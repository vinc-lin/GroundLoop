"""render_playbooks — compose selected KnowledgePlaybook items into the PLAN-prompt preamble, one bounded
block per playbook (KB playbook redesign, Task 2 — the render-side migration off the type-grouped
render_knowledge). Only a playbook's own fields (signature/localize/fix/required_apis) reach the prompt
(never raw Skill prose). Empty in -> "" (byte-identical to no injection); shape mirrors
skills/base.render_skills so it concatenates after a skill preamble."""
from __future__ import annotations

from groundloop.kb.knowledge import KnowledgePlaybook


def _line(label: str, val) -> str:
    # collapse whitespace (and tuples/lists join to "; ") so a multi-line field cannot smuggle a stray
    # markdown header (## / #) into the preamble the renderer is meant to control — each field stays one line.
    if isinstance(val, (list, tuple)):
        val = "; ".join(val)
    return f"{label}: {' '.join(str(val).split())}"


def render_playbooks(items: list[KnowledgePlaybook]) -> str:
    if not items:
        return ""
    blocks: list[str] = []
    for k in items:
        blocks.append("\n".join([f"# Crash playbook: {k.id}", _line("Signature", k.signature),
                                 _line("Look at", k.localize), _line("Fix", k.fix),
                                 _line("APIs", k.required_apis)]))
    return "\n\n# Grounded playbooks\n" + "\n\n".join(blocks)
