"""ClaimRegistry — the claim-path analogue of adapters/skills/mock.MockSkillRegistry. `select(ctx,
tier_floor)` = predicate filter (compiled from each claim's applies_when) + a tier-ladder gate
(TIERS-ranked) + an OPTIONAL bge-m3 rerank over claim.content (gated: pass an embedder). Reads ONLY
its claim store + the loop-visible SkillCtx — never the oracle. Candidate claims are eval-only; the
production floor is `validated` (spec §5.3/§5.6)."""
from __future__ import annotations

import math

from groundloop.kb.claim import CLAIMS_PATH, Claim, load_claims
from groundloop.kb.lifecycle import TIERS
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate


def _cos(a: list[float], b: list[float]) -> float:            # mirrors MockSkillRegistry._cos
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class ClaimRegistry:
    def __init__(self, claims: list[Claim], *, embedder=None, top_k: int = 3):
        self.claims = list(claims)
        self.embedder = embedder
        self.top_k = top_k
        # compile each claim's applies_when ONCE (closed-vocab predicate; bad key/regex -> ValueError)
        self._preds = [compile_predicate(c.applies_when) for c in self.claims]
        # embed content ONCE (pinned bge-m3; query==index) — only when an embedder is attached
        self._cvecs = self.embedder.embed([c.content for c in self.claims]) if self.embedder else None

    @classmethod
    def load(cls, path: str = CLAIMS_PATH, *, embedder=None, top_k: int = 3) -> "ClaimRegistry":
        # load_claims returns a dict keyed by claim id (Phase A); the registry iterates over its values.
        return cls(list(load_claims(path).values()), embedder=embedder, top_k=top_k)

    def select(self, ctx: SkillCtx, tier_floor: str) -> list[Claim]:
        floor = TIERS.index(tier_floor)                       # ValueError if caller passes a non-TIER
        hits = [(i, c) for i, c in enumerate(self.claims)
                if c.tier in TIERS and TIERS.index(c.tier) >= floor and self._preds[i](ctx)]
        if self.embedder is None or not hits:
            return [c for _, c in hits]                        # hermetic default (predicate + tier only)
        qvec = self.embedder.embed([ctx.text or " ".join(ctx.tokens())])[0]   # bge-m3 rerank (gated)
        scored = sorted(hits, key=lambda p: (-_cos(qvec, self._cvecs[p[0]]), self.claims[p[0]].id))
        return [c for _, c in scored[: self.top_k]]
