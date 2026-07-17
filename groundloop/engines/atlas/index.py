from __future__ import annotations

import os
from typing import Optional

from groundloop.config.settings import Settings
from groundloop.engines.atlas.chunk import doc_units
from groundloop.engines.atlas.store import Store, Unit
from groundloop.engines.atlas.registry import RepoEntry
from groundloop.engines.atlas.symbol_source import extract_symbol_source
from groundloop.engines.atlas.tokenize import split_identifier

# CBM's `index_repository` builds the whole symbol graph — seconds on a fast FS, but MINUTES on a
# slow one (e.g. the /mnt/x v9fs mount) or under contention. The CBMClient default (30s) trips
# mid-build, fires call_tool_with_restart's aclose+start on a still-indexing subprocess, and leaves
# the MCP stdio client blocked in poll() forever (0 units, no error). A generous ceiling avoids that;
# query calls return in ms so they never approach it. See docs/type2-atlas-build-findings.md.
DEFAULT_CBM_INDEX_TIMEOUT = 1800.0


def _symbol_unit(row: dict, *, repo: str, repo_head: Optional[str], source_reader=None,
                 camelcase: bool = False) -> Unit:
    name = row.get("name", "")
    qn = row.get("qualified_name") or name
    label = row.get("label", "")
    file = row.get("file_path") or row.get("file")
    text = " ".join(p for p in [name, label, qn, file] if p)
    if source_reader and file:
        src = source_reader(file)
        if src:
            enrich = extract_symbol_source(src, name, int(row.get("start_line") or 0),
                                           int(row.get("end_line") or 0))
            if enrich:
                text = text + "\n" + enrich
    if camelcase:
        # unicode61 does not split CamelCase, so `ScreenshotUtils` is the atomic token
        # `screenshotutils`. Append the identifier sub-words (order-preserving, deduped) so a
        # plain-word query (`screenshot`) matches. Content-only: no new column, no schema change.
        subwords = split_identifier(qn or name)
        for p in split_identifier(name):
            if p not in subwords:
                subwords.append(p)
        if subwords:
            text = text + "\n" + " ".join(subwords)
    return Unit(repo=repo, kind="symbol", name=name, qualified_name=qn, file=file,
                repo_head=repo_head, text=text, meta={"label": label})


def build_units(wiki, symbol_rows: list[dict], *, repo: str,
                repo_head: Optional[str], source_reader=None,
                camelcase: Optional[bool] = None) -> list[Unit]:
    """Pure given the source_reader: wiki + symbol rows -> Units. Tested directly.

    `camelcase` gates index-time identifier expansion (KLOOP_INDEX_CAMELCASE); when None it is
    read from Settings at call time (index time, not import time). Default OFF ⇒ symbol text is
    byte-identical to today."""
    if camelcase is None:
        camelcase = Settings.load().index_camelcase
    units: list[Unit] = []
    docs = getattr(wiki, "docs", {}) or {}
    for fname, text in docs.items():
        module = fname.rsplit(".", 1)[0]
        units += doc_units(text, repo=repo, module=module, file=fname, repo_head=repo_head)
    for row in symbol_rows:
        units.append(_symbol_unit(row, repo=repo, repo_head=repo_head,
                                  source_reader=source_reader, camelcase=camelcase))
    return units


def _make_source_reader(repo_path: str):
    """A repo-relative file reader with a per-file cache (many symbols share a file)."""
    cache: dict = {}
    def read(rel: str) -> str:
        if rel not in cache:
            try:
                with open(os.path.join(repo_path, rel), errors="ignore") as fh:
                    cache[rel] = fh.read()
            except OSError:
                cache[rel] = ""
        return cache[rel]
    return read


async def index_repo(entry: RepoEntry, store: Store, embedder,
                     *, call_timeout: float = DEFAULT_CBM_INDEX_TIMEOUT) -> int:
    """Index one repo end-to-end (IO: wiki load + CBM enumerate + embed + store).

    `call_timeout` is the per-CBM-call ceiling; it must be generous enough to cover a cold
    `index_repository` graph build (see DEFAULT_CBM_INDEX_TIMEOUT).
    Exercised by the gated integration test, not unit tests."""
    from groundloop.engines.lore.wiki.loader import load_wiki
    from groundloop.engines.lore.repo_head import _resolve_repo_head
    from groundloop.engines.lore.deploy import resolve_launch_spec
    from groundloop.engines.lore.graph.client import CBMClient
    from groundloop.engines.lore.graph import forward
    from groundloop.engines.lore.graph.nodes import enumerate_all_nodes

    repo_head = _resolve_repo_head(entry.repo_path, os.environ)
    wiki = load_wiki(entry.wiki_dir)

    spec = resolve_launch_spec(environ=os.environ)
    client = CBMClient(spec.command, env=spec.env, cwd=spec.cwd, call_timeout=call_timeout)
    symbol_rows: list[dict] = []
    try:
        await client.start()
        idx = await forward.index_repository(client, repo_path=entry.repo_path)
        project = idx.get("project") if isinstance(idx, dict) else None
        if not project:
            raise RuntimeError(
                f"CBM index_repository did not return a project id (got: {idx!r})")
        symbol_rows = await enumerate_all_nodes(client, project=project)
    finally:
        await client.aclose()

    units = build_units(wiki, symbol_rows, repo=entry.name, repo_head=repo_head,
                        source_reader=_make_source_reader(entry.repo_path))
    vecs = embedder.embed([u.text for u in units]) if units else []
    store.reindex_repo(entry.name, list(zip(units, vecs)), repo_head=repo_head)
    return len(units)


async def index_all(entries: list[RepoEntry], store: Store, embedder,
                    *, call_timeout: float = DEFAULT_CBM_INDEX_TIMEOUT) -> dict:
    return {e.name: await index_repo(e, store, embedder, call_timeout=call_timeout)
            for e in entries}
