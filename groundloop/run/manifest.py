"""Per-batch provenance manifest: the config that produced a `gloop run --out` batch, so a grade-run
card can be attributed to its atlas/model/affinity pins. change_sink is recorded honestly (mock today)."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


def _atlas_identity(atlas_db) -> str:
    if not atlas_db or not os.path.exists(atlas_db):
        return ""
    st = os.stat(atlas_db)
    return f"{st.st_size}:{int(st.st_mtime)}"


def _affinity_id(affinity) -> object:
    if not affinity or not os.path.exists(affinity):
        return ""
    return {"path": str(affinity), "sha1": hashlib.sha1(Path(affinity).read_bytes()).hexdigest()}


def write_manifest(out: str, *, atlas_db, match_arm: str, fixer: str, affinity, produce_model: str,
                   embed_model: str, n_cases: int, change_sink: str = "mock") -> str:
    manifest = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "atlas_db": str(atlas_db) if atlas_db else "",
        "atlas_identity": _atlas_identity(atlas_db),
        "match_arm": match_arm,
        "fixer": fixer,
        "affinity": _affinity_id(affinity),
        "model_pins": {"produce": produce_model, "embed": embed_model},
        "change_sink": change_sink,
        "n_cases": n_cases,
    }
    p = Path(out) / "manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return str(p)
