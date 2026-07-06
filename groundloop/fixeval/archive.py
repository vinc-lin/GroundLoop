"""Persist per-case repair plans + outcomes (capture-only; consumption — retrieval / regression /
distill — is a future design). Keyed by case_id + arm under <out>/plans/."""
from __future__ import annotations

import json
from pathlib import Path

ARCHIVE_SCHEMA = 1


def _safe(s: str) -> str:
    """Filename-safe key component (case_id/arm may carry path separators)."""
    return str(s).replace("/", "_")


def archive_plans(records, out_dir: str) -> int:
    planned = [r for r in records if getattr(r, "plan", None)]   # truthy — aligned with the scorecard
    if not planned:                                              # no empty plans/ dir on a direct-only run
        return 0
    d = Path(out_dir) / "plans"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in planned:
        payload = {
            "schema": ARCHIVE_SCHEMA,
            "case_id": r.case_id,
            "arm": r.arm,
            "predicted_repo": r.predicted_repo,
            "plan": r.plan,
            "fired_skills": list(getattr(r, "fired_skills", [])),
            "outcome": {
                "groundedness": r.groundedness,
                "replans": getattr(r, "replans", 0),
                "abstained": r.abstained,
                "patch_emitted": r.patch_emitted,
                "patch_applies": r.patch_applies,
            },
        }
        (d / f"{_safe(r.case_id)}__{_safe(r.arm)}.json").write_text(json.dumps(payload, indent=2))
        n += 1
    return n
