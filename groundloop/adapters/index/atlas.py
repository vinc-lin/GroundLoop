from __future__ import annotations

import math
from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.engines.atlas.store import Store


class AtlasIndex:
    """CodeIndex backed by a real atlas.db. rank_repos = IDF-weighted FTS5 unit-membership over the
    extracted signal tokens, grouped by owning repo (the scalable first-stage filter). retrieve = FTS5
    file hits within a repo. (Semantic vector rerank via the embedder is a gated add-on.)

    Size-normalization: scoring by raw token-hit COUNT over a global top-k crowded small repos out
    (big repos fill the top-k and pick up generic tokens by sheer volume), so recall degraded as the
    fleet grew. Instead each matched token is weighted by IDF = log(N_repos / df), where df is how
    many repos contain it (via `token_repo_hits`, no top-k). A token unique to one repo is maximally
    discriminative; a token every repo has (generic sub-words, boilerplate) contributes ~0 — so a big
    repo can no longer win a case on generic-token volume, only on tokens that actually point to it."""

    def __init__(self, db_path: str):
        self.store = Store(db_path)

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        names = [r.name for r in catalog]
        n_repos = len(names)
        matched: dict[str, set] = {name: set() for name in names}
        df: dict[str, int] = {}
        for tok in dict.fromkeys(signals.tokens()):          # dedup, preserve order
            hits = {h for h in self.store.token_repo_hits(tok, repos=names) if h in matched}
            if not hits:
                continue
            df[tok] = len(hits)
            for h in hits:
                matched[h].add(tok)

        def _idf(tok: str) -> float:
            # log(N/df): 1 repo -> maximally discriminative; all repos -> ~0 (generic, no signal).
            return math.log(n_repos / df[tok]) if n_repos and df.get(tok) else 0.0

        ranked = [RepoScore(RepoRef(name), float(sum(_idf(t) for t in ev)), tuple(sorted(ev)))
                  for name, ev in matched.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        files: list[str] = []
        for unit, _rank in self.store.keyword_search(query, repos=[repo.name], k=20):
            if unit.file and unit.file not in files:
                files.append(unit.file)
        return files
