"""Offline: build the component -> owning_repo affinity table from a dataset's loop-visible
ticket.component + offline oracle owning_repo. Population statistics, not per-ticket memory. Runs on
production over the full oracle; a standalone module (NOT the gated groundloop/mine/)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

_NEG_OWNERS = {"__NOT_A_DEFECT__", "__OUT_OF_FLEET__"}


def build_affinity(dataset_root: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in sorted(Path(dataset_root).iterdir()):
        tp, op = d / "ticket.json", d / "_oracle" / "oracle.json"
        if not (tp.is_file() and op.is_file()):
            continue
        comp = (json.loads(tp.read_text()).get("component") or "").strip()
        oracle = json.loads(op.read_text())
        owner = oracle.get("owning_repo")
        if not comp or not owner or owner in _NEG_OWNERS or not oracle.get("is_answerable", True):
            continue
        counts[comp][owner] += 1
    return {c: dict(repos) for c, repos in counts.items()}


def write_affinity(dataset_root: str, out_path: str) -> int:
    counts = build_affinity(dataset_root)
    Path(out_path).write_text(json.dumps(counts, indent=2, ensure_ascii=False, sort_keys=True))
    return sum(sum(r.values()) for r in counts.values())
