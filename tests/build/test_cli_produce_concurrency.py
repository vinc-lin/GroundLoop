"""The produce CLI must expose --concurrency and feed it into the generator config."""
from __future__ import annotations

import importlib

import groundloop.cli as cli

# groundloop/engines/produce/__init__.py does `from ...cli.main import cli`, which
# shadows the `cli` *submodule* attribute on the `produce` package with the click
# Group object of the same name. That breaks pytest's string-based monkeypatch
# target resolution (it walks attributes: produce.cli.adapters... and hits the
# Group instead of the `cli` package, then AttributeErrors on `.adapters`).
# `importlib.import_module` resolves via sys.modules instead of attribute
# traversal, so it isn't affected — use it to get the real module object and
# patch the attribute on it directly.
_doc_generator_mod = importlib.import_module(
    "groundloop.engines.produce.cli.adapters.doc_generator"
)


class _FakeGen:
    """Stand-in for CLIDocumentationGenerator: captures config, runs no real produce/LLM."""

    captured: dict | None = None

    def __init__(self, *, repo_path, output_dir, config, verbose):
        _FakeGen.captured = config

    def generate(self):
        return None


def _run_produce(monkeypatch, tmp_path, *extra_args):
    """Run `gloop produce` with the generator faked out; return the captured config."""
    _FakeGen.captured = None
    monkeypatch.setattr(_doc_generator_mod, "CLIDocumentationGenerator", _FakeGen)
    rc = cli.main(["produce", "--repo", str(tmp_path), "--out", str(tmp_path / "wiki"),
                   *extra_args])
    assert rc == 0
    assert _FakeGen.captured is not None
    return _FakeGen.captured


def test_produce_concurrency_flag_reaches_config(monkeypatch, tmp_path):
    config = _run_produce(monkeypatch, tmp_path, "--concurrency", "5")
    assert config["concurrency"] == 5


def test_produce_concurrency_defaults_to_one(monkeypatch, tmp_path):
    monkeypatch.delenv("KLOOP_PRODUCE_CONCURRENCY", raising=False)
    config = _run_produce(monkeypatch, tmp_path)
    assert config["concurrency"] == 1


def test_produce_concurrency_reads_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("KLOOP_PRODUCE_CONCURRENCY", "7")
    config = _run_produce(monkeypatch, tmp_path)
    assert config["concurrency"] == 7


def test_produce_concurrency_flag_overrides_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("KLOOP_PRODUCE_CONCURRENCY", "7")
    config = _run_produce(monkeypatch, tmp_path, "--concurrency", "3")
    assert config["concurrency"] == 3
