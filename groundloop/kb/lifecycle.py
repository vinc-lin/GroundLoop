"""Lifecycle tier manager for KB provenance records.

A Skill climbs the trust ladder one rung per passing verdict and slides down only after
`hysteresis` CONSECUTIVE failing verdicts (so a single noisy A/B run cannot demote a canonical
playbook). Records are frozen `ProvenanceRecord`s (B1); every transition returns a NEW record via
`dataclasses.replace` — the input is never mutated.
"""
from __future__ import annotations

import dataclasses

from groundloop.kb.provenance import ProvenanceRecord

# Trust ladder, lowest -> highest. Ordered; index arithmetic drives promote/demote.
TIERS: tuple[str, ...] = ("candidate", "applied", "validated", "canonical")


def next_tier(t: str) -> str:
    """The tier one rung up, clamped at the top (`canonical` stays `canonical`)."""
    i = TIERS.index(t)
    return TIERS[min(i + 1, len(TIERS) - 1)]


def prev_tier(t: str) -> str:
    """The tier one rung down, clamped at the bottom (`candidate` stays `candidate`)."""
    i = TIERS.index(t)
    return TIERS[max(i - 1, 0)]


def apply_verdict(
    rec: ProvenanceRecord, passed: bool, *, hysteresis: int = 2
) -> ProvenanceRecord:
    """Fold one A/B verdict into a provenance record and return the updated (new) record.

    passed -> promote one tier and reset the fail streak.
    failed -> increment the fail streak; only once it reaches `hysteresis` do we demote one tier,
              record the `from->to` transition in `demotions`, and reset the streak.
    """
    if passed:
        return dataclasses.replace(rec, tier=next_tier(rec.tier), fail_count=0)

    streak = rec.fail_count + 1
    if streak < hysteresis:
        return dataclasses.replace(rec, fail_count=streak)

    demoted = prev_tier(rec.tier)
    return dataclasses.replace(
        rec,
        tier=demoted,
        fail_count=0,
        demotions=rec.demotions + (f"{rec.tier}->{demoted}",),
    )
