"""Honest end-to-end funnel report: match -> localize -> fix, on the SAME N cases, reusing
grade_fix_all's own numbers (never recomputed) for localize/fix. grade_fix_all is oracle-blind to
match correctness (it never reads oracle.owning_repo — see fixeval/scorecard.py), so the funnel's
match row is a per-case coverage tally over `per_case` (raw FixRecord-shaped rows), not a scorecard
key. `_SCORE` below is the REAL shape of one arm's dict from grade_fix_all(...)["arms"][arm]."""
from groundloop.fixeval.report import render_e2e_funnel

_SCORE = {
    "n": 3,
    "fix_coverage": 0.667,
    "abstain_rate": 0.333,
    "file_recall@1": {"value": 0.333, "wilson95": [0.06, 0.79], "n": 3},
    "file_recall@3": {"value": 0.667, "wilson95": [0.21, 0.94], "n": 3},
    "file_recall@5": {"value": 0.667, "wilson95": [0.21, 0.94], "n": 3},
    "patch_apply_rate": 0.5,
    "required_api_pass_rate": {"value": 0.333, "wilson95": [0.06, 0.79], "n": 3},
    "resolved_rate": {"value": 0.333, "wilson95": [0.06, 0.79], "n": 3},
    "resolved_rate_strict": {"value": 0.333, "wilson95": [0.06, 0.79], "n": 3},
    "n_gradeable": 3,
    "n_excluded": 0,
    "fabrication_rate": {"value": 0.0, "wilson95": [0.0, 0.71], "n": 1},
    "resolved_by_case": {"oboe-1417": True, "oboe-1420": False, "oboe-1433": None},
}
_ROWS = [
    {"case_id": "oboe-1417", "match": True, "localize_at_5": True, "resolved": True},
    {"case_id": "oboe-1420", "match": True, "localize_at_5": False, "resolved": False},
    {"case_id": "oboe-1433", "match": False, "localize_at_5": False, "resolved": None},
]


def test_funnel_reports_each_stage_and_mock_bind():
    md = render_e2e_funnel(_SCORE, _ROWS)
    low = md.lower()
    assert "match" in low and "0.67" in md            # match stage value present (2/3 matched)
    assert "localize" in low and "file@5" in low      # localize stage
    assert "resolved" in low                          # fix stage
    assert "mock" in low                              # submit/bind reported as mock
    assert "bound" not in low                         # NEVER scored as bound
    assert "oboe-1417" in md                          # per-case row


def test_funnel_empty_is_safe():
    md = render_e2e_funnel({"n": 0}, [])
    assert isinstance(md, str) and "0" in md
