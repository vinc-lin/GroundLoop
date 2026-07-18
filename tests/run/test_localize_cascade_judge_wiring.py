"""`gloop run --localize cascade_judge` wires a RerankLocalizeIndex (LLM judge + code-understanding
context) whose recall POOL is drawn from a CascadeLocalizeIndex (recall-first RRF union), all wrapped in
a SplitIndex so localize runs independently of the match arm. Like `--localize cascade` (and unlike
`--localize rerank`), the missing-embedder path must STILL build: the cascade degrades gracefully (bge-m3
semantic tier omitted) and the judge is creds-gated (judge=None), not embedder-gated. Composition-root
test via main() — no live gateway (the autouse KLOOP_DEV fixture is active suite-wide)."""
from __future__ import annotations


def test_cascade_judge_wraps_rerank_over_cascade_pool(monkeypatch):
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: None)   # cascade degrades; NO fail-fast
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)            # judge=None is fine for wiring
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned",
              "--match-arm", "flood", "--localize", "cascade_judge"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, RerankLocalizeIndex)
    assert isinstance(idx._localize._pool_index, CascadeLocalizeIndex)
