"""Per-item placebo control for the knowledge-attribution retain-loop (design spec §5.4). The
Knowledge-granular analogue of kb/placebo.build_placebo: one placebo Knowledge item per candidate — SAME
applies_when + type (so it fires on the identical cases at the same tier floor), id prefixed 'placebo-',
EMPTY grounding_refs, and a length-matched, deliberately IRRELEVANT content. It is the null arm of the
per-item LOFO-confirm: any lift a real item shows over its placebo isolates the item's CONTENT as the
treatment, ruling out the confound of merely injecting some item on those cases. The filler is
owner-token-free (leak-safe by construction)."""
from __future__ import annotations

from groundloop.kb.knowledge import Knowledge

# Neutral, owner-token-free filler (mirrors kb/placebo._FILLER; verified leak-safe vs FLEET_OWNER_TOKENS in
# the C1 test). Trimmed to the reference content length so treatment and control differ ONLY in wording.
_FILLER = (
    "placebo control text of matched length that conveys no diagnostic or corrective information and "
    "points at nothing in particular so the treatment and control differ solely in the wording injected "
)


def _matched_filler(reference: str, *, floor: int = 40) -> str:
    """Owner-token-free filler cut to EXACTLY max(len(reference), floor) characters."""
    n = max(len(reference), floor)
    reps = (n // len(_FILLER)) + 1
    return (_FILLER * reps)[:n]


def build_knowledge_placebo(items: dict[str, Knowledge]) -> dict[str, Knowledge]:
    """Return {placebo_id: placebo Knowledge}, one per input item. Each placebo copies applies_when + type
    VERBATIM (fires on the identical cases at the same tier floor) under id='placebo-'+<id>, but carries
    empty grounding_refs and length-matched irrelevant content. Mirrors kb/placebo.build_placebo."""
    out: dict[str, Knowledge] = {}
    for kid, k in items.items():
        pid = "placebo-" + kid
        out[pid] = Knowledge(
            id=pid,
            applies_when=dict(k.applies_when or {}),           # verbatim predicate -> same firing set
            type=k.type,                                       # same advice slot (render groups it identically)
            content=_matched_filler(k.content or ""),
            grounding_refs=(),                                 # cites nothing
            provenance=f"placebo control paired to knowledge {kid} (length-matched, irrelevant content)",
            tier=k.tier,                                       # injectable wherever the source item is
            evidence={},
        )
    return out
