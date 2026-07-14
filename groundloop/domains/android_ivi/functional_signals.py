"""Functional (no-crash) matching: pack ticket summary+description prose into the frozen Signals
seam so a text-similarity index can rank repos when there is no fault frame. Prose rides as the
single reserved element Signals.symbols[0], prefixed with PROSE_MARK so a dispatcher can tell a
prose query from crash symbols. Optional log tokens (audio/connection) ride in the other fields."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket
from groundloop.domains.android_ivi.fault_signals import fault_record_for_logs, signals_from_fault
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor

PROSE_MARK = "\x00fn\x00"      # reserves symbols[0] as a prose query (crash symbols never start with it)


def normalize_prose(ticket: Ticket) -> str:
    return " ".join((ticket.summary + " " + ticket.description).lower().split())


def prose_query(signals: Signals) -> str:
    """Recover the prose query from a functional Signals (strips PROSE_MARK). '' if none."""
    if signals.symbols and signals.symbols[0].startswith(PROSE_MARK):
        return signals.symbols[0][len(PROSE_MARK):]
    return ""


def is_functional_localize(signals: Signals) -> bool:
    """Localize-side discriminator: True iff localize should use the semantic (bge-m3) retriever
    instead of FTS5-over-symbols — the ticket is prose-marked (DispatchExtractor) OR carries no
    code anchor at all. MATCH-ARM-INDEPENDENT: unlike DispatchIndex._is_functional (PROSE_MARK
    only, correct only under the dispatch match arm), this also fires under the Core component/flood
    extractors, where a no-crash ticket yields anchorless Signals. No anchor => no symbol token to
    feed FTS5 => use the vector retriever. `errors` (generic exception names) are NOT anchors."""
    if signals.symbols and signals.symbols[0].startswith(PROSE_MARK):
        return True
    return not (signals.classes or signals.methods or signals.symbols
                or signals.libraries or signals.packages)


def pack_prose(ticket: Ticket, logs: Sequence[LogAttachment]) -> Signals:
    prose = normalize_prose(ticket)
    # optional log evidence only (empty description so ticket prose is NOT double-counted here)
    inner = AndroidSignalExtractor().extract(logs, Ticket(id=ticket.id, summary="", description=""))
    return Signals(symbols=(PROSE_MARK + prose,),
                   packages=inner.packages, classes=inner.classes, methods=inner.methods,
                   libraries=inner.libraries, errors=inner.errors)   # drop inner.symbols (reserved)


class FunctionalTextExtractor:
    """SignalExtractor for the `functional` arm — prose query + optional log tokens."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        return pack_prose(ticket, logs)


class DispatchExtractor:
    """Route discriminator carried in Signals: a crash ANCHOR -> fault Signals (no prose mark);
    no anchor -> prose Signals (symbols[0] starts with PROSE_MARK). Lets a Signals-only index route."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        fr = fault_record_for_logs(logs)
        if fr is not None:
            return signals_from_fault(fr)
        return pack_prose(ticket, logs)
