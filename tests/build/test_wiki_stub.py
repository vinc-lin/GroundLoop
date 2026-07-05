import json
from groundloop.build.wiki_stub import ensure_indexable_wiki
from groundloop.engines.lore.wiki.loader import load_wiki


def test_creates_minimal_wiki_when_missing(tmp_path):
    w = tmp_path / "wiki"
    wrote = ensure_indexable_wiki(str(w))
    assert wrote is True
    assert (w / "module_tree.json").is_file() and (w / "metadata.json").is_file()
    data = load_wiki(str(w))          # load_wiki now succeeds (0 docs)
    assert data.docs == {}
    assert json.loads((w / "metadata.json").read_text())["files_generated"] == []


def test_lists_existing_md_as_generated(tmp_path):
    w = tmp_path / "wiki"
    w.mkdir()
    (w / "Foo.md").write_text("# Foo module\n\nsome real doc text here")
    (w / "Bar.md").write_text("# Bar module\n\nmore doc text")
    ensure_indexable_wiki(str(w))
    gen = json.loads((w / "metadata.json").read_text())["files_generated"]
    assert set(gen) == {"Foo.md", "Bar.md"}
    data = load_wiki(str(w))          # partial produce docs are salvaged as doc units
    assert set(data.docs) == {"Foo.md", "Bar.md"}


def test_noop_when_metadata_already_present(tmp_path):
    w = tmp_path / "wiki"
    w.mkdir()
    (w / "module_tree.json").write_text('{"real": "tree"}')
    (w / "metadata.json").write_text('{"files_generated": ["X.md"]}')
    wrote = ensure_indexable_wiki(str(w))
    assert wrote is False             # respects a real produced wiki
    assert json.loads((w / "module_tree.json").read_text()) == {"real": "tree"}
    assert json.loads((w / "metadata.json").read_text())["files_generated"] == ["X.md"]
