"""① Extract (design spec §5.1) — LLM-proposed decomposition of a feedstock Skill's prose into atomic,
typed candidate Claims. A batch step (`gloop kb-extract`, A3 CLI) runs a Model over each Skill's
Signature:/Localize:/Fix: guidance + hint_apis + [skill.match], prompting for atomic claims each with a
`content`, a `type`, an `applies_when` predicate (seeded from the Skill's match), and the `grounding_refs`
it names. The LLM is a PROPOSER only; its output is tolerant-parsed (mirror fixeval/plan.parse_plan — never
raises) and every candidate is DISPOSED downstream by kb/claim_ground.check_claim_grounded. A junk
decomposition just yields candidates that fail the gate — noisy, never dangerous.
"""
from __future__ import annotations

import hashlib
import json
import re

from groundloop.kb.claim import Claim
from groundloop.kb.claim_ground import GroundCheck, check_claim_grounded

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def _as_list(v) -> list:
    """Coerce a JSON value to a list before iterating; a bare str/dict/etc. -> [] (never char-iterate)."""
    return list(v) if isinstance(v, (list, tuple)) else []


def parse_claims(text: str) -> list[dict]:
    """Tolerant decode of a model's claim decomposition (```json fenced or a bare {...} span). Returns a
    list of raw claim dicts (each with a non-empty content); [] on ANY failure — mirrors
    fixeval/plan.parse_plan and NEVER raises."""
    if not text or not text.strip():
        return []
    m = _JSON_FENCE.search(text)
    raw = m.group(1) if m else text
    if not m:
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1 or j < i:
            return []
        raw = raw[i:j + 1]
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    claims = d.get("claims") if isinstance(d, dict) else d      # tolerate a top-level list of claims
    out: list[dict] = []
    for c in _as_list(claims):
        if isinstance(c, dict) and str(c.get("content", "")).strip():
            out.append(c)
    return out


def _claim_id(skill_id: str, ctype: str, content: str) -> str:
    """Stable, content-derived id, prefixed by the source Skill so claims never collide across Skills."""
    h = hashlib.sha1(content.encode("utf-8")).hexdigest()[:8]
    return f"{skill_id}-{ctype or 'claim'}-{h}"


def _extract_prompt(skill: dict) -> str:
    guidance = skill.get("guidance", "")
    hint_apis = ", ".join(skill.get("hint_apis", ()) or ())
    match = json.dumps(skill.get("match", {}) or {})
    return (
        "Decompose the crash-RCA playbook below into ATOMIC, self-contained claims. Each claim advises "
        "exactly ONE thing and names the concrete code entities (API / symbol / file names) it asserts "
        'exist. Reply ONLY with a JSON object {"claims": [{type, content, grounding_refs, applies_when}]} '
        "where:\n"
        '- type is one of "localize_hint" | "fix_step" | "api_requirement";\n'
        "- content is the single piece of advice (this exact text is injected into a repair prompt);\n"
        "- grounding_refs is a list of the code entities the claim names;\n"
        "- applies_when is a [skill.match]-style predicate for WHEN the claim fires (default: the "
        "playbook's own match below).\n"
        "Name NO product / repo / vendor identifiers — stay generic to the crash signature.\n\n"
        f"Playbook guidance:\n{guidance}\n\n"
        f"Known APIs: {hint_apis}\n"
        f"Playbook match predicate: {match}\n"
    )


def claims_from_skill(skill: dict, model) -> list[Claim]:
    """LLM PROPOSES: decompose one feedstock Skill (a raw dict from kb/validate.load_corpus) into candidate
    Claims at tier=candidate. `applies_when` falls back to the Skill's [skill.match] when the proposal omits
    it. Content-identical claims within a Skill are de-duplicated by their derived id. Never raises."""
    skill_id = skill.get("id", "skill")
    default_match = dict(skill.get("match", {}) or {})
    raw = parse_claims(model.complete(_extract_prompt(skill)) or "")
    out: list[Claim] = []
    seen: set[str] = set()
    for c in raw:
        ctype = str(c.get("type", "")).strip()
        content = str(c.get("content", "")).strip()
        refs = tuple(str(r).strip() for r in _as_list(c.get("grounding_refs")) if str(r).strip())
        aw = c.get("applies_when")
        applies_when = aw if isinstance(aw, dict) and aw else dict(default_match)
        cid = _claim_id(skill_id, ctype, content)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(Claim(id=cid, applies_when=applies_when, type=ctype, content=content,
                         grounding_refs=refs, provenance=skill_id, tier="candidate",
                         evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [],
                                   "fail_count": 0, "demotions": []}))
    return out


def extract_to_store(skills, model, resolver, *, denylist=None,
                     existing=None) -> tuple[dict[str, Claim], list[tuple[Claim, GroundCheck]]]:
    """Decompose every feedstock Skill -> candidate Claims, ground-check each (A2), and MERGE the survivors
    into the store dict at tier=candidate. Returns (admitted_store, rejected[(claim, check)]). Oracle-blind:
    grounding hits the atlas via `resolver`, never the oracle. Unique-id well-formedness is enforced at the
    store layer via setdefault (content-derived ids are stable, so a re-extract keeps the first)."""
    store: dict[str, Claim] = dict(existing or {})
    rejected: list[tuple[Claim, GroundCheck]] = []
    for skill in skills:
        for claim in claims_from_skill(skill, model):
            chk = check_claim_grounded(claim, resolver, denylist=denylist)
            if not chk.grounded:
                rejected.append((claim, chk))
                continue
            store.setdefault(claim.id, claim)
    return store, rejected
