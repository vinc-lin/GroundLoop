"""`gloop run --profile {core,labs}` (KLOOP_LABS=1) flips the run DEFAULTS to the experimental stack
(routing match + atlas localize; fix stays plan) — but ONLY where left at default; explicit
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
    assert _resolve_arms(parse(["--profile", "labs"])) == ("routing", "atlas", "labs")
    assert _resolve_arms(parse(["--profile", "labs", "--match-arm", "functional"])) == ("functional", "atlas", "labs")
    assert _resolve_arms(parse(["--profile", "labs", "--localize", "atlas"])) == ("routing", "atlas", "labs")
    monkeypatch.setenv("KLOOP_LABS", "1")
    assert _resolve_arms(parse([])) == ("routing", "atlas", "labs")


def test_kloop_labs_falsey_values_do_not_enable_labs(monkeypatch):
    """KLOOP_LABS=0/false/no/off must NOT enable labs — an operator writing =0 to disable it must not
    silently flip production to the experimental defaults."""
    from groundloop.cli import _resolve_arms, build_parser
    args = build_parser().parse_args(["run", "--dataset", "d", "--catalog", "c", "--work", "w",
                                      "--changes", "ch", "--index-db", "a.db", "--out", "o", "--repos", "r"])
    for falsey in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("KLOOP_LABS", falsey)
        assert _resolve_arms(args) == ("component", "atlas", "core")   # stays Core-aligned
    monkeypatch.setenv("KLOOP_LABS", "1")
    assert _resolve_arms(args)[2] == "labs"                            # affirmative still works


def test_manifest_has_profile_and_localize(tmp_path):
    from groundloop.run.manifest import write_manifest
    import json
    p = write_manifest(str(tmp_path), atlas_db=None, match_arm="routing", fixer="plan", affinity="",
                       produce_model="deepseek-chat", embed_model="bge-m3", n_cases=1,
                       profile="labs", localize="atlas")
    m = json.loads(open(p).read())
    assert m["profile"] == "labs" and m["localize"] == "atlas"
