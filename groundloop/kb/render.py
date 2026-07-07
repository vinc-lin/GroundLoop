"""render_claims — compose selected Claims into the PLAN-prompt preamble, grouped by advice type.
The claim-path replacement for skills/base.render_skills (spec §6): only a claim's `content` reaches
the prompt (never raw Skill prose). Empty in -> "" (byte-identical to no injection); shape mirrors
render_skills so it concatenates after a skill preamble."""
from __future__ import annotations

from groundloop.kb.claim import Claim

# Fixed render order + human header per advice type (spec §5.3: "known localize hints / fix steps /
# required APIs for this crash class"). Types outside this closed set are dropped (defensive).
_TYPE_HEADS: tuple[tuple[str, str], ...] = (
    ("localize_hint", "Known localize hints for this crash class"),
    ("fix_step", "Known fix steps for this crash class"),
    ("api_requirement", "Required APIs for this crash class"),
)


def render_claims(claims: list[Claim]) -> str:
    if not claims:
        return ""
    blocks: list[str] = []
    for type_key, head in _TYPE_HEADS:
        items = [c for c in claims if c.type == type_key]     # preserves selection order within a group
        if not items:
            continue
        # collapse whitespace so a multi-line content cannot smuggle a stray markdown header (## / #)
        # into the preamble the renderer is meant to control — each claim stays a single bullet line.
        lines = "\n".join(f"- {' '.join(c.content.split())}" for c in items)
        blocks.append(f"## {head}\n{lines}")
    if not blocks:                                            # only off-taxonomy claims -> no injection
        return ""
    return "\n\n# Grounded claims\n" + "\n\n".join(blocks)
