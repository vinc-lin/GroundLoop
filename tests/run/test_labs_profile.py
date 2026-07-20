"""`gloop run --profile {core,labs}` (KLOOP_LABS=1) flips the run DEFAULTS to the experimental peak stack
(routing match + cascade_judge localize — the best per-stage Candidate arms, [proxy] not [production]; fix
stays plan) — but ONLY where left at default; explicit --match-arm/--localize always win. The core
(production) default stack stays component + atlas_rerank + plan. --match-arm/--localize parse to a None
sentinel resolved by _resolve_arms. The manifest records profile + the localize that actually ran
(post-degrade)."""
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
    assert _resolve_arms(parse([])) == ("component", "atlas_rerank", "core")
    assert _resolve_arms(parse(["--profile", "labs"])) == ("routing", "cascade_judge", "labs")
    # explicit --match-arm wins; localize still fills to the labs default (cascade_judge)
    assert _resolve_arms(parse(["--profile", "labs", "--match-arm", "functional"])) == ("functional", "cascade_judge", "labs")
    # explicit --localize wins over the labs cascade_judge default
    assert _resolve_arms(parse(["--profile", "labs", "--localize", "atlas"])) == ("routing", "atlas", "labs")
    monkeypatch.setenv("KLOOP_LABS", "1")
    assert _resolve_arms(parse([])) == ("routing", "cascade_judge", "labs")


def test_kloop_labs_falsey_values_do_not_enable_labs(monkeypatch):
    """KLOOP_LABS=0/false/no/off must NOT enable labs — an operator writing =0 to disable it must not
    silently flip production to the experimental defaults."""
    from groundloop.cli import _resolve_arms, build_parser
    args = build_parser().parse_args(["run", "--dataset", "d", "--catalog", "c", "--work", "w",
                                      "--changes", "ch", "--index-db", "a.db", "--out", "o", "--repos", "r"])
    for falsey in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("KLOOP_LABS", falsey)
        assert _resolve_arms(args) == ("component", "atlas_rerank", "core")   # stays Core-aligned
    monkeypatch.setenv("KLOOP_LABS", "1")
    assert _resolve_arms(args)[2] == "labs"                            # affirmative still works


def test_labs_profile_builds_routing_plus_cascade_judge_stack(monkeypatch):
    """End-to-end composition lock: a labs run (KLOOP_LABS=1) with NO --match-arm/--localize builds the peak
    stack — the match side is FaultRoutingIndex and the localize side is a RerankLocalizeIndex (LLM judge)
    over a CascadeLocalizeIndex recall pool, wrapped in a SplitIndex. Missing embedder + no gateway creds
    must STILL build (cascade omits its bge-m3 tier; judge=None), so labs never fail-closes on the peak
    stack. Composition-root test via main() — no live gateway (autouse KLOOP_DEV fixture active)."""
    monkeypatch.setenv("KLOOP_LABS", "1")
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: None)   # cascade degrades; NO fail-fast
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)            # judge=None is fine for wiring
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.labs.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.labs.fault_routing import FaultRoutingIndex
    from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.labs.split import SplitIndex
    from groundloop.cli import main
    try:                                     # no --match-arm/--localize: both fill from the labs profile
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._match, FaultRoutingIndex)                       # labs match default = routing
    assert isinstance(idx._localize, RerankLocalizeIndex)                  # labs localize default = cascade_judge
    assert isinstance(idx._localize._pool_index, CascadeLocalizeIndex)     # ...judge over the cascade recall pool


def test_manifest_has_profile_and_localize(tmp_path):
    from groundloop.run.manifest import write_manifest
    import json
    p = write_manifest(str(tmp_path), atlas_db=None, match_arm="routing", fixer="plan", affinity="",
                       produce_model="deepseek-chat", embed_model="bge-m3", n_cases=1,
                       profile="labs", localize="atlas")
    m = json.loads(open(p).read())
    assert m["profile"] == "labs" and m["localize"] == "atlas"
