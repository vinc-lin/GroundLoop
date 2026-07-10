"""FunctionalTextIndex: rank repos by bge-m3 cosine between the ticket prose query and each repo's
text profile (max cosine per repo). A CodeIndex (rank_repos + retrieve) swapped at the composition
root. The optional log-FTS RRF channel is added in Phase 3. rank_repos in atlas.py is untouched."""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import prose_query
from groundloop.engines.atlas.store import Store

_LOG_WEIGHT = 0.15     # optional log evidence is supporting, not primary (calibration seed)


class FunctionalTextIndex:
    def __init__(self, profile_db: str, embedder, atlas_db: str | None = None):
        self.profile = Store(profile_db)
        self.embedder = embedder
        self._atlas = AtlasIndex(atlas_db) if atlas_db else None   # code atlas: log channel (Phase 3) + retrieve

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        best: dict[str, float] = {name: 0.0 for name in allowed}
        q = prose_query(signals)
        if q.strip():
            qvec = self.embedder.embed([q])[0]
            for unit, cos in self.profile.vector_search(qvec, k=50, repos=list(allowed)):
                if unit.repo in best:
                    best[unit.repo] = max(best[unit.repo], cos)

        # optional log-FTS channel: rank-decayed bonus, UNIONs a prose-missed owner in
        log_signals = replace(signals, symbols=())          # drop the reserved prose slot
        if self._atlas is not None and log_signals.tokens():
            fts = self._atlas.rank_repos(log_signals, catalog)
            for i, x in enumerate(r for r in fts if r.score > 0):
                if x.repo.name in best:
                    best[x.repo.name] += _LOG_WEIGHT / (1 + i)

        ranked = [RepoScore(RepoRef(name), float(score)) for name, score in best.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        # localization uses the code atlas (the text-profile store has no source files)
        return self._atlas.retrieve(repo, query) if self._atlas else []
