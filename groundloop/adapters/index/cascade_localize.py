from __future__ import annotations

from typing import Optional, Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.anchors import extract_anchor_candidates, rare_anchors
from groundloop.domains.android_ivi.functional_signals import code_query
from groundloop.engines.atlas.retrieve import rrf_fuse


def _default_anchors(text, store, repo):
    return rare_anchors(extract_anchor_candidates(text), store, repo)


class CascadeLocalizeIndex:
    """Recall-first localize: RRF-union of crash code-tokens (FTS), literal anchors (FTS), and an optional
    bge-m3 semantic fallback. Non-regressive: falls back to the FTS floor when no tier fires. Stash pattern
    (signal_query.py); no core/ or schema edit; opt-in Candidate."""

    def __init__(self, match, *, fts, semantic=None, store, anchors_fn=_default_anchors, k: int = 20):
        self._match = match
        self._fts = fts
        self._semantic = semantic
        self._store = store
        self._anchors_fn = anchors_fn
        self.k = k
        self._last_signals: Optional[Signals] = None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def note_signals(self, signals: Signals) -> None:
        self._last_signals = signals

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        lists: list[list[str]] = []
        cq = code_query(self._last_signals) if self._last_signals is not None else ""
        if cq:
            lists.append(self._fts.retrieve(repo, cq))
        for a in self._anchors_fn(query, self._store, repo.name):
            lists.append(self._fts.retrieve(repo, a))
        if self._semantic is not None:
            lists.append(self._semantic.retrieve(repo, query))
        lists = [x for x in lists if x]
        if not lists:
            return self._fts.retrieve(repo, query)
        return [f for f, _ in rrf_fuse(lists)][: self.k]
