"""`gloop run --localize {atlas,semantic}` chooses the localize retriever independently of --match-arm.
When localize differs from the match arm's native retrieve, the built index is wrapped in a SplitIndex
(rank from the match index, retrieve from the localize index). Composition-root tests via main() — no
live gateway (the autouse KLOOP_DEV fixture is active suite-wide)."""
from __future__ import annotations


def test_localize_semantic_fail_closed_without_embedder(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index-db", "a.db", "--out", "o", "--repos", "r", "--localize", "semantic"])
    assert rc == 2 and "embedder" in capsys.readouterr().out.lower()


def test_localize_semantic_wraps_in_split_index(monkeypatch):
    """--localize semantic with a non-semantic match wraps the built index in a SplitIndex whose retrieve
    is a SemanticAtlasIndex. We stub the embedder + SemanticAtlasIndex + capture the estate wiring; assert
    the composed index is a SplitIndex."""
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: object())
    import groundloop.adapters.index.atlas_semantic as sem
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
              "--localize", "semantic", "--match-arm", "flood"])
    except Exception:
        pass
    from groundloop.adapters.index.split import SplitIndex
    assert isinstance(seen.get("index"), SplitIndex)   # localize was split onto SemanticAtlasIndex


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
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.adapters.index.signal_query import SignalQueryIndex
    idx = _captured_index(monkeypatch, ["--localize", "atlas"])
    assert not isinstance(idx, (SplitIndex, SignalQueryIndex))


def test_localize_tokens_is_core_default_wraps_signalquery(monkeypatch):
    """Core default (no --localize) is now `tokens` (Provisional-Core): the index is wrapped in
    SignalQueryIndex so the localize FTS5 query uses the extracted code tokens."""
    from groundloop.adapters.index.signal_query import SignalQueryIndex
    idx = _captured_index(monkeypatch, [])   # no --localize -> core default = tokens
    assert isinstance(idx, SignalQueryIndex)
