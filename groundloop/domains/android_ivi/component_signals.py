"""Carry the JIRA component through the frozen Signals seam for the component-prior re-ranker. The
component rides as a reserved COMPONENT_MARK token in Signals.errors; ComponentPriorIndex reads it
(component_of) and strips it (strip_component) before the base index sees the query."""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket

COMPONENT_MARK = "\x00comp\x00"


def component_of(signals: Signals) -> str:
    for e in signals.errors:
        if e.startswith(COMPONENT_MARK):
            return e[len(COMPONENT_MARK):]
    return ""


def strip_component(signals: Signals) -> Signals:
    return replace(signals, errors=tuple(e for e in signals.errors if not e.startswith(COMPONENT_MARK)))


class ComponentExtractor:
    """Wraps a base SignalExtractor; appends the ticket's JIRA component as a reserved marker token."""

    def __init__(self, base):
        self.base = base

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        sig = self.base.extract(logs, ticket)
        comp = (ticket.component or "").strip()
        if not comp:
            return sig
        return replace(sig, errors=sig.errors + (COMPONENT_MARK + comp,))
