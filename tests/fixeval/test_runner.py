import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
# canonical git-generated diff (a single-line hunk with no context does NOT apply — git needs context)
GOLD = ("```diff\n"
        "--- a/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "+++ b/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "@@ -1,4 +1,4 @@\n"
        "-// bug\n"
        "+// fixed nativeCreateHandler\n"
        ' #include "cgeImageHandler.h"\n'
        " namespace CGE {\n"
        " jlong nativeCreateHandler(JNIEnv*, jclass) {\n"
        "```")


def _dataset(tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return str(ds)


def _runner(tmp_path, tau_score):
    ds = _dataset(tmp_path)
    runner = FixEvalRunner(issues=MockJira(ds),
                           estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "work")),
                           catalog=CATALOG, tau_margin=0.0, tau_score=tau_score)
    return runner, load_cases(ds)


def test_happy_path_emits_applying_patch(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    runner, cases = _runner(tmp_path, tau_score=0.0)
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)),
                      fixer=ModelPatchEngine(CannedModel({"default": GOLD})))
    logs = next(r for r in recs if r.arm == "membership+logs")
    assert logs.predicted_repo == "android-gpuimage-plus"
    assert logs.patch_emitted and logs.patch_applies and not logs.abstained
    assert logs.cost_usd == 0.0


def test_match_abstain_yields_no_patch(tmp_path):
    # membership+text extracts from the description ONLY (no logcat), which carries no discriminative
    # tokens for gpuimage-352, so Stage-1 finds zero evidence -> no_repo_match abstain (no fix stage).
    # (Note: build_arms sets a per-arm tau of (1.0, 1.0); the runner-level tau is a fallback only.)
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    runner, cases = _runner(tmp_path, tau_score=1.0)
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)),
                      fixer=ModelPatchEngine(CannedModel({"default": GOLD})))
    text = next(r for r in recs if r.arm == "membership+text")
    assert text.abstained and text.abstain_reason == "no_repo_match" and not text.patch_emitted
