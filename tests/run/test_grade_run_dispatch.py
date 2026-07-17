import json
from groundloop.run.grade_run import _localize_index_for, _signals_from_doc
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals


def test_localize_index_for_reads_manifest_arm(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "atlas"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and arm == "atlas"


def test_localize_index_for_dispatch_is_retired_to_atlas(tmp_path):
    """localize `dispatch` was archived (2026-07-16): a historical dispatch run grades on the FTS5 floor."""
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "dispatch"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and arm == "dispatch->atlas(retired)"


def test_localize_index_for_missing_manifest_defaults_atlas(tmp_path):
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and arm == "atlas"


def test_signals_from_doc_reconstructs_from_dict():
    class _Doc:
        signals = {"classes": ["com.x.Foo"], "symbols": [], "bogus": ["drop-me"]}
    sig = _signals_from_doc(_Doc())
    assert isinstance(sig, Signals) and sig.classes == ("com.x.Foo",)


def test_signals_from_doc_handles_missing_signals():
    class _Doc:
        signals = None
    assert _signals_from_doc(_Doc()) == Signals()


def test_signals_from_doc_preserves_prose_mark():
    from groundloop.domains.android_ivi.functional_signals import PROSE_MARK
    class _Doc:
        signals = {"symbols": [PROSE_MARK + "wrong ui label"]}   # JSON round-trip = list of str
    sig = _signals_from_doc(_Doc())
    assert sig.symbols[0].startswith(PROSE_MARK)


def test_localize_index_for_tokens_needs_no_embedder(tmp_path):
    import json as _json
    from groundloop.run.grade_run import _localize_index_for
    from groundloop.adapters.index.signal_query import SignalQueryIndex
    (tmp_path / "manifest.json").write_text(_json.dumps({"localize": "tokens"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)   # embedder=None
    assert isinstance(idx, SignalQueryIndex) and arm == "tokens"


def test_localize_index_for_rerank_builds_reranklocalizeindex(tmp_path):
    """A `--localize rerank` run grades on the reranker's grounded candidate POOL (judge=None offline):
    with an embedder present the isolated diagnostic reconstructs a RerankLocalizeIndex labelled
    `rerank(no-judge:pool)`."""
    from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "rerank"}))
    idx, arm = _localize_index_for(str(tmp_path), str(tmp_path / "atlas.db"), object())  # embedder present
    assert isinstance(idx, RerankLocalizeIndex) and arm == "rerank(no-judge:pool)"
    assert idx.judge is None      # no LLM judge offline -> pool order is the graded ceiling


def test_localize_index_for_rerank_fail_fast_without_embedder(tmp_path):
    """A `--localize rerank` run grades its vector candidate-gen — no embedder must fail-fast (same as the
    live run's guard) so the isolated diagnostic can't silently degrade to a keyword-only reranker."""
    import pytest
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "rerank"}))
    with pytest.raises(RuntimeError, match="embedder"):
        _localize_index_for(str(tmp_path), str(tmp_path / "atlas.db"), None)   # embedder=None
