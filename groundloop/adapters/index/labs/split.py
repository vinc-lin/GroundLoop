"""A CodeIndex composite: rank_repos from the MATCH index, retrieve from the LOCALIZE index. Lets
`gloop run` choose --localize independently of --match-arm (run_ticket uses one index for both). Pure
composition-root adapter — no core edit."""
from __future__ import annotations

from groundloop.core.types import RepoRef, RepoScore, Signals


class SplitIndex:
    def __init__(self, match, localize):
        self._match = match
        self._localize = localize

    def rank_repos(self, signals: Signals, catalog) -> list[RepoScore]:
        # Propagate signals to a localize side that keys candidate-gen on them (e.g. RerankLocalizeIndex):
        # run_ticket calls rank_repos then retrieve on this SplitIndex, so without this the localize
        # stash never fires and retrieve falls back to the prose query. No-op for plain retrievers.
        note = getattr(self._localize, "note_signals", None)
        if callable(note):
            note(signals)
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self._localize.retrieve(repo, query)
