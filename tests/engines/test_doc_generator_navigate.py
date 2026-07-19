"""Regression: DocumentationGenerator tree-navigation must descend into `children` by INDEX, not by
name-value. A module tree where a child shares its parent module's name (path ['x','x']) used to
KeyError in the `all_leaves` guard (documentation_generator.py:489) and abort the WHOLE repo's doc
generation — the raw failure was cameraview's real 'video_encoding' parent with a 'video_encoding'
child (2026-07-16). The value-comparison `path_part != module_path[-1]` treated the earlier
'video_encoding' as the last element, skipped the children descent, then looked the child key up in
the parent node. Fixed to compare by loop index in _navigate + the sequential loop + build_overview.

Hermetic: pure tree walking, no LLM / no network. Importing the generator pulls in the produce stack
(a default dep); skip cleanly if that stack is unavailable."""
from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai", reason="produce stack (pydantic_ai) not installed")

from codewiki.src.be.documentation_generator import (  # noqa: E402
    DocumentationGenerator as D,
)

# A leaf whose name collides with its parent module's name (the cameraview shape).
COLLIDING_TREE = {
    "video_encoding": {
        "components": ["c0"],
        "children": {
            "video_encoding": {"components": ["c1"]},   # child shares the PARENT's name
            "audio_encoding": {"components": ["c2"]},
        },
    },
    "controls": {"components": ["c3"]},
}


def test_navigate_descends_by_index_not_name():
    """['video_encoding','video_encoding'] resolves to the CHILD, not KeyError in the parent."""
    node = D._navigate(COLLIDING_TREE, ["video_encoding", "video_encoding"])
    assert node["components"] == ["c1"]


def test_navigate_sibling_child_still_reachable():
    node = D._navigate(COLLIDING_TREE, ["video_encoding", "audio_encoding"])
    assert node["components"] == ["c2"]


def test_navigate_single_element_path():
    node = D._navigate(COLLIDING_TREE, ["controls"])
    assert node["components"] == ["c3"]


def test_navigate_parent_path():
    node = D._navigate(COLLIDING_TREE, ["video_encoding"])
    assert node["components"] == ["c0"] and "children" in node


def test_all_leaves_guard_does_not_crash_on_name_collision():
    """The line-489 concurrency guard (all_leaves over the full processing order) must compute a
    bool without raising — this is the exact expression that aborted cameraview pre-fix."""
    inst = D.__new__(D)                       # pure methods only; skip __init__ (needs a Config)
    order = D.get_processing_order(inst, COLLIDING_TREE)
    all_leaves = all(D.is_leaf_module(inst, D._navigate(COLLIDING_TREE, p)) for p, _ in order)
    assert all_leaves is False                # the parent 'video_encoding' has children
