"""Composition-root FixEngine decorator: consult validated playbooks and inject them into the fixer's
prompt. run_ticket (frozen) passes only (worktree, ticket, locations); we read the per-ticket signals from
the shared RecordingExtractor and build the selection ctx. Fail-safe: no signals / empty selection / a
fixer without with_preamble -> the inner fixer runs unchanged."""
from __future__ import annotations

from groundloop.kb.render import render_playbooks
from groundloop.skills.ctx import build_ctx


class KnowledgeInjectingFixEngine:
    def __init__(self, inner, *, registry, extractor_rec, tier_floor: str = "validated"):
        self.inner = inner
        self.registry = registry
        self.extractor_rec = extractor_rec
        self.tier_floor = tier_floor
        self.model = getattr(inner, "model", None)

    def with_preamble(self, preamble):
        return self.inner.with_preamble(preamble)

    def propose(self, worktree, ticket, locations):
        signals = getattr(self.extractor_rec, "last_signals", None)
        preamble = ""
        if signals is not None and hasattr(self.inner, "with_preamble"):
            ctx = build_ctx(signals, ticket, worktree.repo.name)
            preamble = render_playbooks(self.registry.select(ctx, self.tier_floor))
        fixer = self.inner.with_preamble(preamble) if preamble else self.inner
        return fixer.propose(worktree, ticket, locations)
