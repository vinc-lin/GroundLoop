"""MockSkillRegistry — the SP3 KB adapter. `select` = predicate filter (hermetic, deterministic default)
+ an OPTIONAL bge-m3 rerank over guidance (gated: pass an embedder). "Mock" = the wiring; the seed content
is real. Real Skills swap in by replacing the data file / passing a different loader (docs/skill-kb-
migration.md). Reads ONLY its seed data + the loop-visible SkillCtx — never _oracle/."""
from __future__ import annotations

import math
import tomllib
from pathlib import Path

from groundloop.skills.base import Skill
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate

SEED_PATH = str(Path(__file__).parent / "data" / "aaos_playbooks.toml")


def load_skills(path: str) -> list[Skill]:
    raw = tomllib.loads(Path(path).read_text())
    out: list[Skill] = []
    for e in raw.get("skill", []):
        out.append(Skill(
            id=e["id"],
            applies_to=compile_predicate(e.get("match", {})),
            guidance=e["guidance"].strip(),
            hint_apis=tuple(e.get("hint_apis", ())),
            signals=tuple(e.get("signals", ())),
            provenance=e.get("provenance", ""),
        ))
    return out


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class MockSkillRegistry:
    def __init__(self, skills: list[Skill], *, embedder=None, top_k: int = 3):
        self.skills = list(skills)
        self.embedder = embedder
        self.top_k = top_k
        # embed guidance ONCE (pinned bge-m3; query==index) — only when a live/stub embedder is attached
        self._gvecs = self.embedder.embed([s.guidance for s in self.skills]) if self.embedder else None

    @classmethod
    def load(cls, path: str = SEED_PATH, *, embedder=None, top_k: int = 3) -> "MockSkillRegistry":
        return cls(load_skills(path), embedder=embedder, top_k=top_k)

    def select(self, ctx: SkillCtx) -> list[Skill]:
        hits = [(i, s) for i, s in enumerate(self.skills) if s.applies_to(ctx)]   # predicate stage
        if self.embedder is None or not hits:
            return [s for _, s in hits]                                            # hermetic default
        qvec = self.embedder.embed([ctx.text or " ".join(ctx.tokens())])[0]        # bge-m3 rerank (gated)
        scored = sorted(hits, key=lambda p: (-_cos(qvec, self._gvecs[p[0]]), self.skills[p[0]].id))
        return [s for _, s in scored[: self.top_k]]
