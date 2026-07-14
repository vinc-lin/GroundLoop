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


def is_functional_localize(signals) -> bool:
    """Localize-side discriminator: True (=> semantic/bge-m3 retriever) iff the ticket is prose-marked
    OR carries NO crash-frame evidence. Crash evidence = a parsed Java stack frame (signals.methods —
    populated ONLY by the `at pkg.Class.method(` frame regex) or a native backtrace frame (a non-PROSE
    signals.symbols entry). A functional ticket's logcat can mention FQ class names (fills
    classes/packages) yet have NO stack frame → routes to semantic. MATCH-ARM-INDEPENDENT. Keys on
    stack-frame evidence, NOT anchor-emptiness: the old no-anchor test made this a no-op in production,
    where functional tickets carry logcat class mentions (RCA 2026-07-14). Residual: a lone non-crash
    `at X.Y(` handler line misroutes to FTS5 — upgrade to a fault_record marker if production shows it."""
    if signals.symbols and signals.symbols[0].startswith(PROSE_MARK):
        return True
    real_symbols = tuple(s for s in signals.symbols if not s.startswith(PROSE_MARK))
    return not (signals.methods or real_symbols)


def code_query(signals) -> str:
    """FTS5 localize query built from the extracted CODE tokens (classes/methods/packages/symbols/
    libraries), dropping the reserved PROSE_MARK / COMPONENT_MARK marker tokens. '' if none. The crash
    localize branch uses this instead of the prose summary (which has no code tokens to match symbols)."""
    from groundloop.domains.android_ivi.component_signals import COMPONENT_MARK
    reserved = (PROSE_MARK, COMPONENT_MARK)
    seen: dict[str, None] = {}
    for group in (signals.classes, signals.methods, signals.packages, signals.symbols, signals.libraries):
        for t in group:
            if t and not t.startswith(reserved):
                seen.setdefault(t, None)
    return " ".join(seen)


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
