"""FunctionalTextIndex: rank repos by bge-m3 cosine between the ticket prose query and each repo's
text profile (max cosine per repo). A CodeIndex (rank_repos + retrieve) swapped at the composition
root. The optional log-FTS RRF channel is added in Phase 3. rank_repos in atlas.py is untouched."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import prose_query
from groundloop.engines.atlas.store import Store


class FunctionalTextIndex:
    def __init__(self, profile_db: str, embedder, atlas_db: str | None = None):
        self.profile = Store(profile_db)
        self.embedder = embedder
        self.atlas_db = atlas_db          # optional log-FTS channel (Phase 3)

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        best: dict[str, float] = {name: 0.0 for name in allowed}
        q = prose_query(signals)
        if q.strip():
            qvec = self.embedder.embed([q])[0]
            for unit, cos in self.profile.vector_search(qvec, k=50, repos=list(allowed)):
                if unit.repo in best:
                    best[unit.repo] = max(best[unit.repo], cos)
        ranked = [RepoScore(RepoRef(name), float(score)) for name, score in best.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        qvec = self.embedder.embed([query])[0]
        files: list[str] = []
        for unit, _ in self.profile.vector_search(qvec, k=20, repos=[repo.name]):
            if unit.file and unit.file not in files:
                files.append(unit.file)
        return files
