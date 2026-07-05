from groundloop.fixeval.compare import compare_metrics, accept


def _arm(fr1, fab, cost, phi):
    return {"file_recall@1": {"value": fr1}, "file_recall@3": {"value": fr1},
            "file_recall@5": {"value": fr1}, "resolved_rate": {"value": None},
            "patch_apply_rate": 1.0, "fabrication_rate": {"value": fab},
            "cost_per_solved": cost, "cost_total": 0.0, "phi_c": {"1.0": phi}}


def test_compare_metrics_computes_deltas_none_safe():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.8, 0.0, 0.12, 0.7))
    assert abs(m["file_recall@1"]["delta"] - 0.3) < 1e-9
    assert m["resolved_rate"]["delta"] is None          # None on either side -> None (no crash)
    assert abs(m["phi_c@1.0"]["delta"] - 0.2) < 1e-9


def test_accept_positive_lift_no_honesty_regression():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.8, 0.0, 0.12, 0.7))
    v = accept(m, {"newly_solved": ["c1"], "newly_broken": []})
    assert v["accepted"] and v["pos_ok"] and v["honesty_ok"]


def test_accept_rejects_fabrication_rise():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.9, 0.25, 0.10, 0.6))   # fabrication up
    v = accept(m, {"newly_solved": ["c1"], "newly_broken": []})
    assert not v["accepted"] and not v["honesty_ok"]
    assert any("fabrication" in r for r in v["reasons"])


def test_accept_rejects_no_lift():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.5, 0.0, 0.10, 0.5))
    v = accept(m, {"newly_solved": [], "newly_broken": []})
    assert not v["accepted"] and not v["pos_ok"]


def test_accept_cost_budget_optional_gate():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.8, 0.0, 0.30, 0.7))    # cost tripled
    assert accept(m, {"newly_solved": ["c1"], "newly_broken": []})["accepted"]   # advisory by default
    assert not accept(m, {"newly_solved": ["c1"], "newly_broken": []}, cost_budget=0.05)["accepted"]
