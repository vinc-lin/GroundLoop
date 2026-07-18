"""`gloop run --localize cascade` wires the recall-first CascadeLocalizeIndex at the composition root.

Unlike `--localize rerank` (which FAILS-FAST without an embedder because its vector candidate-gen would
silently die), cascade DEGRADES GRACEFULLY: with no embedder the bge-m3 semantic tier is simply omitted
and the crash-tokens + literal-anchor FTS tiers still fire. So the no-embedder path must STILL build a
SplitIndex over a CascadeLocalizeIndex, with the cascade's semantic tier None. Composition-root test via
main() — no live gateway (the autouse KLOOP_DEV fixture is active suite-wide)."""
from __future__ import annotations


def test_localize_cascade_wraps_split_over_cascade_no_embedder(monkeypatch):
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: None)   # no embedder -> semantic omitted, still builds
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned",
              "--match-arm", "flood", "--localize", "cascade"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, CascadeLocalizeIndex)
    assert idx._localize._semantic is None       # graceful degrade with no embedder


def test_localize_cascade_builds_semantic_tier_with_embedder(monkeypatch, tmp_path):
    """With an embedder present the cascade's semantic tier is a SemanticAtlasIndex (bge-m3 fallback).
    Point --index-db at a fresh empty Store db so SemanticAtlasIndex._check_dim early-returns (empty
    vectors table) — keeps the test hermetic (the stub embedder is never actually probed)."""
    class _StubEmbedder:
        def embed(self, texts):
            return [[0.0] for _ in texts]

    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: _StubEmbedder())
    db = tmp_path / "empty.db"
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
    from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", str(db), "--out", str(tmp_path / "o"), "--repos", "r", "--fixer", "canned",
              "--match-arm", "flood", "--localize", "cascade"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, CascadeLocalizeIndex)
    assert isinstance(idx._localize._semantic, SemanticAtlasIndex)
