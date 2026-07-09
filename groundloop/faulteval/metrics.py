"""Offline fault-localization grading (Android Log Match v2 §8). The ONLY oracle reader on this path;
never called in the loop."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FaultLocRecord:
    case_id: str
    top_frame_key: str | None
    blamed_keys: list[str] = field(default_factory=list)
    fault_file_hint: str | None = None
    confidence: str = "NONE"


def _wrap(k: int, n: int) -> dict:
    return {"value": (k / n if n else 0.0), "k": k, "n": n}


def grade_fault_localization(records, *, oracle_by_case, k: int = 5) -> dict:
    n = len(records)
    f1 = fk = fl = nofault = 0
    for rec in records:
        o = oracle_by_case[rec.case_id]
        want_frame, want_file = o["fault_frame"], o.get("fault_file")
        if rec.confidence == "NONE" or rec.top_frame_key is None:
            nofault += 1
            continue
        if rec.top_frame_key == want_frame:
            f1 += 1
        if want_frame in rec.blamed_keys[:k]:
            fk += 1
        if want_file and rec.fault_file_hint and \
                os.path.basename(want_file) == os.path.basename(rec.fault_file_hint):
            fl += 1
    return {"frame@1": _wrap(f1, n), f"frame@{k}": _wrap(fk, n), "file@1": _wrap(fl, n),
            "no_fault_found": nofault, "n": n}
