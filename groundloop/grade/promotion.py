"""Reporting-only promotion-eligibility notes over a grade-run card. NEVER edits capabilities.md or flips a
default — it only SAYS when a [production] number clears a capability's bar, so a human can enact it. This is
where the Provisional-Core obligation (e.g. PlanningFixEngine) surfaces for a decision."""
from __future__ import annotations


def _fixer_used(card: dict) -> str:
    fixers = {c.get("fixer", "") for c in card.get("cases", [])}
    return next(iter(fixers)) if len(fixers) == 1 else ""


def promotion_notes(card: dict) -> list[str]:
    notes: list[str] = []
    fix = (card.get("overall", {}).get("fix", {}) or {})
    rr = fix.get("resolved_rate_strict", {}) or {}
    v, n = rr.get("value"), rr.get("n", 0)
    if _fixer_used(card) == "plan" and v is not None and n > 0:
        notes.append(
            f"PROMOTION-ELIGIBLE: PlanningFixEngine (Provisional-Core) resolved_rate={v:.2f} over {n} "
            f"[production] cases — confirm Core in capabilities.md, or revert to --fixer model.")
    return notes
