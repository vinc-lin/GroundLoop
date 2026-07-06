# tests/fixeval/test_scorecard_plan_metrics.py
from dataclasses import dataclass
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all


@dataclass
class O:  # noqa: E742
    expected_files: list
    required_apis: list
    is_answerable: bool = True


def _rec(plan, groundedness):
    return FixRecord(case_id="c1", arm="plan", predicted_repo="r", locations=["src/Right.java"],
                     patch_diff="--- a/src/Right.java\n+++ b/src/Right.java\n@@ -1 +1 @@\n-a\n+b\n",
                     patch_files=["src/Right.java"], patch_emitted=True, patch_applies=True,
                     abstained=False, abstain_reason=None, refine_iters=0, cost_usd=0.0,
                     plan=plan, groundedness=groundedness, replans=0)


def test_plan_metrics_reported():
    plan = {"root_cause": "rc", "targets": [{"file": "src/Right.java", "symbol": None, "why": ""}],
            "required_apis": ["isAdded"], "strategy": "s", "citations": [], "risks": "",
            "confidence": 0.5, "abstain": False}
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["isAdded"])}
    card = grade_fix_all([_rec(plan, 1.0)], oracle_by_case=oracle)["arms"]["plan"]
    assert card["plan_groundedness"]["value"] == 1.0
    assert card["plan_target_recall@1"]["value"] == 1.0
    assert card["plan_api_match"]["value"] == 1.0


def test_plan_correctness_penalizes_wrong_target():
    plan = {"root_cause": "rc", "targets": [{"file": "src/Wrong.java", "symbol": None, "why": ""}],
            "required_apis": [], "strategy": "s", "citations": [], "risks": "",
            "confidence": 0.5, "abstain": False}
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=[])}
    card = grade_fix_all([_rec(plan, 1.0)], oracle_by_case=oracle)["arms"]["plan"]
    assert card["plan_target_recall@1"]["value"] == 0.0


def test_malformed_plan_shape_does_not_crash():
    # a raw-dict plan (runner._do_propose passthrough) missing "file" in a target / missing required_apis
    plan = {"root_cause": "rc", "targets": [{"symbol": "x"}, "notadict"], "strategy": "s"}
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["isAdded"])}
    card = grade_fix_all([_rec(plan, 1.0)], oracle_by_case=oracle)["arms"]["plan"]
    assert card["plan_target_recall@1"]["value"] == 0.0   # no valid target file -> no recall
    assert card["plan_api_match"]["value"] == 0.0         # required_apis absent -> no match
