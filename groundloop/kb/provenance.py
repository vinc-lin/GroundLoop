"""Per-entry provenance sidecar for the KB lifecycle (tiering / auto-demotion).

Records the traceability every KB Skill needs to be auto-demotable: source `lineage`, the
split-tagged `validating_case_ids`, the (proxy) `measured_lift`, and the `evidence_context`
(atlas SHA + `bge-m3` + model pin + date) a lift was measured against. Stored OUT-OF-BAND from the
corpus TOML as JSON (`groundloop/kb/data/provenance.json`) so authoring the leak-safe *content*
stays separate from the mutable lifecycle *bookkeeping* — the TOML is human-authored + regression
checked (`groundloop/kb/validate.py`), this sidecar is machine-updated by the lifecycle.

GATING: Phase B (this sidecar + `lifecycle.py`) is gated on a positive
Phase-A `accept()` (`groundloop/kb/accept.strengthened_accept(...) -> {"accepted": True, ...}`): the
KB arm must first show a two-sided A/B lift over the placebo control before we invest in tiering the
corpus that produced it. This module ships the frozen record + JSON I/O only; tier transitions live
in `groundloop/kb/lifecycle.py` (Task B2).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SIDECAR_PATH = str(Path(__file__).parent / "data" / "provenance.json")

# JSON has no tuple type — these fields serialize as lists and must be re-tupled on load so that
# frozen-dataclass equality (used by the round-trip test + by lifecycle diffing) holds.
_TUPLE_FIELDS = ("validating_case_ids", "demotions")


@dataclass(frozen=True)
class ProvenanceRecord:
    id: str
    tier: str
    lineage: str
    validating_case_ids: tuple[str, ...]
    measured_lift: dict
    evidence_context: dict
    fail_count: int = 0
    demotions: tuple[str, ...] = ()
    leak_check: str = ""


def _to_record(sid: str, raw: dict) -> ProvenanceRecord:
    """Build a record from a raw JSON row: drop unknown keys, default missing optionals, re-tuple."""
    known = {f.name for f in fields(ProvenanceRecord)}
    kw = {k: v for k, v in raw.items() if k in known}
    kw.setdefault("id", sid)  # id is the dict key; tolerate its absence in the body
    for tf in _TUPLE_FIELDS:
        if kw.get(tf) is not None and not isinstance(kw[tf], tuple):
            kw[tf] = tuple(kw[tf])
    return ProvenanceRecord(**kw)


def load_sidecar(path: str = SIDECAR_PATH) -> dict[str, ProvenanceRecord]:
    """Load the sidecar; a missing file is an empty sidecar (no records yet), not an error."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {sid: _to_record(sid, row) for sid, row in raw.items()}


def save_sidecar(path: str, records: dict[str, ProvenanceRecord]) -> None:
    """Write the sidecar as deterministic (sorted-key, indented) JSON, keyed by the passed keys."""
    out = {sid: asdict(rec) for sid, rec in records.items()}
    Path(path).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
