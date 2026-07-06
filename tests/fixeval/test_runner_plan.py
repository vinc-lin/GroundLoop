# tests/fixeval/test_runner_plan.py
from groundloop.core.types import Patch
from groundloop.fixeval.runner import FixRecord, _do_propose


class PlainFixer:
    model = type("M", (), {"cost_usd": 0.0})()
    def propose(self, wt, ticket, locations):
        return Patch(diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", files=("x",))


class PlanFixer(PlainFixer):
    def propose_with_plan(self, wt, ticket, locations):
        plan = {"root_cause": "rc", "targets": [{"file": "x", "symbol": None, "why": ""}],
                "required_apis": [], "strategy": "s", "citations": [], "risks": "",
                "confidence": 0.5, "abstain": False}
        return plan, Patch(diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", files=("x",)), \
            {"replans": 1, "groundedness": 1.0}


def test_do_propose_plain_fixer_has_no_plan():
    plan, patch, meta = _do_propose(PlainFixer(), None, None, ["x"])
    assert plan is None and meta == {} and patch.diff


def test_do_propose_plan_fixer_returns_dict_plan():
    plan, patch, meta = _do_propose(PlanFixer(), None, None, ["x"])
    assert plan["root_cause"] == "rc" and meta["groundedness"] == 1.0


def test_fixrecord_accepts_plan_fields():
    r = FixRecord(case_id="c", arm="a", predicted_repo="r", locations=["x"], patch_diff="d",
                  patch_files=["x"], patch_emitted=True, patch_applies=True, abstained=False,
                  abstain_reason=None, refine_iters=0, cost_usd=0.0,
                  plan={"root_cause": "rc"}, groundedness=1.0, replans=1)
    assert r.plan["root_cause"] == "rc" and r.groundedness == 1.0 and r.replans == 1
