"""Behaviour tests for the migrated atlas helper modules."""
from __future__ import annotations


def test_chunk_markdown_yields_heading_body():
    from groundloop.engines.atlas.chunk import chunk_markdown

    chunks = chunk_markdown("# H\nbody")
    assert chunks == [("H", "body")]


def test_extract_symbol_source_returns_signature():
    from groundloop.engines.atlas.symbol_source import extract_symbol_source

    src = "// doc comment\nvoid myFunc(int x) {\n    return;\n}\n"
    result = extract_symbol_source(src, "myFunc", start_line=2, end_line=4)
    assert "myFunc" in result


def test_repo_tokens_returns_identifiers(tmp_path):
    from groundloop.engines.atlas.source_probe import repo_tokens

    src_file = tmp_path / "sample.py"
    src_file.write_text("def hello_world():\n    pass\n")
    tokens = repo_tokens(str(tmp_path))
    assert "hello_world" in tokens
