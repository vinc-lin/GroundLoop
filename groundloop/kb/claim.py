"""The atomic Claim — the unit of trust in the claim-centric distilled KB (design spec
docs/superpowers/specs/2026-07-07-claim-centric-distilled-kb-design.md §4). A Claim is a self-contained,
GROUNDED piece of advice carrying its OWN firing predicate (`applies_when`, a [skill.match]-style spec
reusing groundloop/skills/predicate.compile_predicate) — never a whole Skill.

Claims persist in a machine-updated JSON store (`groundloop/kb/data/claims.json`, keyed by claim id —
analogous to kb/provenance.py's sidecar): the retain-loop mutates tier + evidence, while the human-authored
feedstock stays the aaos_kb_seed.toml Skills that extraction (A3) decomposes. The `evidence` dict is the
lifecycle-bookkeeping bag (measured_lift, wilson95, validating_case_ids, fail_count, demotions,
evidence_context); Phase C bridges tier + evidence[fail_count]/[demotions] to the reused
kb/lifecycle.apply_verdict (which reads .tier/.fail_count/.demotions). Phase A only persists it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CLAIMS_PATH = str(Path(__file__).parent / "data" / "claims.json")

# JSON has no tuple — grounding_refs serializes as a list and must be re-tupled on load so frozen-dataclass
# equality (round-trip test + Phase-C diffing) holds. applies_when / evidence stay dicts.
_TUPLE_FIELDS = ("grounding_refs",)


@dataclass(frozen=True)
class Claim:
    id: str
    applies_when: dict            # a [skill.match]-style predicate: WHEN this claim fires
    type: str                     # "localize_hint" | "fix_step" | "api_requirement"
    content: str                  # the ONE thing it advises (this text enters the plan prompt)
    grounding_refs: tuple[str, ...]  # the code entities it asserts exist (checkable in the atlas)
    provenance: str               # the source Skill id it was distilled from (kept; never trusted)
    tier: str                     # "candidate" | "validated" | "canonical" | "retired"
    evidence: dict = field(default_factory=dict)  # lifecycle-bookkeeping bag (see module docstring)


def _to_claim(cid: str, raw: dict) -> Claim:
    """Build a Claim from a raw JSON row: drop unknown keys, default the id from its dict key, re-tuple."""
    known = {f.name for f in fields(Claim)}
    kw = {k: v for k, v in raw.items() if k in known}
    kw.setdefault("id", cid)                       # id is the dict key; tolerate its absence in the body
    for tf in _TUPLE_FIELDS:
        if kw.get(tf) is not None and not isinstance(kw[tf], tuple):
            kw[tf] = tuple(kw[tf])
    return Claim(**kw)


def load_claims(path: str = CLAIMS_PATH) -> dict[str, Claim]:
    """Load the claim store keyed by claim id; a missing file is an empty store (no claims yet), not an
    error — mirrors kb/provenance.load_sidecar."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {cid: _to_claim(cid, row) for cid, row in raw.items()}


def save_claims(path: str, claims: dict[str, Claim]) -> None:
    """Write the store as deterministic (sorted-key, indented) JSON, keyed by the passed keys."""
    out = {cid: asdict(c) for cid, c in claims.items()}
    Path(path).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
