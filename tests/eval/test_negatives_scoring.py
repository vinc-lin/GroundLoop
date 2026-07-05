from groundloop.eval.dataset import EvalOracle
from groundloop.eval.runner import MatchRecord
from groundloop.eval.scorecard import grade_all


def _rec(cid, arm, ranked, predicted):
    return MatchRecord(cid, arm, ranked, [float(len(ranked) - i) for i in range(len(ranked))],
                       predicted, 3.0, 5.0)


def test_bucket1_abstain_scores_plus_one():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_all([_rec("c", "a", ["x", "y"], None)], oracle_by_case={"c": oo}, c_values=(1.0,))
    sel = card["arms"]["a"]["selective"]
    assert sel["phi_c"]["1.0"] == 1.0                          # abstain on unanswerable = +1
    assert sel["abstention_recall_oof"]["value"] == 1.0
    assert card["arms"]["a"]["per_class"]["out_of_fleet"]["abstain_rate"] == 1.0


def test_bucket1_answer_is_penalized():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_all([_rec("c", "a", ["x", "y"], "x")], oracle_by_case={"c": oo}, c_values=(1.0,))
    sel = card["arms"]["a"]["selective"]
    assert sel["phi_c"]["1.0"] == -1.0                         # answered unanswerable = -c
    assert sel["abstention_recall_oof"]["value"] == 0.0


def test_bucket2_insufficient_signal_abstain_scores_zero():
    lo = EvalOracle("cameraview", is_answerable=True, negative_class="insufficient_signal")
    card = grade_all([_rec("c", "a", ["x", "cameraview"], None)], oracle_by_case={"c": lo}, c_values=(1.0,))
    sel = card["arms"]["a"]["selective"]
    assert sel["phi_c"]["1.0"] == 0.0                          # abstain on answerable = 0
    assert sel["abstention_recall_oof"]["n_unanswerable"] == 0  # answerable -> not in OOF denominator


def test_forced_recall_excludes_unanswerable():
    recs = [_rec("p", "a", ["cameraview", "x"], "cameraview"),          # positive hit
            _rec("o", "a", ["x", "y"], None)]                            # OOF abstain
    oracles = {"p": EvalOracle("cameraview"),
               "o": EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")}
    card = grade_all(recs, oracle_by_case=oracles, ks=(1,), c_values=(1.0,))
    f = card["arms"]["a"]["forced"]
    assert f["n_answerable"] == 1 and f["recall@1"]["value"] == 1.0     # OOF not in the denominator
