"""ComponentPriorIndex: additive JIRA-component->repo prior on top of any base CodeIndex. Reads the
component from the reserved Signals marker, strips it before the base (so the component string never
enters the base FTS/cosine query and can't be double-counted), and boosts base scores by the affinity
weight. A CodeIndex swapped at the composition root; loop-blind — reads only the component + the
affinity object it was given (the LOO exclusion lives in an eval-side affinity view, not here)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.component_signals import component_of, strip_component

_COMPONENT_WEIGHT = 1.0    # calibration seed; prior should dominate ranking (recall@3=0.90). Frozen on prod.


class ComponentPriorIndex:
    def __init__(self, base_index, affinity, *, weight: float = _COMPONENT_WEIGHT):
        self.base = base_index
        self.affinity = affinity                 # any object exposing .affinity(component) -> {repo: weight}
        self.weight = weight

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        comp = component_of(signals)
        ranked = self.base.rank_repos(strip_component(signals), catalog)
        boost = self.affinity.affinity(comp) if comp else {}
        allowed = {r.name for r in catalog}
        out = [RepoScore(rs.repo, rs.score + self.weight * boost.get(rs.repo.name, 0.0), rs.evidence)
               for rs in ranked if rs.repo.name in allowed]
        out.sort(key=lambda s: s.score, reverse=True)
        return out

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self.base.retrieve(repo, query)
