"""Signal-ablation extractor: text-only drops the failure logs (docs/type2-evaluation.md §6.2)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor


class TextOnlyExtractor:
    """SignalExtractor that ignores logs — extracts from ticket summary/description only."""

    def __init__(self) -> None:
        self._inner = AndroidSignalExtractor()

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        return self._inner.extract((), ticket)     # drop logs
