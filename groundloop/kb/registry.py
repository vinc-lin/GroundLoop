"""PlaybookRegistry — the knowledge-path analogue of adapters/skills/mock.MockSkillRegistry. `select(ctx,
tier_floor)` = predicate filter (compiled from each item's applies_when) + a tier-ladder gate
(TIERS-ranked) + an OPTIONAL bge-m3 rerank over playbook.signature (gated: pass an embedder; KB playbook
redesign Task 5 — was knowledge.content). Reads ONLY its knowledge store + the loop-visible SkillCtx —
never the oracle. Candidate items are eval-only; the production floor is `validated` (spec §5.3/§5.6).
`top_k` defaults to 2 (was 3) to keep the injected preamble bounded. `KnowledgeRegistry` is kept as a
transitional alias so existing importers (cli/__init__.py::_load_knowledge, kb/ab.py, fixeval) need no
change."""
from __future__ import annotations

import math

from groundloop.kb.knowledge import KNOWLEDGE_PATH, Knowledge, load_knowledge
from groundloop.kb.lifecycle import TIERS
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate


def _cos(a: list[float], b: list[float]) -> float:            # mirrors MockSkillRegistry._cos
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class PlaybookRegistry:
    def __init__(self, items: list[Knowledge], *, embedder=None, top_k: int = 2):
        self.items = list(items)
        self.embedder = embedder
        self.top_k = top_k
        # compile each item's applies_when ONCE (closed-vocab predicate; bad key/regex -> ValueError)
        self._preds = [compile_predicate(k.applies_when) for k in self.items]
        # embed signature ONCE (pinned bge-m3; query==index) — only when an embedder is attached
        self._cvecs = self.embedder.embed([k.signature for k in self.items]) if self.embedder else None

    @classmethod
    def load(cls, path: str = KNOWLEDGE_PATH, *, embedder=None, top_k: int = 2) -> "PlaybookRegistry":
        # load_knowledge returns a dict keyed by id (Phase A); the registry iterates over its values.
        return cls(list(load_knowledge(path).values()), embedder=embedder, top_k=top_k)

    def select(self, ctx: SkillCtx, tier_floor: str) -> list[Knowledge]:
        floor = TIERS.index(tier_floor)                       # ValueError if caller passes a non-TIER
        hits = [(i, k) for i, k in enumerate(self.items)
                if k.tier in TIERS and TIERS.index(k.tier) >= floor and self._preds[i](ctx)]
        if self.embedder is None or not hits:
            # BOTH paths are bounded (spec §4: a top-k retriever, not a firehose). The no-embedder
            # fail-safe/offline path takes the first top_k in the existing deterministic (store) order.
            return [k for _, k in hits[: self.top_k]]
        qvec = self.embedder.embed([ctx.text or " ".join(ctx.tokens())])[0]   # bge-m3 rerank (gated)
        scored = sorted(hits, key=lambda p: (-_cos(qvec, self._cvecs[p[0]]), self.items[p[0]].id))
        return [k for _, k in scored[: self.top_k]]


KnowledgeRegistry = PlaybookRegistry          # transitional alias; drop once importers rename
