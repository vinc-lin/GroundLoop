"""Hermetic test for the pure build_units() function in engines/atlas/index.py.

No CBM, no network, no embedder — just wiki + symbol rows -> Units.
"""
from __future__ import annotations


class _FakeWiki:
    """Minimal wiki stub with no doc files."""

    def __init__(self):
        self.docs: dict[str, str] = {}


def test_build_units_symbol_row_produces_one_symbol_unit():
    from groundloop.engines.atlas.index import build_units

    wiki = _FakeWiki()
    symbol_rows = [
        {
            "name": "CGEImageHandler",
            "qualified_name": "org.wysaid.nativePort.CGEImageHandler",
            "label": "class",
            "file_path": "src/CGEImageHandlerAndroid.cpp",
            "start_line": 10,
            "end_line": 50,
        }
    ]

    units = build_units(wiki, symbol_rows, repo="android-gpuimage-plus", repo_head="deadbeef")

    assert len(units) == 1
    u = units[0]
    assert u.kind == "symbol"
    assert u.name == "CGEImageHandler"
    assert u.qualified_name == "org.wysaid.nativePort.CGEImageHandler"
    assert u.repo == "android-gpuimage-plus"
    assert u.repo_head == "deadbeef"


def test_build_units_empty_wiki_empty_rows_returns_empty():
    from groundloop.engines.atlas.index import build_units

    wiki = _FakeWiki()
    units = build_units(wiki, [], repo="some-repo", repo_head="abc123")
    assert units == []
