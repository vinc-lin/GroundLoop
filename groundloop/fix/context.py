"""Grounded code-understanding context for the FIX prompt (opt-in Candidate, default OFF).

Today the fix stage sees only `@head` source snippets of the localized files. This module gives the
fixer two richer, GROUNDED context blocks — the same code-understanding the localize reranker already
assembles (`adapters/index/rerank_localize.py`), now injected as a fix-prompt preamble:

  * CodeWiki — for each localized file, its MODULE's CodeWiki `doc`-unit summary. The file->module edge
    comes from the entity_map (`engines/lore/bridge`), the doc text from the atlas store's `doc` units.
  * CBM — for the localized symbols (from the arm signals), the LIVE CBM call-graph: node source
    (`cbm.snippet`) + callers/callees (`cbm.call_neighbors`).

Both renderers mirror `skills/base.render_skills` / `kb/render.render_knowledge`: they return the
`"\n\n# <Header>\n…"` shape and `""` when empty, so the runner concatenates
`preamble = skills + knowledge + codewiki + cbm` cleanly.

GROUNDED: only real doc text / real CBM output reaches the prompt — nothing is synthesized. Fail-safe
throughout: a missing store / entity_map / CBM, or any error, yields `""` (the preamble simply does not
grow). Default OFF -> byte-identical to today. No `core/` or atlas-schema edit.
"""
from __future__ import annotations

import json
from typing import Sequence

from groundloop.core.types import Signals

_CW_HEADER = "\n\n# CodeWiki module summaries"
_CBM_HEADER = "\n\n# Live code-graph context (CBM)"


def render_codewiki(files: Sequence[str], *, provider, max_chars: int = 800) -> str:
    """One block per localized file's MODULE doc summary. `provider.module_doc(file) -> str` ("" on miss);
    blocks are deduped by doc text (N files in one module render once). "" when nothing resolves."""
    if provider is None:
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for f in files:
        try:
            doc = (provider.module_doc(f) or "").strip()
        except Exception:      # noqa: BLE001 — context is best-effort, never sink the fix
            doc = ""
        if not doc or doc in seen:
            continue
        seen.add(doc)
        blocks.append(f"## {f}\n{doc[:max_chars]}")
    if not blocks:
        return ""
    return _CW_HEADER + "\n" + "\n\n".join(blocks)


def render_cbm(symbols: Sequence[str], *, cbm, max_chars: int = 800, max_symbols: int = 4,
               max_neighbors: int = 8) -> str:
    """One block per localized symbol: CBM node source (`snippet`) + callers/callees (`call_neighbors`).
    "" when no cbm / nothing resolves. Per-call fail-safe (a bad symbol never sinks the batch)."""
    if cbm is None:
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        if not sym or sym in seen:
            continue
        seen.add(sym)
        if len(blocks) >= max_symbols:
            break
        parts: list[str] = []
        try:
            snip = cbm.snippet(sym) or ""
        except Exception:      # noqa: BLE001
            snip = ""
        if snip:
            parts.append("source:\n" + snip[:max_chars])
        try:
            neigh = cbm.call_neighbors(sym) or []
        except Exception:      # noqa: BLE001
            neigh = []
        if neigh:
            parts.append("calls: " + ", ".join(str(n) for n in neigh[:max_neighbors]))
        if parts:
            blocks.append(f"## {sym}\n" + "\n".join(parts))
    if not blocks:
        return ""
    return _CBM_HEADER + "\n" + "\n\n".join(blocks)


def _symbols_for(signals: Signals | None) -> list[str]:
    """Ordered, deduped symbol/method/class short-names from the arm signals -> the CBM query set.
    Methods/native symbols first (the strongest call-graph anchors), then classes."""
    if signals is None:
        return []
    out: list[str] = []
    for group in (signals.methods, signals.symbols, signals.classes):
        for s in group:
            if s and s not in out:
                out.append(s)
    return out


class _RepoDocs:
    """Repo-bound CodeWiki doc source for `render_codewiki` (the renderer takes no repo handle)."""
    def __init__(self, provider: "FixContextProvider", repo: str):
        self._p = provider
        self._repo = repo

    def module_doc(self, file: str) -> str:
        return self._p.module_doc(self._repo, file)


