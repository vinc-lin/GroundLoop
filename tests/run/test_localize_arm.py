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


def test_localize_default_is_cascade_judge_wrapped(monkeypatch):
    """Core default (no --localize) is `cascade_judge` (promoted to the core default 2026-07-21 on an owner
    override, `[production]` read pending) — the cascade recall pool (FTS ∪ crash-tokens ∪ literal-anchors ∪
    bge-m3 semantic) reordered by the LLM file-judge — so the built index IS a SplitIndex whose retrieve side
    is a RerankLocalizeIndex whose `_pool_index` is a CascadeLocalizeIndex. With no creds the judge is None
    (degrades to the cascade pool order); with no embedder the cascade omits its bge-m3 tier — neither
    fail-closes."""
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)
    from groundloop.adapters.index.labs.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.labs.split import SplitIndex
    idx = _captured_index(monkeypatch, [])   # no --localize -> core default = cascade_judge
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, RerankLocalizeIndex)
    assert idx._localize.judge is None                              # no creds -> cascade pool order
    assert isinstance(idx._localize._pool_index, CascadeLocalizeIndex)  # the cascade recall pool


def test_localize_default_no_fail_close_without_embedder(monkeypatch):
    """The cascade_judge default must never fail-close a default `gloop run` when no embedder is configured
    (KLOOP_EMBED_BASE_URL unset): unlike `--localize rerank` (which fail-fasts without an embedder, see
    tests/run/test_localize_rerank_failfast.py), cascade_judge asks `_build_embedder()` but DEGRADES when it
    returns None (the bge-m3 semantic tier is omitted; the FTS/crash-token/literal-anchor tiers still run) —
    run_dataset must still be reached."""
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)
    monkeypatch.delenv("KLOOP_LABS", raising=False)
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned"])
    assert rc == 0
    assert "index" in seen        # run_dataset was reached -> no fail-close guard fired for localize
    from groundloop.adapters.index.labs.split import SplitIndex
    assert isinstance(seen["index"], SplitIndex)   # cascade_judge default still wraps as expected


def test_localize_tokens_explicit_wraps_signalquery(monkeypatch):
    """`--localize tokens` (now an opt-in, no longer the default) still wraps the index in SignalQueryIndex
    so the localize FTS5 query uses the extracted code tokens."""
    from groundloop.adapters.index.labs.signal_query import SignalQueryIndex
    idx = _captured_index(monkeypatch, ["--localize", "tokens"])
    assert isinstance(idx, SignalQueryIndex)


def test_localize_tokens_judge_wraps_signalquery_pool_under_judge(monkeypatch):
    """L1: `--localize tokens_judge` builds SplitIndex -> RerankLocalizeIndex whose pool_index is a
    SignalQueryIndex (the crash-token pool) — the token pool reordered by the LLM judge. With no creds the
    judge is None, so it degrades to the token-pool order (= plain --localize tokens). [authored] file@1:
    0.62 tokens -> 0.71 tokens+judge (the token pool holds the oracle file ~0.90, so the judge can promote it)."""
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)
    from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.labs.signal_query import SignalQueryIndex
    from groundloop.adapters.index.labs.split import SplitIndex
    idx = _captured_index(monkeypatch, ["--localize", "tokens_judge"])
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, RerankLocalizeIndex)
    assert idx._localize.judge is None                             # no creds -> token-pool order
    assert isinstance(idx._localize._pool_index, SignalQueryIndex)  # the crash-token pool feeds the judge


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
