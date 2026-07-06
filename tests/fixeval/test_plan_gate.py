# tests/fixeval/test_plan_gate.py
from groundloop.fixeval.plan import RepairPlan, PlanTarget, check_plan_in_world, plan_groundedness


def _wt(tmp_path, files):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return str(tmp_path)


def test_gate_passes_when_grounded(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F { void onBind(){ isAdded(); } }"})
    plan = RepairPlan(root_cause="rc", strategy="s",
                      targets=(PlanTarget(file="src/F.java", symbol="onBind"),),
                      required_apis=("isAdded",))
    chk = check_plan_in_world(plan, wt, candidates=["src/F.java"])
    assert chk.ok is True
    assert plan_groundedness(chk) == 1.0


def test_gate_flags_missing_file_and_scope(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    plan = RepairPlan(root_cause="rc", strategy="s",
                      targets=(PlanTarget(file="src/Missing.java"),   # in-scope candidate, not on disk
                               PlanTarget(file="src/Ghost.java")),     # out of the candidate set
                      required_apis=())
    chk = check_plan_in_world(plan, wt, candidates=["src/F.java", "src/Missing.java"])
    assert chk.ok is False
    assert any("target_file_missing:src/Missing.java" in f for f in chk.failures)
    assert any("target_out_of_scope:src/Ghost.java" in f for f in chk.failures)
    assert plan_groundedness(chk) == 0.0


def test_gate_rejects_traversal_and_absolute(tmp_path):
    # a secret sits OUTSIDE the work-tree; a traversal/absolute target must never be read (anti-leak)
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("class F { void onBind(){} }")     # would resolve `onBind` IF it were ever read
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    for bad in ("../secret.txt", str(secret)):
        plan = RepairPlan(root_cause="rc", strategy="s",
                          targets=(PlanTarget(file=bad, symbol="onBind"),), required_apis=())
        chk = check_plan_in_world(plan, wt, candidates=["src/F.java"])
        assert chk.ok is False
        assert any("target_out_of_scope" in f for f in chk.failures)
        assert plan_groundedness(chk) == 0.0             # nothing outside candidates was read/credited


def test_gate_flags_unresolved_symbol_and_api(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    plan = RepairPlan(root_cause="rc", strategy="s",
                      targets=(PlanTarget(file="src/F.java", symbol="nope"),),
                      required_apis=("alsoNope",))
    chk = check_plan_in_world(plan, wt, candidates=["src/F.java"])
    assert any("symbol_unresolved" in f for f in chk.failures)
    assert any("api_unresolved" in f for f in chk.failures)


def test_gate_rejects_abstain_and_empty(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    assert check_plan_in_world(RepairPlan("", (), abstain=True), wt, ["src/F.java"]).ok is False
    assert check_plan_in_world(RepairPlan("", ()), wt, ["src/F.java"]).ok is False
