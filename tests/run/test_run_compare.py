from pytest import approx

from groundloop.run.compare import compare_cards


def _card(*, recall1, file5, resolved, n_gradeable, cases):
    """A minimal-but-valid grade-run card: only the fields compare_cards reads."""
    return {
        "n_cases": len(cases),
        "overall": {
            "match": {"n": len(cases), "recall@1": recall1, "recall@3": recall1,
                      "recall@5": recall1, "recall_rank_avg": 1.0},
            "localize": {"as_run": {"file@1": file5, "file@3": file5, "file@5": file5},
                         "isolated": None},
            "fix": {"n_gradeable": n_gradeable, "n_ungradeable_no_source": 0,
                    "file_recall@1": None,
                    "resolved_rate_strict": {"value": resolved, "n": n_gradeable},
                    "fabrication_rate": {"value": None, "n": 0}, "patch_apply_rate": None},
            "counts": {"n": len(cases), "match_hits@1": 0},
        },
        "by_bug_kind": {},
        "cases": cases,
    }


def _case(cid, as_run1, fix, cost=0.0):
    return {"case_id": cid, "rank": 1, "as_run@1": as_run1, "isolated@1": None,
            "fix": fix, "predicted_repo": "alpha", "oracle_repo": "alpha",
            "signals": None, "cost_usd": cost, "fixer": "plan"}


def test_regressed_verdict_and_regressions_list():
    prev = _card(recall1=1.0, file5=0.8, resolved=0.5, n_gradeable=2,
                 cases=[_case("A", 1.0, "applies", 0.10),
                        _case("B", 1.0, "unappliable", 0.05)])
    cur = _card(recall1=0.5, file5=0.8, resolved=0.5, n_gradeable=2,
                cases=[_case("A", 0.0, "unappliable", 0.10),   # as_run@1 1 -> 0 (regression)
                       _case("B", 1.0, "unappliable", 0.05)])
    comp = compare_cards(cur, prev)

    # per-stage delta blocks
    assert comp["match"]["recall@1"] == {"cur": 0.5, "prev": 1.0, "delta": -0.5}
    assert comp["localize"]["file@5"]["delta"] == 0.0
    assert comp["fix"]["resolved_rate"]["delta"] == 0.0
    assert comp["cost"]["cur"] == approx(0.15) and comp["cost"]["prev"] == approx(0.15)

    # case A regressed (as_run@1 1 -> 0); B did not (as_run@1 stayed 1)
    assert comp["regressions"] == ["A"]
    assert comp["verdict"] == "regressed"


def test_flat_verdict_empty_regressions():
    a = _card(recall1=0.5, file5=0.4, resolved=0.3, n_gradeable=1,
              cases=[_case("A", 1.0, "applies")])
    b = _card(recall1=0.5, file5=0.4, resolved=0.3, n_gradeable=1,
              cases=[_case("A", 1.0, "applies")])
    comp = compare_cards(a, b)
    assert comp["verdict"] == "flat"
    assert comp["regressions"] == []
    assert comp["match"]["recall@1"]["delta"] == 0.0


def test_improved_verdict():
    prev = _card(recall1=0.5, file5=0.4, resolved=0.3, n_gradeable=1,
                 cases=[_case("A", 0.0, "unappliable")])
    cur = _card(recall1=1.0, file5=0.4, resolved=0.3, n_gradeable=1,
                cases=[_case("A", 1.0, "applies")])
    comp = compare_cards(cur, prev)
    assert comp["verdict"] == "improved"
    assert comp["regressions"] == []


def test_none_metric_yields_none_delta_no_regression():
    # resolved None on the cur side -> delta None, must NOT count as regression/improvement.
    prev = _card(recall1=0.5, file5=0.4, resolved=0.5, n_gradeable=1,
                 cases=[_case("A", 1.0, "applies")])
    cur = _card(recall1=0.5, file5=0.4, resolved=None, n_gradeable=0,
                cases=[_case("A", 1.0, "applies")])
    comp = compare_cards(cur, prev)
    assert comp["fix"]["resolved_rate"]["delta"] is None
    assert comp["verdict"] == "flat"          # nothing tracked moved
    assert comp["regressions"] == []


def test_fix_regression_applies_to_nonapplies():
    prev = _card(recall1=0.5, file5=0.4, resolved=0.5, n_gradeable=1,
                 cases=[_case("A", 1.0, "applies")])
    cur = _card(recall1=0.5, file5=0.4, resolved=0.5, n_gradeable=1,
                cases=[_case("A", 1.0, "unappliable")])   # fix applies -> unappliable
    comp = compare_cards(cur, prev)
    assert comp["regressions"] == ["A"]


def test_cost_increase_alone_does_not_regress():
    prev = _card(recall1=0.5, file5=0.4, resolved=0.5, n_gradeable=1,
                 cases=[_case("A", 1.0, "applies", cost=0.01)])
    cur = _card(recall1=0.5, file5=0.4, resolved=0.5, n_gradeable=1,
                cases=[_case("A", 1.0, "applies", cost=5.00)])  # cost way up, quality flat
    comp = compare_cards(cur, prev)
    assert comp["cost"]["delta"] > 0
    assert comp["verdict"] == "flat"
    assert comp["regressions"] == []
