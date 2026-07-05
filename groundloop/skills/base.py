"""Dev-experience KB primitive — migrated as-is from loop-agent/bfl/skills/base.py, extended with the
spec §3.1 `signals` (retrieval tags) and `provenance` (KB traceability) fields. NOT a core port: this is
an engine-internal Protocol (like engines/atlas/embed.Embedder), swapped at the composition root."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Skill:
    id: str
    applies_to: Callable[[object], bool]   # predicate on a SkillCtx (compiled from declarative data)
    guidance: str                          # the playbook text (real dev experience)
    hint_apis: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()          # retrieval keys / tags (spec §3.1)
    provenance: str = ""                   # source doc/commit, for KB traceability (spec §3.1)


class SkillRegistry(Protocol):
    def select(self, ctx) -> list[Skill]: ...


class NullSkillRegistry:
    """The `skills=none` arm: a true no-op so the fix loop is byte-identical to pre-SP3."""
    def select(self, ctx) -> list[Skill]:
        return []


def render_skills(skills: list[Skill]) -> str:
    if not skills:
        return ""
    blocks = [f"## Skill: {s.id}\n{s.guidance}" for s in skills]
    return "\n\n# Applicable playbooks\n" + "\n\n".join(blocks)
