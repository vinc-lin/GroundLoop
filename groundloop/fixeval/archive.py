"""Persist per-case repair plans + outcomes (capture-only; consumption — retrieval / regression /
distill — is a future design). Keyed by case_id + arm under <out>/plans/."""
from __future__ import annotations

import json
from pathlib import Path

ARCHIVE_SCHEMA = 1


def archive_plans(records, out_dir: str) -> int:
    d = Path(out_dir) / "plans"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in records:
        if getattr(r, "plan", None) is None:
            continue
        payload = {
            "schema": ARCHIVE_SCHEMA,
            "case_id": r.case_id,
            "arm": r.arm,
            "predicted_repo": r.predicted_repo,
            "plan": r.plan,
            "outcome": {
                "groundedness": r.groundedness,
                "replans": getattr(r, "replans", 0),
                "abstained": r.abstained,
                "patch_emitted": r.patch_emitted,
                "patch_applies": r.patch_applies,
            },
        }
        (d / f"{r.case_id}__{r.arm}.json").write_text(json.dumps(payload, indent=2))
        n += 1
    return n
