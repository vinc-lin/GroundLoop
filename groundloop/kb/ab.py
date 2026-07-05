"""A/B fix-eval orchestration over dev-experience-KB arms {none, kb, placebo}. Each arm reruns the SAME
whole-loop fix-eval (FixEvalRunner + grade_fix_all) with a different skills registry injected at the FIX
stage: none = skills off (byte-identical to pre-SP3), kb = OUR 12-skill corpus (groundloop/kb/data/
aaos_kb_seed.toml), placebo = the length-matched IRRELEVANT control that fires on the SAME cases. Writes
one scorecard-<arm>.json per arm under out_dir and returns {arm: card}. Oracle-blind loop; grade_fix_all
is the sole oracle read. _make_fixer mirrors the CLI fixeval handler and is monkeypatched by hermetic
tests to inject a scripted CannedModel."""
from __future__ import annotations

import json
import os
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.fixeval.scorecard import grade_fix_all
from groundloop.kb.placebo import KB_SEED, PLACEBO_SEED


def _make_fixer():
    """The fix-stage FixEngine, wired exactly like the CLI fixeval handler: a live GatewayModel when
    KLOOP_PRODUCE_API_KEY is set, else a hermetic CannedModel (every case abstains at fix). Tests
    monkeypatch this symbol to inject a scripted CannedModel."""
    if os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
        from groundloop.adapters.model.gateway import GatewayModel
        from groundloop.config.settings import Settings
        s = Settings.load()
        model = GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
    else:
        model = CannedModel({"default": ""})
    return ModelPatchEngine(model)


def _registry_for(arm: str, embedder):
    """Map an A/B arm name to its skills registry (None = the true no-op `none` arm)."""
    if arm == "none":
        return None
    if arm == "kb":
        return MockSkillRegistry.load(path=KB_SEED, embedder=embedder)
    if arm == "placebo":
        return MockSkillRegistry.load(path=PLACEBO_SEED, embedder=embedder)
    raise ValueError(f"unknown A/B arm: {arm!r} (expected one of none|kb|placebo)")


def run_ab(*, dataset, repos, index_db, catalog_path, out_dir,
           arms=("none", "kb", "placebo"), embedder=None) -> dict[str, dict]:
    catalog = [RepoRef(r["name"]) for r in json.loads(Path(catalog_path).read_text())]
    cases = load_cases(dataset)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — sole oracle read
    eval_arms = build_arms(membership_index=AtlasIndex(index_db))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cards: dict[str, dict] = {}
    for arm in arms:
        skills = _registry_for(arm, embedder)
        runner = FixEvalRunner(issues=MockJira(dataset),
                               estate=GitFixtureEstate(repos, str(out / f"_work-{arm}")),
                               catalog=catalog, tau_margin=0.0, tau_score=0.0, skills=skills)
        records = runner.run(cases, eval_arms, fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        (out / f"scorecard-{arm}.json").write_text(json.dumps(card, indent=2))
        cards[arm] = card
    return cards
