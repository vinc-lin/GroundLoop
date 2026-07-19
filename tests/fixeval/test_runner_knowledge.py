"""Knowledge injection through FixEvalRunner (Phase B3; playbook-shape migrated in Task 2 of the KB
playbook redesign). Mirrors tests/fixeval/test_skill_injection.py: a spy model (_Capture) records the
prompts the fixer builds; the plan path (PlanningFixEngine) is where a playbook preamble
(render_playbooks -> "# Grounded playbooks") lands. Asserts injection, the tier-floor gate,
localize-invariance (knowledge never feeds the localize query), and that the skills-only / none-none
paths stay byte-identical to pre-B3."""
import shutil
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.fix.planning import PlanningFixEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.skills.adapters.mock import MockSkillRegistry
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.registry import KnowledgeRegistry
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


def _knowledge(kid, tier="candidate"):
    # always-firing predicate: the injection plumbing (not predicate matching, which B1 covers) is under test.
    return Knowledge(id=kid, applies_when={"always": True}, fix=(_CONTENT,),
                     grounding_refs=(), provenance="p", tier=tier, evidence={})


def _runner(tmp_path, tag, *, skills=None, knowledge=None, knowledge_tier_floor="validated"):
    ds = tmp_path / f"ds-{tag}"
    ds.mkdir(parents=True)
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return (FixEvalRunner(issues=MockJira(str(ds)),
                          estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / f"w-{tag}")),
                          catalog=CATALOG, tau_margin=0.0, tau_score=0.0,
                          skills=skills, knowledge=knowledge, knowledge_tier_floor=knowledge_tier_floor),
            load_cases(str(ds)))


def test_knowledge_injects_into_plan_prompt(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    reg = KnowledgeRegistry([_knowledge("c-seg")])
    runner, cases = _runner(tmp_path, "inj", knowledge=reg, knowledge_tier_floor="candidate")
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(cap))
    injected = [p for p in cap.prompts if "# Grounded playbooks" in p]
    assert injected, "knowledge=candidate must inject the knowledge preamble into the plan prompt"
    assert any(_CONTENT in p for p in injected)


def test_both_channels_inject_and_compose_in_order(tmp_path):
    # BOTH arms on: the plan prompt must carry the skill preamble AND the knowledge preamble, skills first.
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    reg = KnowledgeRegistry([_knowledge("c-seg")])            # always-firing candidate item
    runner, cases = _runner(tmp_path, "both", skills=MockSkillRegistry.load(), knowledge=reg,
                            knowledge_tier_floor="candidate")
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(cap))
    composed = [p for p in cap.prompts
                if "# Applicable playbooks" in p and "# Grounded playbooks" in p]
    assert composed, "both arms on -> one prompt must carry BOTH preambles"
    for p in composed:
        assert p.index("# Applicable playbooks") < p.index("# Grounded playbooks")   # skills first


def test_candidate_tier_gated_out_at_validated_floor(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    reg = KnowledgeRegistry([_knowledge("c-seg", tier="candidate")])
    runner, cases = _runner(tmp_path, "gate", knowledge=reg, knowledge_tier_floor="validated")
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(cap))
    assert cap.prompts and not any("# Grounded playbooks" in p for p in cap.prompts)


def test_knowledge_is_localize_invariant(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    reg = KnowledgeRegistry([_knowledge("c-seg")])
    r_none, cases_none = _runner(tmp_path, "none", knowledge=None)
    rec_none = r_none.run(cases_none, build_arms(membership_index=AtlasIndex(db)),
                          fixer=PlanningFixEngine(_Capture()))
    r_kn, cases_kn = _runner(tmp_path, "knowledge", knowledge=reg, knowledge_tier_floor="candidate")
    rec_kn = r_kn.run(cases_kn, build_arms(membership_index=AtlasIndex(db)),
                      fixer=PlanningFixEngine(_Capture()))
    # knowledge never feeds _skill_query, so localize is unchanged vs the none arm.
    assert [r.locations for r in rec_none] == [r.locations for r in rec_kn]


def test_back_compat_skills_only_no_knowledge_header(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, "sk", skills=MockSkillRegistry.load(), knowledge=None)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    injected = [p for p in cap.prompts if "# Applicable playbooks" in p]
    assert injected and any("aaos-native-lib-load-failure" in p for p in injected)
    assert not any("# Grounded playbooks" in p for p in cap.prompts)   # knowledge=None -> no knowledge block


def test_back_compat_none_none_no_preamble(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, "off", skills=None, knowledge=None)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    assert cap.prompts and not any(
        "# Applicable playbooks" in p or "# Grounded playbooks" in p for p in cap.prompts)


def test_runner_records_fired_knowledge(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    reg = KnowledgeRegistry([_knowledge("c-seg")])
    runner, cases = _runner(tmp_path, "rec", knowledge=reg, knowledge_tier_floor="candidate")
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(_Capture()))
    matched = [r for r in recs if r.predicted_repo]                # knowledge fires only post-match
    assert matched and all("c-seg" in r.fired_knowledge for r in matched)


def test_runner_no_knowledge_fires_empty_fired_knowledge(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    # a predicate that never matches this fixture -> selection empty -> fired_knowledge == ()
    non_firing = Knowledge(id="c-none", applies_when={"any_text": ["nonexistent_token_zzz"]}, fix=(_CONTENT,),
                           grounding_refs=(), provenance="p", tier="candidate", evidence={})
    runner, cases = _runner(tmp_path, "nofire", knowledge=KnowledgeRegistry([non_firing]),
                            knowledge_tier_floor="candidate")
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=PlanningFixEngine(_Capture()))
    assert recs and all(r.fired_knowledge == () for r in recs)
