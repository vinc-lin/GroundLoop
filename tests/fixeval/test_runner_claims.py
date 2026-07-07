"""Claim injection through FixEvalRunner (Phase B3). Mirrors tests/fixeval/test_skill_injection.py: a
spy model (_Capture) records the prompts the fixer builds; the plan path (PlanningFixEngine) is where a
claim preamble lands. Asserts injection, the tier-floor gate, localize-invariance (claims never feed the
localize query), and that the skills-only / none-none paths stay byte-identical to pre-B3."""
import shutil
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.fix.planning import PlanningFixEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.kb.claim import Claim
from groundloop.kb.registry import ClaimRegistry
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
_CONTENT = "Reject a 0 nativePtr handle at native method entry before dereferencing it."


class _Capture:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return ""


def _claim(cid, tier="candidate"):
    # always-firing predicate: the injection plumbing (not predicate matching, which B1 covers) is under test.
    return Claim(id=cid, applies_when={"always": True}, type="fix_step", content=_CONTENT,
                 grounding_refs=(), provenance="p", tier=tier, evidence={})


def _runner(tmp_path, tag, *, skills=None, claims=None, claims_tier_floor="validated"):
    ds = tmp_path / f"ds-{tag}"
    ds.mkdir(parents=True)
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return (FixEvalRunner(issues=MockJira(str(ds)),
                          estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / f"w-{tag}")),
                          catalog=CATALOG, tau_margin=0.0, tau_score=0.0,
                          skills=skills, claims=claims, claims_tier_floor=claims_tier_floor),
            load_cases(str(ds)))


def test_claims_inject_into_plan_prompt(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    reg = ClaimRegistry([_claim("c-seg")])
    runner, cases = _runner(tmp_path, "inj", claims=reg, claims_tier_floor="candidate")
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(cap))
    injected = [p for p in cap.prompts if "# Grounded claims" in p]
    assert injected, "claims=candidate must inject the claim preamble into the plan prompt"
    assert any(_CONTENT in p for p in injected)


def test_candidate_tier_gated_out_at_validated_floor(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    reg = ClaimRegistry([_claim("c-seg", tier="candidate")])
    runner, cases = _runner(tmp_path, "gate", claims=reg, claims_tier_floor="validated")
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(cap))
    assert cap.prompts and not any("# Grounded claims" in p for p in cap.prompts)


def test_claims_are_localize_invariant(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    reg = ClaimRegistry([_claim("c-seg")])
    r_none, cases_none = _runner(tmp_path, "none", claims=None)
    rec_none = r_none.run(cases_none, build_arms(membership_index=AtlasIndex(db)),
                          fixer=PlanningFixEngine(_Capture()))
    r_cl, cases_cl = _runner(tmp_path, "claims", claims=reg, claims_tier_floor="candidate")
    rec_cl = r_cl.run(cases_cl, build_arms(membership_index=AtlasIndex(db)),
                      fixer=PlanningFixEngine(_Capture()))
    # claims never feed _skill_query, so localize is unchanged vs the none arm.
    assert [r.locations for r in rec_none] == [r.locations for r in rec_cl]


def test_back_compat_skills_only_no_claim_header(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, "sk", skills=MockSkillRegistry.load(), claims=None)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    injected = [p for p in cap.prompts if "# Applicable playbooks" in p]
    assert injected and any("aaos-native-lib-load-failure" in p for p in injected)
    assert not any("# Grounded claims" in p for p in cap.prompts)   # claims=None -> no claim block


def test_back_compat_none_none_no_preamble(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, "off", skills=None, claims=None)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    assert cap.prompts and not any(
        "# Applicable playbooks" in p or "# Grounded claims" in p for p in cap.prompts)


def test_runner_records_fired_claims(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    reg = ClaimRegistry([_claim("c-seg")])
    runner, cases = _runner(tmp_path, "rec", claims=reg, claims_tier_floor="candidate")
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(_Capture()))
    matched = [r for r in recs if r.predicted_repo]                # claim fires only post-match
    assert matched and all("c-seg" in r.fired_claims for r in matched)


def test_runner_no_claim_fires_empty_fired_claims(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    # a predicate that never matches this fixture -> selection empty -> fired_claims == ()
    non_firing = Claim(id="c-none", applies_when={"any_text": ["nonexistent_token_zzz"]}, type="fix_step",
                       content=_CONTENT, grounding_refs=(), provenance="p", tier="candidate", evidence={})
    runner, cases = _runner(tmp_path, "nofire", claims=ClaimRegistry([non_firing]),
                            claims_tier_floor="candidate")
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(_Capture()))
    assert recs and all(r.fired_claims == () for r in recs)
