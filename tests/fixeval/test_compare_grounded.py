# tests/fixeval/test_compare_grounded.py
from groundloop.fixeval.compare import compare_metrics, accept_grounded


def _arm(**kw):
    base = {"file_recall@1": {"value": 1.0}, "file_recall@3": {"value": 1.0},
            "file_recall@5": {"value": 1.0}, "resolved_rate": {"value": 0.3},
            "resolved_rate_strict": {"value": 0.2}, "patch_apply_rate": 0.9,
            "fabrication_rate": {"value": 0.1}, "plan_target_recall@1": {"value": 0.4},
            "plan_target_recall@5": {"value": 0.6}, "plan_api_match": {"value": 0.5},
            "plan_groundedness": {"value": 0.9}, "phi_c": {"1.0": 0.5},
            "cost_per_solved": 0.01, "cost_total": 1.0}
    base.update(kw)
    return base


def test_grounded_metrics_surfaced():
    cmp = compare_metrics(_arm(), _arm(**{"resolved_rate_strict": {"value": 0.5}}))
    assert cmp["resolved_rate_strict"]["delta"] == 0.3
    assert "plan_target_recall@1" in cmp


def test_grounded_accept_on_plan_recall_lift():
    v = accept_grounded(compare_metrics(_arm(), _arm(**{"plan_target_recall@1": {"value": 0.6}})),
                        {"newly_solved": [], "newly_broken": []})
    assert v["accepted"] is True and v["pos_ok"] is True


def test_grounded_reject_when_groundedness_drops():
    v = accept_grounded(compare_metrics(
        _arm(), _arm(**{"plan_target_recall@1": {"value": 0.6}, "plan_groundedness": {"value": 0.7}})), {})
    assert v["accepted"] is False and v["honesty_ok"] is False   # lifted recall but hallucinated more


def test_grounded_reject_when_fabrication_rises():
    v = accept_grounded(compare_metrics(
        _arm(), _arm(**{"resolved_rate_strict": {"value": 0.4}, "fabrication_rate": {"value": 0.3}})), {})
    assert v["accepted"] is False and v["honesty_ok"] is False
