"""Full real-build acceptance: produce + CBM + embed -> atlas.db.

RUNBOOK
-------
This test is the M1 milestone acceptance. Run it on a machine that has:

  - An LLM API key (for gloop produce / CodeWiki wiki generation)
  - The CBM server accessible (codebase-memory-mcp 0.8.1 installed or reachable)
  - An embedding gateway running (bge-m3 compatible)

Exact acceptance command::

    KLOOP_PRODUCE_READY=1 \\
    KLOOP_CBM_READY=1 \\
    KLOOP_EMBED_API_KEY=<key> \\
    KLOOP_EMBED_BASE_URL=http://localhost:8080 \\
    KLOOP_PRODUCE_API_KEY=<llm_api_key> \\
    KLOOP_PRODUCE_BASE_URL=http://localhost:11434/v1 \\
    pytest tests/e2e/test_index_build_live.py -v

What the test does:

  1. Creates a tiny real git repo with a handful of Python source files
     containing identifiable class/function names.
  2. Runs ``gloop produce --repo <repo> --out <wiki_dir>`` (LLM-based doc
     generation) to produce the wiki (source of *doc* units).
  3. Writes a minimal ``atlas.toml`` registry pointing at the repo + wiki.
  4. Runs ``gloop index --registry <atlas.toml>`` (CBM extracts *symbol*
     units; embedding gateway embeds all units into atlas.db).
  5. Opens the resulting ``atlas.db`` and asserts:
       - The ``repos`` row exists with ``unit_count > 0``.
       - Both ``doc`` and ``symbol`` unit kinds are present.
       - ``AtlasIndex.rank_repos`` retrieves a known symbol from the repo.

CI hermetic gate:
  The ``skipif`` guard means the file always collects and cleanly skips in
  CI (where CBM/embed/LLM are unavailable).  The live run is the milestone
  DONE criterion, not a throwaway.
"""
from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# Gate — all three services must be declared ready
# All groundloop/CBM/embed imports are guarded inside the test body so this
# module always collects cleanly even when services are unavailable.
# ---------------------------------------------------------------------------
_EMBED_API_KEY = os.environ.get("KLOOP_EMBED_API_KEY", "").strip()
_CBM_READY = os.environ.get("KLOOP_CBM_READY", "").strip() in ("1", "true", "yes")
_PRODUCE_READY = os.environ.get("KLOOP_PRODUCE_READY", "").strip() in ("1", "true", "yes")

_GATE = bool(_EMBED_API_KEY and _CBM_READY and _PRODUCE_READY)

_SKIP_REASON = (
    "Live services not declared ready — "
    "set KLOOP_EMBED_API_KEY + KLOOP_CBM_READY=1 + KLOOP_PRODUCE_READY=1"
)


@pytest.mark.skipif(not _GATE, reason=_SKIP_REASON)
def test_full_index_build_produce_cbm_embed(tmp_path):
    """Live acceptance: produce wiki + CBM symbols + embed -> atlas.db."""
    import subprocess
    import sys

    # -- All service-dependent / optional-dep imports are guarded here -------
    from groundloop.engines.atlas.store import Store  # noqa: PLC0415
    from groundloop.adapters.index.atlas import AtlasIndex  # noqa: PLC0415
    from groundloop.core.types import RepoRef, Signals  # noqa: PLC0415

    # 1. Create a tiny real git repo with identifiable Python symbols
    repo_dir = tmp_path / "tiny_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test"],
                   check=True, capture_output=True)

    (repo_dir / "widget.py").write_text(
        '"""Widget management module."""\n\n'
        "class WidgetManager:\n"
        '    """Manages widgets for the UI layer."""\n\n'
        "    def create_widget(self, name: str) -> 'Widget':\n"
        "        return Widget(name)\n\n"
        "    def list_widgets(self) -> list:\n"
        "        return []\n\n\n"
        "class Widget:\n"
        '    """A single UI widget."""\n\n'
        "    def __init__(self, name: str) -> None:\n"
        "        self.name = name\n"
    )
    (repo_dir / "utils.py").write_text(
        '"""Utility functions."""\n\n'
        "def format_widget_name(name: str) -> str:\n"
        '    """Normalise a widget name."""\n'
        "    return name.strip().lower()\n"
    )
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "--no-gpg-sign", "-m", "init"],
                   check=True, capture_output=True)

    # 2. gloop produce -- generate wiki (produces doc units)
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "groundloop.cli", "produce",
         "--repo", str(repo_dir),
         "--out", str(wiki_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"gloop produce failed (rc={result.returncode})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert (wiki_dir / "module_tree.json").exists(), "produce: module_tree.json missing"
    assert (wiki_dir / "metadata.json").exists(), "produce: metadata.json missing"

    # 3. Write atlas.toml registry
    atlas_toml = tmp_path / "atlas.toml"
    atlas_db = tmp_path / "atlas.db"
    atlas_toml.write_text(
        "[[repo]]\n"
        'name = "tiny_repo"\n'
        f'repo_path = "{repo_dir}"\n'
        f'wiki_dir = "{wiki_dir}"\n'
        'entity_map = ""\n'
    )

    # 4. gloop index -- CBM extracts symbol units; embed gateway embeds all
    embed_base_url = os.environ.get("KLOOP_EMBED_BASE_URL", "")
    result = subprocess.run(
        [sys.executable, "-m", "groundloop.cli", "index",
         "--registry", str(atlas_toml)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "KLOOP_ATLAS_DB": str(atlas_db),
            "KLOOP_EMBED_API_KEY": _EMBED_API_KEY,
            "KLOOP_EMBED_BASE_URL": embed_base_url,
        },
    )
    assert result.returncode == 0, (
        f"gloop index failed (rc={result.returncode})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "indexed tiny_repo:" in result.stdout, (
        f"Expected 'indexed tiny_repo:' in output; got:\n{result.stdout}"
    )

    # 5. Assert atlas.db is usable and contains both doc + symbol units
    assert atlas_db.exists(), "atlas.db was not created"
    store = Store(str(atlas_db))
    repo_states = store.list_repo_states()
    assert repo_states, "atlas.db has no repos rows"
    rs = next((s for s in repo_states if s.repo == "tiny_repo"), None)
    assert rs is not None, "tiny_repo not found in atlas.db repos table"
    assert rs.unit_count > 0, "unit_count == 0 for tiny_repo — expected > 0"

    kinds = {row[0] for row in store.db.execute(
        "SELECT DISTINCT kind FROM units WHERE repo='tiny_repo'"
    )}
    assert "symbol" in kinds, (
        f"No symbol units found in atlas.db; kinds present: {kinds}"
    )
    assert "doc" in kinds, (
        f"No doc units found in atlas.db; kinds present: {kinds}"
    )

    # 6. AtlasIndex retrieves a known symbol from the live atlas.db
    idx = AtlasIndex(str(atlas_db))
    sig = Signals(classes=("WidgetManager",), packages=(), libraries=())
    catalog = [RepoRef("tiny_repo")]
    ranked = idx.rank_repos(sig, catalog)
    assert ranked, "AtlasIndex.rank_repos returned empty list"
    assert ranked[0].score > 0, (
        "AtlasIndex could not retrieve 'WidgetManager' from atlas.db — "
        "symbol units may be missing or search query returned no hits"
    )
    assert ranked[0].repo.name == "tiny_repo", (
        f"Expected tiny_repo as top result; got {ranked[0].repo.name}"
    )
