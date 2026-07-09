"""Phase-1 bridge: FaultRecord -> a TIGHT Signals of only fault-site tokens, fed to the UNCHANGED
AtlasIndex.rank_repos. Implements the Arm.extractor interface (.extract(logs, ticket) -> Signals)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket
from groundloop.domains.android_ivi.fault_extract import FaultRecord, _is_framework, extract_fault_record
from groundloop.domains.android_ivi.logcat_parse import parse_logcat


def fault_record_for_logs(logs: Sequence[LogAttachment]) -> FaultRecord | None:
    """Parse all log attachments and extract the single fault record (or None)."""
    text = "\n".join(a.content for a in logs)
    return extract_fault_record(parse_logcat(text))


def _dedup(xs):
    seen: dict[str, None] = {}
    for x in xs:
        if x:
            seen.setdefault(x, None)
    return tuple(seen)


def signals_from_fault(fr: FaultRecord | None) -> Signals:
    if fr is None:
        return Signals()
    owner_frames = [f for f in fr.frames if not _is_framework(f)]
    if fr.top_frame is not None and fr.top_frame not in owner_frames:
        owner_frames = [fr.top_frame] + owner_frames
    packages = _dedup(f.package for f in owner_frames)
    classes = _dedup(f.klass for f in owner_frames)
    methods = _dedup(f.method for f in owner_frames)
    symbols = _dedup(f.symbol for f in owner_frames if f.symbol)
    libraries = _dedup(f.soname for f in owner_frames if f.soname)
    errors = _dedup([fr.exception.rsplit(".", 1)[-1]] if fr.exception else [])
    return Signals(packages=packages, classes=classes, methods=methods,
                   symbols=symbols, libraries=libraries, errors=errors)


class FaultSignalExtractor:
    """Domain extractor for the `faultslice`/`routing` arms."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        return signals_from_fault(fault_record_for_logs(logs))
