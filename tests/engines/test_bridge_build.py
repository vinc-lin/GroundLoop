"""build_entity_map walks a CodeWiki module_tree into a doc->source EntityMap (module_tree-only,
no CBM). Covers the recursive walk, symbol/file split, file_only confidence, child path inheritance,
tolerance of components with no '::', and a save->load round-trip."""
from __future__ import annotations

from groundloop.engines.lore.bridge.build import build_entity_map
from groundloop.engines.lore.bridge.schema import (
    CONFIDENCE,
    load_entity_map,
    save_entity_map,
)
from groundloop.engines.lore.wiki.loader import WikiData


def _wiki():
    """A small nested module_tree: two top-level modules; the first has one child that lacks a
    'path' (must inherit the parent's) and a component with no '::' (tolerated)."""
    module_tree = {
        "Core": {
            "path": "src/core",
            "components": [
                "src/core/foo.py::Foo",
                "src/core/bar.py::Bar",
            ],
            "children": {
                "SubCore": {
                    # no "path" key -> must inherit "src/core"
                    "components": [
                        "src/core/foo.py::Foo",
                        "src/core/baz.py::Baz",
                    ],
                    "children": {},
                },
            },
        },
        "Utils": {
            "path": "src/utils",
            "components": [
                "src/utils/helper.py::Helper",
                "src/utils/bare_no_symbol.py",  # no "::" -> skipped (file-only tolerance)
            ],
            "children": {},
        },
    }
    return WikiData(module_tree=module_tree, metadata={}, docs={},
                    wiki_commit="deadbeef", files_generated=[])


def _module(em, name):
    return next(m for m in em.modules if m.module == name)


def test_build_entity_map_module_tree_only():
    em = build_entity_map(_wiki(), repo_head="abc123")

    # Every node (top-level AND nested child) becomes a ModuleMap.
    names = {m.module for m in em.modules}
    assert names == {"Core", "SubCore", "Utils"}

    assert em.built_at_repo_head == "abc123"
    assert em.wiki_commit == "deadbeef"
    assert em.graph_commit is None

    core = _module(em, "Core")
    assert core.wiki_page == "Core.md"
    assert core.path == "src/core"
    assert {(e.symbol, e.file) for e in core.entries} == {
        ("Foo", "src/core/foo.py"), ("Bar", "src/core/bar.py")}

    # Every module_tree-only entry is file_only, weight 0.5, no CBM node/lines, not stale.
    for e in core.entries:
        assert e.match_strategy == "file_only"
        assert e.confidence == CONFIDENCE["file_only"] == 0.5
        assert e.cbm_node_id is None
        assert e.lines is None
        assert e.stale is False


def test_child_inherits_parent_path():
    em = build_entity_map(_wiki(), repo_head="")
    sub = _module(em, "SubCore")
    assert sub.path == "src/core"      # inherited from "Core"
    assert {(e.symbol, e.file) for e in sub.entries} == {
        ("Foo", "src/core/foo.py"), ("Baz", "src/core/baz.py")}


def test_component_without_separator_is_skipped():
    em = build_entity_map(_wiki(), repo_head="")
    utils = _module(em, "Utils")
    # "src/utils/bare_no_symbol.py" (no "::") is skipped; only Helper remains.
    assert {(e.symbol, e.file) for e in utils.entries} == {("Helper", "src/utils/helper.py")}


def test_empty_module_tree_yields_no_modules():
    wiki = WikiData(module_tree={}, metadata={}, docs={}, wiki_commit=None, files_generated=[])
    em = build_entity_map(wiki, repo_head="x")
    assert em.modules == []
    assert em.wiki_commit is None


def test_save_load_round_trip(tmp_path):
    em = build_entity_map(_wiki(), repo_head="abc123")
    path = tmp_path / "entity_map.json"
    save_entity_map(em, str(path))
    back = load_entity_map(str(path))

    assert back.built_at_repo_head == em.built_at_repo_head
    assert back.wiki_commit == em.wiki_commit
    assert {m.module for m in back.modules} == {m.module for m in em.modules}
    core_before = {(e.symbol, e.file, e.match_strategy, e.confidence)
                   for e in _module(em, "Core").entries}
    core_after = {(e.symbol, e.file, e.match_strategy, e.confidence)
                  for e in _module(back, "Core").entries}
    assert core_before == core_after
