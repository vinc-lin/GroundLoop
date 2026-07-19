"""Task 9: reporting-only promotion-eligibility notes over a grade-run card. The note SAYS when a
[production] number clears a capability's bar (e.g. PlanningFixEngine's Provisional-Core obligation) so a
human can enact the promotion — it NEVER edits capabilities.md or flips a default."""
from groundloop.grade.promotion import promotion_notes


def _card(value, n, fixer):
    return {"overall": {"fix": {"resolved_rate_strict": {"value": value, "n": n}}},
            "cases": [{"case_id": "A", "fixer": fixer}, {"case_id": "B", "fixer": fixer}]}


def test_plan_fixer_with_gradeable_resolution_yields_note():
    notes = promotion_notes(_card(0.4, 10, "plan"))
    assert notes, "expected a promotion-eligibility note"
    blob = " ".join(notes)
    assert "PlanningFixEngine" in blob
    assert "Provisional-Core" in blob
    assert "0.40" in blob
    assert "10" in blob
    assert ("confirm Core" in blob) or ("revert" in blob)


def test_nothing_gradeable_yields_no_note():
    assert promotion_notes(_card(None, 0, "plan")) == []


def test_non_plan_fixer_yields_no_note():
    assert promotion_notes(_card(0.4, 10, "model")) == []
