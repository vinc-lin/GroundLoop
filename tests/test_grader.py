from groundloop.grade.grader import grade
from groundloop.core.types import RepoScore, RepoRef, Oracle
from groundloop.core.workflow import RunRecord
from groundloop.core.types import Patch, Change


def _record(ranked_names, locations, bound=True):
    ranked = [RepoScore(RepoRef(n), float(len(ranked_names) - i)) for i, n in enumerate(ranked_names)]
    ch = Change("Ixyz", "s", "GP-1", Patch("d", tuple(locations)))
    return RunRecord(ticket_id="GP-1", ranked=ranked, chosen=ranked[0].repo,
                     locations=list(locations), patch=ch.patch, change=ch, bound=bound, events=[])


def test_grade_scores_match_and_localization():
    rec = _record(["android-gpuimage-plus", "organicmaps"], ["cgeImageHandlerAndroid.cpp"])
    oracle = Oracle(owning_repo="android-gpuimage-plus", expected_files=("cgeImageHandlerAndroid.cpp",))
    sc = grade(rec, oracle)
    assert sc.repo_recall_at_1 == 1.0 and sc.repo_rank == 1 and sc.localization_recall == 1.0 and sc.bound

    rec2 = _record(["organicmaps", "android-gpuimage-plus"], [])
    sc2 = grade(rec2, oracle)
    assert sc2.repo_recall_at_1 == 0.0 and sc2.repo_rank == 2 and sc2.localization_recall == 0.0
