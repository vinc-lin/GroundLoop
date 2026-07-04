"""Hermetic tests for retrieve.py (rrf_fuse) and registry.py (load_registry).
No network, no embedding gateway required.
"""
from __future__ import annotations

def test_rrf_fuse_pure_ranking():
    from groundloop.engines.atlas.retrieve import rrf_fuse

    # list A ranks: a, b, c  |  list B ranks: b, a, d
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    ids = [item[0] for item in fused]
    scores = {item[0]: item[1] for item in fused}

    # 'a' and 'b' both appear in two lists so they outrank 'c' and 'd'
    assert ids[0] in ("a", "b")
    assert ids[1] in ("a", "b")
    assert scores["a"] > scores["c"]
    assert scores["b"] > scores["d"]

    # scores are strictly positive
    for _id, score in fused:
        assert score > 0.0


def test_rrf_fuse_empty():
    from groundloop.engines.atlas.retrieve import rrf_fuse

    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_rrf_fuse_single_list():
    from groundloop.engines.atlas.retrieve import rrf_fuse

    result = rrf_fuse([["x", "y", "z"]])
    # order preserved, scores decrease monotonically
    ids = [i for i, _ in result]
    assert ids == ["x", "y", "z"]
    scores = [s for _, s in result]
    assert scores[0] > scores[1] > scores[2]


def test_load_registry_parses_toml(tmp_path):
    from groundloop.engines.atlas.registry import load_registry, RepoEntry

    atlas_toml = tmp_path / "atlas.toml"
    atlas_toml.write_text(
        '[[repo]]\n'
        'name = "my-repo"\n'
        'repo_path = "/path/to/repo"\n'
        'wiki_dir = "/path/to/wiki"\n'
        'entity_map = "/path/to/entity_map.json"\n'
        '\n'
        '[[repo]]\n'
        'name = "other-repo"\n'
        'repo_path = "/other/repo"\n'
        'wiki_dir = "/other/wiki"\n',
        encoding="utf-8",
    )
    entries = load_registry(str(atlas_toml))
    assert len(entries) == 2
    assert isinstance(entries[0], RepoEntry)
    assert entries[0].name == "my-repo"
    assert entries[0].repo_path == "/path/to/repo"
    assert entries[0].wiki_dir == "/path/to/wiki"
    assert entries[0].entity_map == "/path/to/entity_map.json"
    # missing entity_map defaults to ""
    assert entries[1].entity_map == ""


def test_load_registry_empty_file(tmp_path):
    from groundloop.engines.atlas.registry import load_registry

    atlas_toml = tmp_path / "empty.toml"
    atlas_toml.write_text("", encoding="utf-8")
    entries = load_registry(str(atlas_toml))
    assert entries == []
