"""`gloop run --localize {atlas,tokens}` chooses the localize retriever independently of --match-arm.
When localize differs from the match arm's native retrieve, the built index is wrapped in a SplitIndex
(rank from the match index, retrieve from the localize index). Composition-root tests via main() — no
live gateway (the autouse KLOOP_DEV fixture is active suite-wide)."""
from __future__ import annotations


def test_semantic_match_atlas_localize_wraps_in_split_index(monkeypatch):
    """`--match-arm semantic` (vector match) with the default `atlas` localize wraps the built index in a
    SplitIndex whose retrieve is the FTS5 AtlasIndex — so localize stays FTS5 under a vector match. We stub
    the embedder + SemanticAtlasIndex; assert the composed index is a SplitIndex."""
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: object())
    import groundloop.adapters.index.labs.atlas_semantic as sem
    monkeypatch.setattr(sem, "SemanticAtlasIndex", lambda db, emb: ("sem", db))
    seen = {}
    import groundloop.run.batch as batch

    def _spy(dataset, **kw):
        seen["index"] = kw.get("index")
        return 0
    monkeypatch.setattr(batch, "run_dataset", _spy)
    # need the --fixer/--repos guards to pass: use --fixer canned (dev-gated; KLOOP_DEV autouse is on)
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned",
              "--match-arm", "semantic", "--localize", "atlas"])
    except Exception:
        pass
    from groundloop.adapters.index.labs.split import SplitIndex
    assert isinstance(seen.get("index"), SplitIndex)   # semantic match, FTS5 localize -> split


def _captured_index(monkeypatch, extra):
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned",
              "--match-arm", "flood", *extra])
    except Exception:
        pass
    return seen.get("index")


def test_localize_atlas_explicit_no_wrap(monkeypatch):
    """Explicit --localize atlas with a non-semantic match leaves the index unwrapped (the reversible
    opt-out from the tokens default): neither a SplitIndex nor a SignalQueryIndex."""
    from groundloop.adapters.index.labs.split import SplitIndex
    from groundloop.adapters.index.labs.signal_query import SignalQueryIndex
    idx = _captured_index(monkeypatch, ["--localize", "atlas"])
    assert not isinstance(idx, (SplitIndex, SignalQueryIndex))


def test_localize_default_is_atlas_unwrapped(monkeypatch):
    """Core default (no --localize) is `atlas` — the [production]-validated FTS5 floor — so the index is
    left unwrapped (neither a SignalQueryIndex nor a SplitIndex). `tokens` was reverted from the default to
    a reachable opt-in on 2026-07-15 (the workflow-simplification pass)."""
    from groundloop.adapters.index.labs.split import SplitIndex
    from groundloop.adapters.index.labs.signal_query import SignalQueryIndex
    idx = _captured_index(monkeypatch, [])   # no --localize -> core default = atlas (unwrapped)
    assert not isinstance(idx, (SplitIndex, SignalQueryIndex))


def test_localize_tokens_explicit_wraps_signalquery(monkeypatch):
    """`--localize tokens` (now an opt-in, no longer the default) still wraps the index in SignalQueryIndex
    so the localize FTS5 query uses the extracted code tokens."""
    from groundloop.adapters.index.labs.signal_query import SignalQueryIndex
    idx = _captured_index(monkeypatch, ["--localize", "tokens"])
    assert isinstance(idx, SignalQueryIndex)


def test_localize_rerank_wraps_split_over_reranker(monkeypatch):
    """`--localize rerank` (opt-in Candidate) wraps the match index in a SplitIndex whose retrieve side is
    the grounded RerankLocalizeIndex — rank stays with the match arm. An embedder must be present (the
    no-embedder path now fail-fasts, see test_localize_rerank_failfast); with no PRODUCE creds judge=None
    (the reranker degrades to the candidate-pool order). The construction must not crash."""
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: object())   # embedder present -> passes guard
    from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.labs.split import SplitIndex
    idx = _captured_index(monkeypatch, ["--localize", "rerank"])
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, RerankLocalizeIndex)
    assert idx._localize.judge is None       # no creds -> degrade to the grounded pool order
