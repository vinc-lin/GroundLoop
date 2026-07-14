"""① Extract (design spec §5.1) — LLM-proposed decomposition of a feedstock Skill's prose into atomic,
typed candidate Knowledge items. A batch step (`gloop kb-extract`, A3 CLI) runs a Model over each Skill's
Signature:/Localize:/Fix: guidance + hint_apis + [skill.match], prompting for atomic items each with a
`content`, a `type`, an `applies_when` predicate (seeded from the Skill's match), and the `grounding_refs`
it names. The LLM is a PROPOSER only; its output is tolerant-parsed (mirror fixeval/plan.parse_plan — never
raises) and every candidate is DISPOSED downstream by kb/knowledge_ground.check_knowledge_grounded. A junk
decomposition just yields candidates that fail the gate — noisy, never dangerous.
"""
from __future__ import annotations

import hashlib
import json
import re

from groundloop.kb.knowledge import Knowledge
from groundloop.kb.knowledge_ground import GroundCheck, check_knowledge_grounded

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def _as_list(v) -> list:
    """Coerce a JSON value to a list before iterating; a bare str/dict/etc. -> [] (never char-iterate)."""
    return list(v) if isinstance(v, (list, tuple)) else []


def parse_knowledge(text: str) -> list[dict]:
    """Tolerant decode of a model's knowledge decomposition (```json fenced or a bare {...} span). Returns a
    list of raw item dicts (each with a non-empty content); [] on ANY failure — mirrors
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
    items = d.get("claims") if isinstance(d, dict) else d      # tolerate a top-level list of items
    out: list[dict] = []
    for c in _as_list(items):
        if isinstance(c, dict) and str(c.get("content", "")).strip():
            out.append(c)
    return out


def _knowledge_id(skill_id: str, ktype: str, content: str) -> str:
    """Stable, content-derived id, prefixed by the source Skill so items never collide across Skills."""
    h = hashlib.sha1(content.encode("utf-8")).hexdigest()[:8]
    return f"{skill_id}-{ktype or 'knowledge'}-{h}"


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


def knowledge_from_skill(skill: dict, model) -> list[Knowledge]:
    """LLM PROPOSES: decompose one feedstock Skill (a raw dict from kb/validate.load_corpus) into candidate
    Knowledge items at tier=candidate. `applies_when` falls back to the Skill's [skill.match] when the
    proposal omits it. Content-identical items within a Skill are de-duplicated by their derived id. Never
    raises on parse (the parse is tolerant); a `model.complete()` failure (e.g. a live gateway timeout) DOES
    propagate — the batch driver `extract_to_store` guards it per-skill so one failure never aborts the whole
    run."""
    skill_id = skill.get("id", "skill")
    default_match = dict(skill.get("match", {}) or {})
    raw = parse_knowledge(model.complete(_extract_prompt(skill)) or "")
    out: list[Knowledge] = []
    seen: set[str] = set()
    for c in raw:
        ktype = str(c.get("type", "")).strip()
        content = str(c.get("content", "")).strip()
        refs = tuple(str(r).strip() for r in _as_list(c.get("grounding_refs")) if str(r).strip())
        aw = c.get("applies_when")
        applies_when = aw if isinstance(aw, dict) and aw else dict(default_match)
        kid = _knowledge_id(skill_id, ktype, content)
        if kid in seen:
            continue
        seen.add(kid)
        out.append(Knowledge(id=kid, applies_when=applies_when, type=ktype, content=content,
                             grounding_refs=refs, provenance=skill_id, tier="candidate",
                             evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [],
                                       "fail_count": 0, "demotions": []}))
    return out


def extract_to_store(skills, model, resolver, *, denylist=None,
                     existing=None) -> tuple[dict[str, Knowledge], list[tuple[Knowledge, GroundCheck]]]:
    """Decompose every feedstock Skill -> candidate Knowledge, ground-check each (A2), and MERGE the
    survivors into the store dict at tier=candidate. Returns (admitted_store, rejected[(knowledge, check)]).
    Oracle-blind: grounding hits the atlas via `resolver`, never the oracle. Unique-id well-formedness is
    enforced at the store layer via setdefault (content-derived ids are stable, so a re-extract keeps the
    first)."""
    store: dict[str, Knowledge] = dict(existing or {})
    rejected: list[tuple[Knowledge, GroundCheck]] = []
    for skill in skills:
        try:
            items = knowledge_from_skill(skill, model)   # the only step that can hit the live model
        except Exception as e:                           # one skill's model failure must not lose the batch
            print(f"kb-extract: skill {skill.get('id', '?')!r} extraction failed ({e}) — skipped")
            continue
        for item in items:
            chk = check_knowledge_grounded(item, resolver, denylist=denylist)
            if not chk.grounded:
                rejected.append((item, chk))
                continue
            store.setdefault(item.id, item)
    return store, rejected
