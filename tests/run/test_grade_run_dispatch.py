import json
from groundloop.run.grade_run import _localize_index_for, _signals_from_doc
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals


def test_localize_index_for_reads_manifest_arm(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "atlas"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and arm == "atlas"


def test_localize_index_for_dispatch_without_embedder_degrades(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "dispatch"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and "atlas" in arm   # no embedder -> FTS5 fallback


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
    from groundloop.domains.android_ivi.functional_signals import PROSE_MARK, is_functional_localize
    class _Doc:
        signals = {"symbols": [PROSE_MARK + "wrong ui label"]}   # JSON round-trip = list of str
    sig = _signals_from_doc(_Doc())
    assert sig.symbols[0].startswith(PROSE_MARK)
    assert is_functional_localize(sig) is True                    # would route to the functional retriever
