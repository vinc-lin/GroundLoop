import pathlib
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


def test_fix_runner_never_reads_oracle(tmp_path, monkeypatch):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    idx = AtlasIndex(build_fix_atlas_fixture(str(tmp_path / "atlas.db")))
    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])
    FixEvalRunner(issues=MockJira(str(ds)), estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "w")),
                  catalog=[RepoRef("android-gpuimage-plus")], tau_margin=0.0, tau_score=0.0).run(
        load_cases(str(ds)), build_arms(membership_index=idx),
        fixer=ModelPatchEngine(CannedModel({"default": ""})))
    leaked = [r for r in reads if "_oracle" in pathlib.Path(r).parts]
    assert not leaked, f"fix runner read the oracle: {leaked}"
