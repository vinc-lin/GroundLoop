"""FaultRoutingIndex (Android Log Match v2 §7.2): wraps AtlasIndex; fuses the production-known routing
table with the fault-scoped FTS ranking via Reciprocal Rank Fusion, and UNIONs routing candidates so an
owner the base FTS dropped can still surface. A CodeIndex (rank_repos + retrieve) swapped at the
composition root — rank_repos in atlas.py is untouched."""
from __future__ import annotations

from typing import Sequence

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.repo_routing import route_signals

_RRF_K = 60           # standard RRF damping
_ROUTING_WEIGHT = 2.0  # routing is a strong, high-precision prior


class FaultRoutingIndex:
    def __init__(self, db_path: str):
        self.base = AtlasIndex(db_path)

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        fts = self.base.rank_repos(signals, catalog)                       # base fault-scoped FTS
        nonzero = [x for x in fts if x.score > 0]                          # sorted score-desc by AtlasIndex
        fts_rank = {x.repo.name: i for i, x in enumerate(nonzero)}
        routes = [(r, w) for r, w in route_signals(signals) if r in allowed]
        fused: dict[str, float] = {r.name: 0.0 for r in catalog}
        ev: dict[str, list[str]] = {r.name: [] for r in catalog}
        for name, i in fts_rank.items():
            fused[name] += 1.0 / (_RRF_K + i)
            ev[name].append("fts")
        for name, _w in routes:                     # routed hits are equal-weight -> equal (rank-0) bonus;
            fused[name] += _ROUTING_WEIGHT / _RRF_K  # ordinal position is NOT a confidence proxy
            ev[name].append("route")
        ranked = [RepoScore(RepoRef(n), sc, tuple(ev[n])) for n, sc in fused.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self.base.retrieve(repo, query)
