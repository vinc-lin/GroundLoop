"""Per-claim placebo control for the claim-attribution retain-loop (design spec §5.4). The Claim-granular
analogue of kb/placebo.build_placebo: one placebo Claim per candidate — SAME applies_when + type (so it
fires on the identical cases at the same tier floor), id prefixed 'placebo-', EMPTY grounding_refs, and a
length-matched, deliberately IRRELEVANT content. It is the null arm of the per-claim LOFO-confirm: any lift
a real claim shows over its placebo isolates the claim's CONTENT as the treatment, ruling out the confound
of merely injecting some claim on those cases. The filler is owner-token-free (leak-safe by construction)."""
from __future__ import annotations

from groundloop.kb.claim import Claim

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


def build_claim_placebo(claims: dict[str, Claim]) -> dict[str, Claim]:
    """Return {placebo_id: placebo Claim}, one per input claim. Each placebo copies applies_when + type
    VERBATIM (fires on the identical cases at the same tier floor) under id='placebo-'+<id>, but carries
    empty grounding_refs and length-matched irrelevant content. Mirrors kb/placebo.build_placebo."""
    out: dict[str, Claim] = {}
    for cid, c in claims.items():
        pid = "placebo-" + cid
        out[pid] = Claim(
            id=pid,
            applies_when=dict(c.applies_when or {}),          # verbatim predicate -> same firing set
            type=c.type,                                      # same advice slot (render groups it identically)
            content=_matched_filler(c.content or ""),
            grounding_refs=(),                                # cites nothing
            provenance=f"placebo control paired to claim {cid} (length-matched, irrelevant content)",
            tier=c.tier,                                      # injectable wherever the source claim is
            evidence={},
        )
    return out
