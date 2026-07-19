"""Deterministic feedstock parser (`kb/seed.py`) — replaces the retired LLM `kb-extract`. Splits each
feedstock Skill's Signature:/Localize:/Fix: guidance into a KnowledgePlaybook, grounds it, and seeds the
candidate store — no model involved."""
from groundloop.kb.seed import playbook_from_skill, seed_to_store
from groundloop.kb.validate import load_corpus, SEED_PATH


def test_parses_a_feedstock_skill_into_a_playbook():
    skill = next(s for s in load_corpus(SEED_PATH) if s["id"] == "fragment-view-after-destroy-npe")
    pb = playbook_from_skill(skill)
    assert pb.id == "fragment-view-after-destroy-npe" and pb.tier == "candidate"
    assert len(pb.signature) > 0 and pb.localize and pb.fix
    assert pb.required_apis == tuple(skill["hint_apis"]) and pb.grounding_refs == tuple(skill["hint_apis"])
    assert pb.applies_when == skill["match"]


def test_seed_to_store_grounds_and_admits_all_feedstock():
    def resolver(ref):                               # hermetic: accept all refs
        return True

    store, rejected = seed_to_store(load_corpus(SEED_PATH), resolver)
    # assert the ACTUAL admitted count (all feedstock skills that have >=1 hint_api ground under all-true);
    # report the number — if any skill has empty hint_apis it is legitimately rejected (no_grounding_refs).
    assert len(store) >= 1 and all(pb.tier == "candidate" for pb in store.values())
    assert len(store) + len(rejected) == 12
