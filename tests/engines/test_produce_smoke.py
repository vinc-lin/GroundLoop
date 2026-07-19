"""Hermetic smoke tests for the migrated codewiki package.

Tests:
 - import codewiki works
 - gloop produce --repo <path> --out <wiki_dir> dispatches the generator with correct args and rc 0
"""
from __future__ import annotations



def test_produce_package_importable():
    """The migrated produce package must be importable at module level."""
    import codewiki  # noqa: F401


def test_gloop_produce_dispatches_generator_hermetic(tmp_path, monkeypatch):
    """gloop produce --repo <path> --out <dir> dispatches CLIDocumentationGenerator.generate()
    and returns rc 0.  The generator is monkeypatched to a no-op so no LLM is needed."""
    from pathlib import Path

    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    out_dir = tmp_path / "wiki"

    captured: dict = {}

    class _FakeJob:
        files_generated: list = []
        module_count: int = 0

        class statistics:
            total_files_analyzed = 0
            total_tokens_used = 0

    def _fake_init(self, repo_path, output_dir, config, verbose=False, generate_html=False):
        captured["repo_path"] = repo_path
        captured["output_dir"] = output_dir
        captured["config"] = config

    def _fake_generate(self):
        # Write minimal output so the command can report success
        captured["output_dir"].mkdir(parents=True, exist_ok=True)
        (captured["output_dir"] / "overview.md").write_text("# overview")
        return _FakeJob()

    import importlib
    _dg_mod = importlib.import_module("codewiki.cli.adapters.doc_generator")

    monkeypatch.setattr(_dg_mod.CLIDocumentationGenerator, "__init__", _fake_init)
    monkeypatch.setattr(_dg_mod.CLIDocumentationGenerator, "generate", _fake_generate)

    from groundloop.cli import main

    rc = main(["produce", "--repo", str(repo_dir), "--out", str(out_dir)])
    assert rc == 0, f"expected rc 0, got {rc}"
    assert Path(captured["repo_path"]) == repo_dir
    assert Path(captured["output_dir"]) == out_dir
