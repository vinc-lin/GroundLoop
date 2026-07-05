import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]


class _Capture:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return ""


def _runner(tmp_path, skills):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return (FixEvalRunner(issues=MockJira(str(ds)),
                          estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "w")),
                          catalog=CATALOG, tau_margin=0.0, tau_score=0.0, skills=skills),
            load_cases(str(ds)))


def test_skills_none_is_noop(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, skills=None)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    assert cap.prompts and not any("# Applicable playbooks" in p for p in cap.prompts)


def test_skills_mock_injects_native_playbook(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, skills=MockSkillRegistry.load())
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    injected = [p for p in cap.prompts if "# Applicable playbooks" in p]
    assert injected, "skills=mock must inject a preamble on the native crash case"
    assert any("aaos-native-lib-load-failure" in p for p in injected)
