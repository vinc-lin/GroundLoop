"""Deterministic feedstock parser (replaces the retired LLM kb-extract). Splits a Skill's guidance
Signature:/Localize:/Fix: clauses into a KnowledgePlaybook, grounds it, and seeds the candidate store."""
from __future__ import annotations

from groundloop.kb.knowledge import KnowledgePlaybook
from groundloop.kb.knowledge_ground import GroundCheck, check_knowledge_grounded

_SEED_EVIDENCE = {"measured_lift": {}, "wilson95": None, "validating_case_ids": [], "fail_count": 0, "demotions": []}


def _clause(guidance: str, label: str) -> str:
    """The text of one 'Label: ...' clause (one line in the feedstock), else ''."""
    for line in guidance.splitlines():
        s = line.strip()
        if s.startswith(label):
            return s[len(label):].strip()
    return ""


def playbook_from_skill(skill: dict) -> KnowledgePlaybook:
    """Parse one raw feedstock Skill dict (from kb/validate.load_corpus) into a KnowledgePlaybook at
    tier=candidate. No model involved: signature/localize/fix are lifted verbatim from the Skill's
    Signature:/Localize:/Fix: guidance clauses; required_apis/grounding_refs = the Skill's hint_apis;
    applies_when = the Skill's own [skill.match] predicate."""
    g = skill.get("guidance", "")
    apis = tuple(str(a).strip() for a in (skill.get("hint_apis") or ()) if str(a).strip())
    loc, fix = _clause(g, "Localize:"), _clause(g, "Fix:")
    return KnowledgePlaybook(
        id=str(skill.get("id", "")), applies_when=dict(skill.get("match", {}) or {}),
        signature=_clause(g, "Signature:"), localize=((loc,) if loc else ()), fix=((fix,) if fix else ()),
        required_apis=apis, grounding_refs=apis, provenance=str(skill.get("id", "")),
        tier="candidate", evidence=dict(_SEED_EVIDENCE))


def seed_to_store(skills, resolver, *, denylist=None, existing=None):
    """Parse+ground every feedstock Skill; merge survivors at tier=candidate (setdefault, idempotent).
    Returns (admitted_store, rejected[(playbook, GroundCheck)]). Oracle-blind: grounding hits the atlas
    via `resolver`, never the oracle."""
    store = dict(existing or {})
    rejected: list[tuple[KnowledgePlaybook, GroundCheck]] = []
    for skill in skills:
        pb = playbook_from_skill(skill)
        chk = check_knowledge_grounded(pb, resolver, denylist=denylist)
        (rejected.append((pb, chk)) if not chk.grounded else store.setdefault(pb.id, pb))
    return store, rejected
