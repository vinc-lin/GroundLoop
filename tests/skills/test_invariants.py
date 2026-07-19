"""Anti-leak invariants for the KB arm: the registry/ctx read no _oracle/, the seed guidance names no
fleet repo, and an empty preamble is a true no-op (so the measured Δ is clean)."""
import pathlib
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.skills.adapters.mock import MockSkillRegistry, load_skills, SEED_PATH
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
FLEET = ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview", "oboe", "osmand")


def test_seed_guidance_names_no_fleet_repo():
    for s in load_skills(SEED_PATH):
        blob = (s.guidance + " " + s.provenance).lower()
        for repo in FLEET:
            assert repo.lower() not in blob, f"skill {s.id} leaks fleet repo {repo}"


def test_skills_path_never_reads_oracle(tmp_path, monkeypatch):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])
    FixEvalRunner(issues=MockJira(str(ds)),
                  estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "w")),
                  catalog=[RepoRef("android-gpuimage-plus")], tau_margin=0.0, tau_score=0.0,
                  skills=MockSkillRegistry.load()).run(
        load_cases(str(ds)), build_arms(membership_index=AtlasIndex(db)),
        fixer=ModelPatchEngine(CannedModel({"default": ""})))
    leaked = [r for r in reads if "_oracle" in pathlib.Path(r).parts]
    assert not leaked, f"KB path read the oracle: {leaked}"


def test_non_applicable_case_preamble_is_empty(tmp_path):
    from groundloop.core.types import Signals, Ticket, LogAttachment
    from groundloop.skills.base import render_skills
    from groundloop.skills.ctx import build_ctx
    tk = Ticket(id="NEG", summary="Live preview freezes intermittently",
                description="No crash is shown; the UI just stops refreshing.",
                logs=(LogAttachment(path="l", kind="logcat", content="ui stops refreshing"),))
    preamble = render_skills(MockSkillRegistry.load().select(build_ctx(Signals(), tk, "cameraview")))
    assert preamble == ""      # no native/JNI/ops cue -> no skill -> empty -> no-op vs skills=none
