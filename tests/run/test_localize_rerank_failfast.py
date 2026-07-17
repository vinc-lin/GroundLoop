"""`gloop run --localize rerank` must FAIL-FAST when no embedder is available.

The reranker's vector candidate-gen lane only fires when an embedder is injected; with
`KLOOP_EMBED_BASE_URL` unset the reranker would silently degrade to keyword-only, so a rerank
scorecard would LOOK valid while the vector lane is dead (a real misleading production read).
Mirror the `--match-arm semantic` no-embedder guard: exit 2 with a message mentioning the
embedder, and DO NOT build a keyword-only reranker. Composition-root test via main() — no live
gateway (the autouse KLOOP_DEV fixture is active suite-wide)."""
from __future__ import annotations


def test_localize_rerank_fail_closed_without_embedder(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    # A reranker must NOT be built on the no-embedder path — trip the test if _build_rerank_localize runs.
    import groundloop.cli as cli
    monkeypatch.setattr(cli, "_build_rerank_localize",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("built keyword-only reranker")))
    rc = cli.main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
                   "--index-db", "a.db", "--out", "o", "--repos", "r", "--localize", "rerank"])
    out = capsys.readouterr().out.lower()
    assert rc == 2
    assert "embedder" in out and "kloop_embed_base_url" in out


def test_localize_rerank_builds_when_embedder_present(monkeypatch):
    """With an embedder present the rerank branch passes the guard and wraps the match index in a
    SplitIndex over the RerankLocalizeIndex (rank stays with the match arm)."""
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: object())
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned",
              "--match-arm", "flood", "--localize", "rerank"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, RerankLocalizeIndex)
