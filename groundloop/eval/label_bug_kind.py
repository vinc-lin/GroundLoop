"""Offline labeling pass: stamp bug_kind (crash|functional) into each case's _oracle/oracle.json.
crash = a fault anchor was extracted (fault_frame present); functional = prose-only / no anchor.
OFFLINE artifact — bug_kind is never read by the loop (only by the scorecard). Idempotent."""
from __future__ import annotations

import json
from pathlib import Path


def _classify(oracle: dict) -> str:
    return "crash" if oracle.get("fault_frame") else "functional"


def stamp_bug_kind(dataset_root: str) -> int:
    n = 0
    for d in sorted(Path(dataset_root).iterdir()):
        op = d / "_oracle" / "oracle.json"
        if not op.is_file():
            continue
        oracle = json.loads(op.read_text())
        oracle["bug_kind"] = _classify(oracle)
        op.write_text(json.dumps(oracle, indent=2, ensure_ascii=False))
        n += 1
    return n
