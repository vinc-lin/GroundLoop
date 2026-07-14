"""SignalQueryIndex: a composition-root CodeIndex that keeps rank_repos on the match index (stashing
the signals) and rewrites the localize query to the extracted CODE tokens (code_query) — the validated
file@1 lever: a crash stack / logcat naming the fault class → FTS5 exact-matches it. Falls back to the
passed prose query when no code tokens exist. No semantic branch, no embedder: the 2026-07-14 [proxy]
A/B showed bge-m3 on prose is neutral-to-negative at file@1 while tokens-in-FTS5 lifted functional
file@1 0.010->0.161. run/batch.py runs cases sequentially so the stash is race-free; note_signals()
seeds it for out-of-loop callers (grade-run's isolated diagnostic). No core/ or schema edit."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import code_query


class SignalQueryIndex:
    def __init__(self, match, fts_localize):
        self._match = match
        self._fts = fts_localize
        self._last_signals: Signals | None = None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        q = code_query(self._last_signals) if self._last_signals is not None else ""
        return self._fts.retrieve(repo, q or query)

    def note_signals(self, signals: Signals) -> None:
        self._last_signals = signals
