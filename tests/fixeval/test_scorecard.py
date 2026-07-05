from groundloop.eval.dataset import EvalOracle
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all

REL = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


def _rec(**kw):
    base = dict(case_id="c", arm="a", predicted_repo="r", locations=[REL],
                patch_diff="+ nativeCreateHandler", patch_files=[REL], patch_emitted=True,
                patch_applies=True, abstained=False, abstain_reason=None, refine_iters=0, cost_usd=0.0)
    base.update(kw)
    return FixRecord(**base)


def test_resolved_positive():
    oracle = EvalOracle("r", expected_files=(REL,), required_apis=("nativeCreateHandler",))
    card = grade_fix_all([_rec()], oracle_by_case={"c": oracle})
    a = card["arms"]["a"]
    assert a["file_recall@1"]["value"] == 1.0 and a["patch_apply_rate"] == 1.0
    assert a["required_api_pass_rate"]["value"] == 1.0
    assert a["resolved_rate"]["value"] == 1.0 and a["n_gradeable"] == 1 and a["n_excluded"] == 0


def test_case_without_required_apis_excluded_from_resolved():
    oracle = EvalOracle("r", expected_files=(REL,), required_apis=())   # not grounded-gradeable
    card = grade_fix_all([_rec()], oracle_by_case={"c": oracle})
    a = card["arms"]["a"]
    assert a["n_gradeable"] == 0 and a["n_excluded"] == 1
    assert a["resolved_rate"]["value"] is None      # advisory, undefined over an empty subset


def test_unappliable_patch_not_resolved():
    oracle = EvalOracle("r", expected_files=(REL,), required_apis=("nativeCreateHandler",))
    card = grade_fix_all([_rec(patch_applies=False)], oracle_by_case={"c": oracle})
    a = card["arms"]["a"]
    assert a["resolved_rate"]["value"] == 0.0 and a["cost_per_solved"] is None
