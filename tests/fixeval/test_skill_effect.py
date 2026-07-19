"""Hermetic direction-of-effect for the KB arm. A scripted CannedModel returns the GOLD diff ONLY when
the '# Applicable playbooks' preamble is present -> proves the arm MOVES an outcome (abstain -> applying
patch) via the injection plumbing. NOT a real-lift claim (that is the Type-2 gated measurement)."""
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.skills.adapters.mock import MockSkillRegistry
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.fixeval.scorecard import grade_fix_all
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
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


def _run(tmp_path, db, skills):
    ds = tmp_path / ("on" if skills else "off")
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    # model emits GOLD only when the playbook header is present; empty otherwise
    model = CannedModel({"# Applicable playbooks": GOLD, "default": ""})
    runner = FixEvalRunner(issues=MockJira(str(ds)),
                           estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / ("w_on" if skills else "w_off"))),
                           catalog=CATALOG, tau_margin=0.0, tau_score=0.0, skills=skills)
    cases = load_cases(str(ds))
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(model))
    oracle = {c.case_id: load_eval_oracle(c) for c in cases}
    return recs, grade_fix_all(recs, oracle_by_case=oracle)


def test_skills_arm_moves_outcome_on_native_positive(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    off_recs, off_card = _run(tmp_path, db, skills=None)
    on_recs, on_card = _run(tmp_path, db, skills=MockSkillRegistry.load())
    off = next(r for r in off_recs if r.arm == "membership+logs")
    on = next(r for r in on_recs if r.arm == "membership+logs")
    assert off.abstained and off.abstain_reason == "patch_unappliable"   # no preamble -> "" -> abstain
    assert on.patch_emitted and on.patch_applies and not on.abstained    # preamble -> GOLD -> applies
    # file_recall@1 is a LOCALIZATION metric (over rec.locations) — invariant to the patch/skills, so it
    # is 1.0 in BOTH arms (localization is identical). The scorecard direction-of-effect lands in
    # resolved_rate (patch applies AND recalls the gold file), which moves 0.0 -> 1.0.
    assert on_card["arms"]["membership+logs"]["file_recall@1"]["value"] == 1.0    # on-path (watch-out)
    assert off_card["arms"]["membership+logs"]["resolved_rate"]["value"] == 0.0   # abstain -> unresolved
    assert on_card["arms"]["membership+logs"]["resolved_rate"]["value"] == 1.0    # applying patch -> resolved
