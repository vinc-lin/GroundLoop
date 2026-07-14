"""A/B fix-eval orchestration over dev-experience-KB arms {none, kb, placebo}. Each arm reruns the SAME
whole-loop fix-eval (FixEvalRunner + grade_fix_all) with a different KNOWLEDGE registry injected at the
FIX stage: none = knowledge off (byte-identical to pre-SP3), kb = the distilled Knowledge (candidate
floor) over groundloop/kb/data/knowledge.json, placebo = the per-item length-matched IRRELEVANT control
that fires on the SAME cases. An empty knowledge.json -> every arm selects nothing -> byte-identical to
none (honest cold-start). Writes one scorecard-<arm>.json per arm under out_dir and returns {arm: card}.
Oracle-blind loop; grade_fix_all is the sole oracle read. _make_fixer mirrors the CLI fixeval handler and
is monkeypatched by hermetic tests to inject a scripted CannedModel."""
from __future__ import annotations

import json
import os
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.fixeval.scorecard import grade_fix_all
from groundloop.kb.knowledge import KNOWLEDGE_PATH, load_knowledge
from groundloop.kb.knowledge_placebo import build_knowledge_placebo
from groundloop.kb.registry import KnowledgeRegistry


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
    """Map an A/B arm to its KNOWLEDGE registry (None = the true no-op `none` arm). kb = distilled
    Knowledge (candidate floor); placebo = the per-item knowledge placebo (same firing set, scrambled
    content). Reads knowledge.json; an empty store -> empty registry -> every arm == none (cold-start)."""
    if arm == "none":
        return None
    store = load_knowledge(KNOWLEDGE_PATH)
    if arm == "kb":
        return KnowledgeRegistry(list(store.values()), embedder=embedder)
    if arm == "placebo":
        return KnowledgeRegistry(list(build_knowledge_placebo(store).values()), embedder=embedder)
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
        knowledge = _registry_for(arm, embedder)
        runner = FixEvalRunner(issues=MockJira(dataset),
                               estate=GitFixtureEstate(repos, str(out / f"_work-{arm}")),
                               catalog=catalog, tau_margin=0.0, tau_score=0.0,
                               knowledge=knowledge, knowledge_tier_floor="candidate")
        records = runner.run(cases, eval_arms, fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        (out / f"scorecard-{arm}.json").write_text(json.dumps(card, indent=2))
        cards[arm] = card
    return cards
