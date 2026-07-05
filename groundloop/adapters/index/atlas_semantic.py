"""CodeIndex backed by bge-m3 vector similarity over atlas.db (the +semantic arm).

rank_repos = max cosine per repo over store.vector_search hits, restricted to the catalog.
A construction-time guard verifies the query embedder's dim matches the indexed vectors, so a
model/dim mismatch fails loudly instead of silently scoring every repo -1 (docs §6.3 reuse contract).
Network-bound (GatewayEmbedder) -> Type-2/live."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.engines.atlas.store import Store


class SemanticAtlasIndex:
    def __init__(self, db_path: str, embedder):
        self.store = Store(db_path)
        self.embedder = embedder
        self._check_dim()

    def _check_dim(self) -> None:
        """Reuse contract: the query embedder must produce the same dim as the indexed vectors."""
        import json
        row = self.store.db.execute("SELECT vec FROM vectors LIMIT 1").fetchone()
        if row is None:
            return                       # empty atlas — nothing to compare (build-time only)
        indexed_dim = len(json.loads(row["vec"]))
        query_dim = len(self.embedder.embed(["dim probe"])[0])
        if query_dim != indexed_dim:
            raise ValueError(
                f"embedder dim {query_dim} != indexed vector dim {indexed_dim} "
                f"(query embed model must equal the index-time bge-m3 — reuse contract)")

    def _query(self, signals: Signals) -> str:
        return " ".join(signals.tokens())

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        best: dict[str, float] = {name: 0.0 for name in allowed}
        q = self._query(signals)
        if q.strip():
            qvec = self.embedder.embed([q])[0]
            for unit, cos in self.store.vector_search(qvec, k=50, repos=list(allowed)):
                if unit.repo in best:
                    best[unit.repo] = max(best[unit.repo], cos)
        ranked = [RepoScore(RepoRef(name), float(score)) for name, score in best.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        qvec = self.embedder.embed([query])[0]
        files: list[str] = []
        for unit, _ in self.store.vector_search(qvec, k=20, repos=[repo.name]):
            if unit.file and unit.file not in files:
                files.append(unit.file)
        return files
