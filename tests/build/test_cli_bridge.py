"""gloop bridge --registry <atlas.toml>: for each repo, load its wiki and write a doc->source
entity_map.json (module_tree-only, no CBM). Empty wikis are skipped with a note."""
from __future__ import annotations

import json

from groundloop.cli import main
from groundloop.engines.lore.bridge.schema import load_entity_map


def _write_wiki(wiki_dir, module_tree):
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "module_tree.json").write_text(json.dumps(module_tree))
    (wiki_dir / "metadata.json").write_text(json.dumps({"files_generated": ["overview.md"]}))


def test_gloop_bridge_writes_entity_map(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_REGISTRY", raising=False)
    wiki_dir = tmp_path / "_wiki" / "repoA"
    _write_wiki(wiki_dir, {
        "Core": {
            "path": "src/core",
            "components": ["src/core/foo.py::Foo", "src/core/bar.py::Bar"],
            "children": {
                "Sub": {"components": ["src/core/baz.py::Baz"], "children": {}},
            },
        },
    })

    registry = tmp_path / "atlas.toml"
    registry.write_text(
        f'[[repo]]\nname = "repoA"\nrepo_path = "{tmp_path / "repoA"}"\n'
        f'wiki_dir = "{wiki_dir}"\n'
    )

    rc = main(["bridge", "--registry", str(registry)])
    assert rc == 0

    # Default out path is <wiki_dir>/entity_map.json.
    out = wiki_dir / "entity_map.json"
    assert out.is_file()
    em = load_entity_map(str(out))
    assert {m.module for m in em.modules} == {"Core", "Sub"}
    core = next(m for m in em.modules if m.module == "Core")
    assert {(e.symbol, e.file) for e in core.entries} == {
        ("Foo", "src/core/foo.py"), ("Bar", "src/core/bar.py")}
    assert all(e.match_strategy == "file_only" for e in core.entries)

    printed = capsys.readouterr().out
    assert "repoA" in printed and "2 modules" in printed


def test_gloop_bridge_honors_entity_map_path_and_skips_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_REGISTRY", raising=False)
    # repoA has content and an explicit entity_map path; repoB is an empty wiki (skipped).
    wiki_a = tmp_path / "_wiki" / "repoA"
    _write_wiki(wiki_a, {"M": {"path": "p", "components": ["p/x.py::X"], "children": {}}})
    em_path = tmp_path / "custom_entity_map.json"

    wiki_b = tmp_path / "_wiki" / "repoB"
    _write_wiki(wiki_b, {})  # empty module_tree -> skipped

    registry = tmp_path / "atlas.toml"
    registry.write_text(
        f'[[repo]]\nname = "repoA"\nrepo_path = "{tmp_path / "repoA"}"\n'
        f'wiki_dir = "{wiki_a}"\nentity_map = "{em_path}"\n\n'
        f'[[repo]]\nname = "repoB"\nrepo_path = "{tmp_path / "repoB"}"\n'
        f'wiki_dir = "{wiki_b}"\n'
    )

    rc = main(["bridge", "--registry", str(registry)])
    assert rc == 0
    assert em_path.is_file()                              # written to the explicit path
    assert not (wiki_a / "entity_map.json").is_file()      # NOT the default path
    assert not (wiki_b / "entity_map.json").is_file()      # repoB skipped, nothing written

    em = load_entity_map(str(em_path))
    assert {(e.symbol, e.file) for m in em.modules for e in m.entries} == {("X", "p/x.py")}

    printed = capsys.readouterr().out
    assert "repoB" in printed and "SKIP" in printed


def test_gloop_bridge_requires_registry(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_REGISTRY", raising=False)
    rc = main(["bridge"])
    assert rc == 2
    assert "registry" in capsys.readouterr().out.lower()
