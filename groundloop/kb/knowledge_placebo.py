"""Per-item placebo control for the knowledge-attribution retain-loop (design spec §5.4; retargeted to
playbooks in the KB playbook redesign, Task 7). The Knowledge-granular analogue of
kb/placebo.build_placebo: one placebo KnowledgePlaybook per candidate — SAME applies_when (so it fires on
the identical cases at the same tier floor), id prefixed 'placebo-', EMPTY grounding_refs/required_apis,
and length-matched, deliberately IRRELEVANT signature/fix(/localize) text. It is the null arm of the
per-item LOFO-confirm: any lift a real item shows over its placebo isolates the item's PLAYBOOK CONTENT
(what render_playbooks actually puts in the prompt) as the treatment, ruling out the confound of merely
injecting some item on those cases. The filler is owner-token-free (leak-safe by construction)."""
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
    """Return {placebo_id: placebo KnowledgePlaybook}, one per input item. Each placebo copies
    applies_when VERBATIM (fires on the identical cases at the same tier floor) under id='placebo-'+<id>,
    but carries empty grounding_refs/required_apis and length-matched irrelevant signature/fix(/localize)
    text. Mirrors kb/placebo.build_placebo."""
    out: dict[str, Knowledge] = {}
    for kid, k in items.items():
        pid = "placebo-" + kid
        sig_ref = k.signature or ""
        fix_ref = " ".join(k.fix) if k.fix else ""
        out[pid] = Knowledge(
            id=pid,
            applies_when=dict(k.applies_when or {}),           # verbatim predicate -> same firing set
            signature=_matched_filler(sig_ref),
            localize=(_matched_filler(" ".join(k.localize)),) if k.localize else (),
            fix=(_matched_filler(fix_ref),),
            required_apis=(),                                  # asserts no checkable API
            grounding_refs=(),                                 # cites nothing
            provenance=f"placebo control paired to knowledge {kid} (length-matched, irrelevant content)",
            tier=k.tier,                                       # injectable wherever the source item is
            evidence={},
        )
    return out
