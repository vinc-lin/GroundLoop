from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.engines.atlas.store import Store


class AtlasIndex:
    """CodeIndex backed by a real atlas.db. rank_repos = FTS5 unit-membership over the extracted
    signal tokens, grouped by owning repo (the scalable first-stage filter). retrieve = FTS5 file
    hits within a repo. (Semantic vector rerank via the embedder is a gated add-on.)"""

    def __init__(self, db_path: str):
        self.store = Store(db_path)

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        evidence: dict[str, set] = {r.name: set() for r in catalog}
        for tok in signals.tokens():
            # keyword_search -> list[(Unit, rank)]; the Unit carries .repo / .file (store.py:14-23)
            for unit, _rank in self.store.keyword_search(tok, repos=list(allowed), k=20):
                if unit.repo in evidence:
                    evidence[unit.repo].add(tok)
        ranked = [RepoScore(RepoRef(name), float(len(ev)), tuple(sorted(ev)))
                  for name, ev in evidence.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        files: list[str] = []
        for unit, _rank in self.store.keyword_search(query, repos=[repo.name], k=20):
            if unit.file and unit.file not in files:
                files.append(unit.file)
        return files
