# tests/fixeval/test_report_plan.py
from groundloop.fixeval.report import render_fix_markdown


def test_markdown_includes_plan_metrics_when_present():
    card = {"n_cases": 1, "arms": {"plan": {
        "n": 1, "fix_coverage": 1.0, "abstain_rate": 0.0, "patch_apply_rate": 1.0,
        "file_recall@1": {"value": 1.0, "n": 1}, "file_recall@3": {"value": 1.0, "n": 1},
        "file_recall@5": {"value": 1.0, "n": 1}, "resolved_rate": {"value": 1.0, "n": 1},
        "resolved_rate_strict": {"value": 1.0, "n": 1}, "required_api_pass_rate": {"value": 1.0, "n": 1},
        "fabrication_rate": {"value": None, "n": 0}, "n_gradeable": 1, "n_excluded": 0,
        "phi_c": {"1.0": 1.0}, "cost_total": 0.0, "cost_per_solved": None,
        "plan_groundedness": {"value": 0.9, "n": 1}, "plan_target_recall@1": {"value": 1.0, "n": 1},
        "plan_target_recall@5": {"value": 1.0, "n": 1}, "plan_api_match": {"value": 1.0, "n": 1},
        "resolved_by_case": {}}}}
    md = render_fix_markdown(card)
    assert "plan_groundedness" in md and "resolved_rate_strict" in md
