from groundloop.eval.scorecard import score_match, grade_all, per_case_rows
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


def test_per_case_rows_join_prediction_and_grade():
    recs = [
        # clean hit: owner ranked top-1 and answered
        MatchRecord("oboe-1", "membership+logs", ["oboe", "newpipe", "cameraview"],
                    [4.0, 1.0, 0.0], "oboe", 3.0, 4.0),
        # size-tax miss@1 but in top-3: owner at rank 3, answered the wrong (bigger) repo
        MatchRecord("newpipe-1", "membership+logs", ["antennapod", "osmand", "newpipe"],
                    [3.0, 3.0, 2.0], "antennapod", 0.0, 3.0),
        # abstain: predicted None
        MatchRecord("cam-1", "membership+logs", ["osmand", "cameraview"],
                    [1.0, 1.0], None, 0.0, 1.0),
    ]
    oracles = {"oboe-1": Oracle(owning_repo="oboe"),
               "newpipe-1": Oracle(owning_repo="newpipe"),
               "cam-1": Oracle(owning_repo="cameraview")}
    rows = per_case_rows(recs, oracle_by_case=oracles)
    assert len(rows) == 3
    by_id = {r["case_id"]: r for r in rows}

    hit = by_id["oboe-1"]
    assert hit["owning_repo"] == "oboe" and hit["predicted"] == "oboe"
    assert hit["ranked_top1"] == "oboe" and hit["oracle_rank"] == 1
    assert hit["recall@1"] is True and hit["correct"] is True and hit["answered"] is True

    miss = by_id["newpipe-1"]
    assert miss["owning_repo"] == "newpipe" and miss["predicted"] == "antennapod"
    assert miss["ranked_top1"] == "antennapod" and miss["oracle_rank"] == 3
    assert miss["recall@1"] is False and miss["correct"] is False   # top-3 but not @1
    assert miss["ranked_names"] == ["antennapod", "osmand", "newpipe"]

    abst = by_id["cam-1"]
    assert abst["predicted"] is None and abst["answered"] is False
    assert abst["ranked_top1"] == "osmand"     # forced top-1 recorded even when abstained


def test_score_match_surfaces_bug_kind():
    from groundloop.eval.scorecard import score_match
    from groundloop.eval.runner import MatchRecord
    from groundloop.eval.dataset import EvalOracle
    rec = MatchRecord(case_id="c", arm="a", ranked_names=["oboe"], scores=[1.0],
                      predicted="oboe", margin=1.0, top1_score=1.0)
    m = score_match(rec, EvalOracle("oboe", bug_kind="functional"))
    assert m["bug_kind"] == "functional"
