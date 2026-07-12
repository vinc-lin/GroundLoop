"""A SignalExtractor decorator that records the last Signals the loop computed, so the batch driver can
persist them into the oracle-free run-record (the frozen core.RunRecord drops signals). Pure adapter."""
from __future__ import annotations

from groundloop.core.types import Signals, Ticket


class RecordingExtractor:
    def __init__(self, inner):
        self.inner = inner
        self.last_signals: Signals | None = None

    def extract(self, logs, ticket: Ticket) -> Signals:
        sig = self.inner.extract(logs, ticket)
        self.last_signals = sig
        return sig
