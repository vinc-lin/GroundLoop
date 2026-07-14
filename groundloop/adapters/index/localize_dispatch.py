"""LocalizeDispatchIndex: a composition-root CodeIndex that keeps rank_repos on the match index but
routes localize (retrieve) by the LAST-seen Signals — prose-only / no-anchor tickets to a semantic
(bge-m3) retriever, crash / anchored tickets to the FTS5 retriever. run_ticket calls rank_repos then
retrieve back-to-back per ticket and run/batch.py runs cases sequentially, so stashing the Signals in
rank_repos is race-free. note_signals() seeds the Signals for out-of-loop callers (grade-run's
isolated-localize diagnostic) that call retrieve without a preceding rank_repos. No core/ or schema
edit; the crash path delegates unchanged to the injected FTS5 retriever (byte-identical when wired
to AtlasIndex)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import is_functional_localize


class LocalizeDispatchIndex:
    def __init__(self, match, crash_localize, functional_localize):
        self._match = match
        self._crash = crash_localize
        self._functional = functional_localize
        self._last_signals: Signals | None = None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        sig = self._last_signals
        if sig is not None and is_functional_localize(sig):
            return self._functional.retrieve(repo, query)
        return self._crash.retrieve(repo, query)

    def note_signals(self, signals: Signals) -> None:
        self._last_signals = signals
