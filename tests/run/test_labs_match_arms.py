"""Selectable experimental match arms on `gloop run` (semantic | functional | dispatch). The arms are opt-in
Candidates; they fail-closed with a clear message when their gateway creds are absent. Composition-root
tests via main() — no live gateway (the autouse KLOOP_DEV fixture is active suite-wide)."""
from __future__ import annotations


def test_semantic_arm_fail_closed_without_embedder(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index-db", "a.db", "--out", "o", "--repos", "r", "--match-arm", "semantic"])
    assert rc == 2 and "embedder" in capsys.readouterr().out.lower()


def test_semantic_arm_builds_index_when_embedder_present(monkeypatch):
    """With an embedder present, the semantic branch constructs SemanticAtlasIndex (passes the guard).
    We stub the embedder + the index so no live gateway is hit; the run fails LATER (no real dataset),
    but the point is the guard was passed and the vector index was built."""
    import groundloop.adapters.index.atlas_semantic as sem_mod
    import groundloop.cli as cli
    built = {}

    class _StubSemantic:
        def __init__(self, db, emb):
            built["db"] = db

        def rank_repos(self, signals, catalog):
            return []

        def retrieve(self, repo, query):
            return []

    monkeypatch.setattr(cli, "_build_embedder", lambda: object())
    monkeypatch.setattr(sem_mod, "SemanticAtlasIndex", _StubSemantic)
    try:
        cli.main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
                  "--index-db", "a.db", "--out", "o", "--repos", "r", "--match-arm", "semantic"])
    except Exception:
        pass  # a later stage fails on the fake dataset; we only assert the semantic index was built
    assert built.get("db") == "a.db"   # the semantic branch passed the guard and constructed the index


def test_functional_arm_fail_closed_without_profile(monkeypatch, capsys):
    monkeypatch.setenv("KLOOP_EMBED_BASE_URL", "http://stub")   # embedder present...
    monkeypatch.delenv("KLOOP_FUNCTIONAL_PROFILE", raising=False)  # ...but no profile artifact
    import groundloop.cli as cli
    monkeypatch.setattr(cli, "_build_embedder", lambda: object())
    rc = cli.main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
                   "--index-db", "a.db", "--out", "o", "--repos", "r", "--match-arm", "functional"])
    assert rc == 2 and "profile" in capsys.readouterr().out.lower()


def test_functional_arm_fail_closed_without_embedder(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index-db", "a.db", "--out", "o", "--repos", "r", "--match-arm", "functional",
               "--functional-profile", "p.db"])
    assert rc == 2


def test_dispatch_arm_builds_when_deps_present(monkeypatch):
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: object())
    import groundloop.adapters.index.functional_text as ft
    built = {}

    class _FT:  # FunctionalTextIndex stub
        def __init__(self, profile_db, emb, atlas_db=None):
            built["ft"] = profile_db

    class _DI:  # DispatchIndex stub
        def __init__(self, fault, functional, fault_scale=1.0):
            built["di"] = fault_scale

        def rank_repos(self, s, c):
            return []

        def retrieve(self, r, q):
            return []

    monkeypatch.setattr(ft, "FunctionalTextIndex", _FT)
    monkeypatch.setattr(ft, "DispatchIndex", _DI)
    import groundloop.cli as cli
    try:
        cli.main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
                  "--index-db", "a.db", "--out", "o", "--repos", "r", "--match-arm", "dispatch",
                  "--functional-profile", "p.db"])
    except Exception:
        pass
    assert built.get("ft") == "p.db" and "di" in built   # dispatch built FunctionalTextIndex + DispatchIndex
