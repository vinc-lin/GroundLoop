"""`gloop run --profile {core,labs}` (KLOOP_LABS=1) flips the run DEFAULTS to the experimental stack
(routing match + semantic localize; fix stays plan) — but ONLY where left at default; explicit
--match-arm/--localize always win. --match-arm/--localize parse to a None sentinel resolved by
_resolve_arms. The manifest records profile + the localize that actually ran (post-degrade)."""
from __future__ import annotations


def test_match_arm_localize_default_none_sentinel():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
                                    "--index-db", "a.db", "--out", "o", "--repos", "r"])
    assert ns.match_arm is None and ns.localize is None    # sentinels — resolved by profile


def test_resolve_arms_core_and_labs(monkeypatch):
    from groundloop.cli import build_parser, _resolve_arms

    def parse(extra):
        return build_parser().parse_args(
            ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch", "--index-db", "a.db",
             "--out", "o", "--repos", "r", *extra])
    monkeypatch.delenv("KLOOP_LABS", raising=False)
    assert _resolve_arms(parse([])) == ("component", "atlas", "core")
    assert _resolve_arms(parse(["--profile", "labs"])) == ("routing", "semantic", "labs")
    assert _resolve_arms(parse(["--profile", "labs", "--match-arm", "functional"])) == ("functional", "semantic", "labs")
    assert _resolve_arms(parse(["--profile", "labs", "--localize", "atlas"])) == ("routing", "atlas", "labs")
    monkeypatch.setenv("KLOOP_LABS", "1")
    assert _resolve_arms(parse([])) == ("routing", "semantic", "labs")


def test_manifest_has_profile_and_localize(tmp_path):
    from groundloop.run.manifest import write_manifest
    import json
    p = write_manifest(str(tmp_path), atlas_db=None, match_arm="routing", fixer="plan", affinity="",
                       produce_model="deepseek-chat", embed_model="bge-m3", n_cases=1,
                       profile="labs", localize="semantic")
    m = json.loads(open(p).read())
    assert m["profile"] == "labs" and m["localize"] == "semantic"


def test_labs_localize_degrades_without_embedder(monkeypatch, capsys):
    """labs-DEFAULTED semantic localize degrades to atlas (warn, not exit 2); explicit --localize semantic
    still fails closed."""
    monkeypatch.setenv("KLOOP_LABS", "1")
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    import groundloop.run.batch as batch
    seen = {}
    monkeypatch.setattr(batch, "run_dataset", lambda dataset, **kw: (seen.__setitem__("localize_mf", kw) or 0))
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch", "--index-db", "a.db",
              "--out", "o", "--repos", "r", "--fixer", "canned"])
    except Exception:
        pass
    out = capsys.readouterr().out.lower()
    assert "falling back to" in out and "atlas" in out    # degraded, not exit 2
