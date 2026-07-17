"""Opt-in index-time CamelCase expansion behind KLOOP_INDEX_CAMELCASE.

The FTS5 tokenizer (unicode61) does not split CamelCase, so an indexed symbol
`ScreenshotUtils` becomes the atomic token `screenshotutils` and a plain-word
query `screenshot` cannot match it. With KLOOP_INDEX_CAMELCASE set, index_repo
appends the identifier sub-words to the unit text so `screenshot` matches. Default
OFF ⇒ the produced text (and thus the atlas) is byte-identical to today."""
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


def test_camelcase_off_default_leaves_atomic_token_unmatchable(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOOP_INDEX_CAMELCASE", raising=False)
    store = _index_screenshot_symbol(str(tmp_path / "atlas.db"))
    hits = store.keyword_search("screenshot", k=5, repos=["r"], kinds=["symbol"])
    assert hits == []
