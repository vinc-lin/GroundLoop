from groundloop.eval.scorecard import score_match, grade_all
from groundloop.eval.runner import MatchRecord
from groundloop.core.types import Oracle


def _rec(arm, ranked, predicted, margin=3.0):
    return MatchRecord(case_id="c", arm=arm, ranked_names=ranked,
                       scores=[float(len(ranked) - i) for i in range(len(ranked))],
                       predicted=predicted, margin=margin, top1_score=5.0)


def test_score_match_forced_and_selective_fields():
    rec = _rec("membership+logs", ["gpuimage", "organicmaps", "cameraview"], "gpuimage")
    oracle = Oracle(owning_repo="gpuimage")
    m = score_match(rec, oracle)
    assert m["recall@1"] is True
    assert m["repo_rank"] == 1
    assert m["answered"] is True and m["correct"] is True and m["answerable"] is True


def test_score_match_abstain_and_wrong():
    abstain = score_match(_rec("a", ["organicmaps", "gpuimage"], None), Oracle(owning_repo="gpuimage"))
    assert abstain["answered"] is False and abstain["correct"] is False
    assert abstain["recall@1"] is False and abstain["repo_rank"] == 2   # forced view ignores abstain
    wrong = score_match(_rec("a", ["organicmaps", "gpuimage"], "organicmaps"),
                        Oracle(owning_repo="gpuimage"))
    assert wrong["answered"] is True and wrong["correct"] is False


def test_grade_all_aggregates_per_arm(tmp_path):
    # two cases through one arm: one correct-answered, one abstain
    recs = [
        MatchRecord("c1", "membership+logs", ["gpuimage", "cameraview"], [5.0, 1.0], "gpuimage", 4.0, 5.0),
        MatchRecord("c2", "membership+logs", ["cameraview", "gpuimage"], [2.0, 2.0], None, 0.0, 2.0),
    ]
    oracles = {"c1": Oracle(owning_repo="gpuimage"), "c2": Oracle(owning_repo="gpuimage")}
    card = grade_all(recs, oracle_by_case=oracles, ks=(1, 3))
    arm = card["arms"]["membership+logs"]
    assert arm["n"] == 2
    assert arm["forced"]["recall@1"]["value"] == 0.5      # c1 hits @1, c2 owner at rank2
    assert arm["selective"]["coverage"] == 0.5            # 1 answered of 2
    assert arm["selective"]["selective_accuracy"]["value"] == 1.0   # the 1 answered was correct
    assert arm["selective"]["phi_c"]["1.0"] == 0.5        # +1 (c1) + 0 (abstain c2) / 2
    assert "wilson95" in arm["forced"]["recall@1"]
