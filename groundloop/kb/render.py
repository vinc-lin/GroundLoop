"""render_knowledge — compose selected Knowledge items into the PLAN-prompt preamble, grouped by advice
type. The knowledge-path replacement for skills/base.render_skills (spec §6): only an item's `content`
reaches the prompt (never raw Skill prose). Empty in -> "" (byte-identical to no injection); shape mirrors
render_skills so it concatenates after a skill preamble."""
from __future__ import annotations

from groundloop.kb.knowledge import Knowledge

# Fixed render order + human header per advice type (spec §5.3: "known localize hints / fix steps /
# required APIs for this crash class"). Types outside this closed set are dropped (defensive).
_TYPE_HEADS: tuple[tuple[str, str], ...] = (
    ("localize_hint", "Known localize hints for this crash class"),
    ("fix_step", "Known fix steps for this crash class"),
    ("api_requirement", "Required APIs for this crash class"),
)


def render_knowledge(items: list[Knowledge]) -> str:
    if not items:
        return ""
    blocks: list[str] = []
    for type_key, head in _TYPE_HEADS:
        group = [k for k in items if k.type == type_key]      # preserves selection order within a group
        if not group:
            continue
        # collapse whitespace so a multi-line content cannot smuggle a stray markdown header (## / #)
        # into the preamble the renderer is meant to control — each item stays a single bullet line.
        lines = "\n".join(f"- {' '.join(k.content.split())}" for k in group)
        blocks.append(f"## {head}\n{lines}")
    if not blocks:                                            # only off-taxonomy items -> no injection
        return ""
    return "\n\n# Grounded knowledge\n" + "\n\n".join(blocks)
