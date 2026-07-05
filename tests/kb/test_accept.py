"""A4 — strengthened_accept: the SP3 two-sided accept() plus a Φ_c-sweep monotonicity gate and a
Wilson-95 lower-bound guard on the newly-solved evidence. Two synthetic fix-scorecard arm dicts per
case; no oracle, no network."""
from groundloop.kb.accept import strengthened_accept


def _arm(*, resolved_by_case, fabrication, phi, file_recall1=0.5, cost_per_solved=1.0):
    """A minimal fix-scorecard arm: exactly the keys compare/compare_metrics/accept read."""
    return {
        "file_recall@1": {"value": file_recall1},
        "fabrication_rate": {"value": fabrication},
        "cost_per_solved": cost_per_solved,
        "cost_total": cost_per_solved,
        "phi_c": {"0.5": phi, "1.0": phi, "2.0": phi},
        "resolved_by_case": resolved_by_case,
    }


def test_honesty_regression_rejected():
    # head solves both cases (strong positive lift) but raises fabrication -> honesty fails -> reject
    base = _arm(resolved_by_case={"c1": False, "c2": False}, fabrication=0.0, phi=0.10,
                file_recall1=0.50)
    head = _arm(resolved_by_case={"c1": True, "c2": True}, fabrication=0.20, phi=0.10,
                file_recall1=0.60)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["honesty_ok"] is False
    assert v["accepted"] is False
    assert any("fabrication" in r for r in v["reasons"])
    assert set(v) == {"accepted", "pos_ok", "honesty_ok", "phi_ok", "wilson_lo", "cost_ok", "reasons"}


def test_clean_lift_accepted():
    # head solves 3 (Wilson-95 lo>0), holds honesty, and never regresses phi at any c -> accept
    base = _arm(resolved_by_case={"c1": False, "c2": False, "c3": False}, fabrication=0.10,
                phi=0.10, file_recall1=0.40)
    head = _arm(resolved_by_case={"c1": True, "c2": True, "c3": True}, fabrication=0.05,
                phi=0.25, file_recall1=0.70)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["honesty_ok"] is True
    assert v["phi_ok"] is True
    assert v["wilson_lo"] > 0
    assert v["cost_ok"] is True
    assert v["accepted"] is True
    assert v["reasons"] == []


def test_phi_regression_blocks_accept():
    # solves 3, honesty held, but Φ_c drops at every c -> phi_ok False -> reject (the NEW gate)
    base = _arm(resolved_by_case={"c1": False, "c2": False, "c3": False}, fabrication=0.10,
                phi=0.30, file_recall1=0.40)
    head = _arm(resolved_by_case={"c1": True, "c2": True, "c3": True}, fabrication=0.05,
                phi=0.10, file_recall1=0.70)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["honesty_ok"] is True
    assert v["phi_ok"] is False
    assert v["accepted"] is False
    assert any("phi_c" in r for r in v["reasons"])


def test_thin_evidence_blocks_accept():
    # file_recall@1 lifts (pos_ok) but NO case is newly solved (None never counts) -> Wilson lo==0
    base = _arm(resolved_by_case={"c1": False, "c2": None}, fabrication=0.10, phi=0.10,
                file_recall1=0.40)
    head = _arm(resolved_by_case={"c1": False, "c2": None}, fabrication=0.10, phi=0.10,
                file_recall1=0.70)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["wilson_lo"] == 0.0
    assert v["accepted"] is False
    assert any("Wilson" in r for r in v["reasons"])
