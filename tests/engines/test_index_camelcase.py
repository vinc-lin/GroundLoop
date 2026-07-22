"""Index-time CamelCase expansion, KLOOP_INDEX_CAMELCASE — **default ON since 2026-07-21 (owner override)**.

The FTS5 tokenizer (unicode61) does not split CamelCase, so an indexed symbol
`ScreenshotUtils` becomes the atomic token `screenshotutils` and a plain-word
query `screenshot` cannot match it. With expansion ON (now the default), index_repo
appends the identifier sub-words to the unit text so `screenshot` matches — an
`[authored]` match lever. `KLOOP_INDEX_CAMELCASE=0` opts out to the plain atlas.
Takes effect on the NEXT re-index (a reuse-contract change)."""
from groundloop.engines.atlas.index import build_units
from groundloop.engines.atlas.store import Store


def _index_screenshot_symbol(db_path: str) -> Store:
    """Index a repo holding one `ScreenshotUtils` symbol; the setting is read at
    index time inside build_units (env, via Settings.load())."""
    row = {
        "name": "ScreenshotUtils",
        "qualified_name": "com.example.ScreenshotUtils",
        "file_path": "com/example/ScreenshotUtils.java",
    }
    units = build_units(None, [row], repo="r", repo_head="h")
    store = Store(db_path)
    store.reindex_repo("r", list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return store


def test_camelcase_on_makes_subword_searchable(tmp_path, monkeypatch):
    monkeypatch.setenv("KLOOP_INDEX_CAMELCASE", "1")
    store = _index_screenshot_symbol(str(tmp_path / "atlas.db"))
    hits = store.keyword_search("screenshot", k=5, repos=["r"], kinds=["symbol"])
    assert any(u.name == "ScreenshotUtils" for u, _rank in hits)


def test_camelcase_on_by_default_makes_subword_searchable(tmp_path, monkeypatch):
    """Env UNSET -> expansion is ON (the 2026-07-21 default) -> the sub-word matches."""
    monkeypatch.delenv("KLOOP_INDEX_CAMELCASE", raising=False)
    store = _index_screenshot_symbol(str(tmp_path / "atlas.db"))
    hits = store.keyword_search("screenshot", k=5, repos=["r"], kinds=["symbol"])
    assert any(u.name == "ScreenshotUtils" for u, _rank in hits)


def test_camelcase_explicit_off_leaves_atomic_token_unmatchable(tmp_path, monkeypatch):
    """KLOOP_INDEX_CAMELCASE=0 is the explicit opt-out -> the atomic token stays unmatchable."""
    monkeypatch.setenv("KLOOP_INDEX_CAMELCASE", "0")
    store = _index_screenshot_symbol(str(tmp_path / "atlas.db"))
    hits = store.keyword_search("screenshot", k=5, repos=["r"], kinds=["symbol"])
    assert hits == []