class FixContextProvider:
    """Runner-held provider: yields the (codewiki, cbm) fix-prompt preambles for one case.

    Holds the atlas `store` (doc-unit text), an `entity_map` (an `EntityMap` OR a callable
    `repo -> EntityMap|None` — the file->module bridge), and a `cbm` facade (a `CBMLiveGraph` OR a
    callable `repo -> facade|None`). Any of the three may be absent -> the corresponding preamble is "".
    Fail-safe: any error degrades to "". Opt-in Candidate; the runner constructs it once and reuses it.
    """

    def __init__(self, *, store=None, entity_map=None, cbm=None, max_chars: int = 800,
                 max_files: int = 6):
        self.store = store
        self.entity_map = entity_map
        self.cbm = cbm
        self.max_chars = max_chars
        self.max_files = max_files
        self._lut_cache: dict[int, dict[str, tuple[str, str]]] = {}
        self._doc_cache: dict[tuple[str, str], str] = {}

    def preambles(self, repo: str, files: Sequence[str], signals: Signals | None) -> tuple[str, str]:
        """(codewiki_preamble, cbm_preamble) for this case. Either is "" when its dependency is absent."""
        codewiki = render_codewiki(list(files)[: self.max_files], provider=_RepoDocs(self, repo),
                                   max_chars=self.max_chars)
        cbm = render_cbm(_symbols_for(signals), cbm=self._cbm_for(repo), max_chars=self.max_chars)
        return codewiki, cbm

    # -- CodeWiki: file -> module -> doc text -------------------------------------------------

    def module_doc(self, repo: str, file: str) -> str:
        """The localized file's MODULE CodeWiki summary, or "". Grounded: file->module via the entity_map,
        the summary is the module's real `doc`-unit text from the atlas store."""
        em = self._entity_map_for(repo)
        if em is None or self.store is None:
            return ""
        lut = self._file_module_lut(em)
        info = lut.get(file) or lut.get(file.rsplit("/", 1)[-1])
        if info is None:
            return ""
        module_key, wiki_page = info
        return self._doc_text(repo, module_key, wiki_page)

    def _doc_text(self, repo: str, module_key: str, wiki_page: str) -> str:
        """All `doc`-unit chunks for a module, in `ord` order, joined. Read directly from the atlas
        `units` table (read-only, no schema touch) filtered on repo + kind='doc' + this module — FTS
        keyword_search cannot key on a module (the module name need not appear in the doc text)."""
        key = (repo, module_key or wiki_page or "")
        if key[1] == "":
            return ""
        if key in self._doc_cache:
            return self._doc_cache[key]
        db = getattr(self.store, "db", None)
        rows = []
        if db is not None:
            try:
                rows = db.execute("SELECT file, text, meta FROM units WHERE repo=? AND kind='doc'",
                                  (repo,)).fetchall()
            except Exception:  # noqa: BLE001 — no atlas / read error -> no doc context
                rows = []
        wiki_base = (wiki_page or "").rsplit("/", 1)[-1]
        matched: list[tuple[int, str]] = []
        for r in rows:
            try:
                meta = json.loads(r["meta"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            um = meta.get("module")
            ufile = (r["file"] or "").rsplit("/", 1)[-1]
            if (module_key and um == module_key) or (wiki_base and ufile == wiki_base):
                try:
                    ordv = int(meta.get("ord", 0) or 0)
                except (TypeError, ValueError):
                    ordv = 0
                matched.append((ordv, r["text"] or ""))
        matched.sort(key=lambda t: t[0])
        text = "\n\n".join(t for _o, t in matched if t)
        self._doc_cache[key] = text
        return text

    def _file_module_lut(self, em) -> dict[str, tuple[str, str]]:
        """source file (and its basename) -> (module_key, wiki_page). Cached per entity_map."""
        cached = self._lut_cache.get(id(em))
        if cached is not None:
            return cached
        lut: dict[str, tuple[str, str]] = {}
        for mm in getattr(em, "modules", []) or []:
            info = (getattr(mm, "module", "") or "", getattr(mm, "wiki_page", "") or "")
            for e in getattr(mm, "entries", []) or []:
                f = getattr(e, "file", None)
                if f and f not in lut:
                    lut[f] = info
                    lut.setdefault(f.rsplit("/", 1)[-1], info)
        self._lut_cache[id(em)] = lut
        return lut

    # -- per-repo resolution (single object OR callable, mirrors RerankLocalizeIndex) ---------

    def _entity_map_for(self, repo: str):
        em = self.entity_map
        if callable(em):
            try:
                return em(repo)
            except Exception:  # noqa: BLE001
                return None
        return em

    def _cbm_for(self, repo: str):
        c = self.cbm
        if callable(c):
            try:
                return c(repo)
            except Exception:  # noqa: BLE001
                return None
        return c
