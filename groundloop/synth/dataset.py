"""Assemble the synthesized-log Type-2 test slice from mined cases + the atlas.

Reads each mined case (its scrubbed `ticket.json` + `_oracle/`), adds a synthesized AAOS failure
log that names the owner's crash-site symbols (`logs.synth_log_for_case`), and writes the transformed
case in the on-disk dataset format. Deliberately does NOT import `groundloop.mine.*` (SP1b's producer)
— it writes the case dirs directly, so it stays decoupled from the in-flight miner changes."""
from __future__ import annotations

import glob
import json
import os

from groundloop.engines.atlas.store import Store
from groundloop.synth.logs import synth_log_for_case


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def write_synth_case(src_case_dir: str, store: Store, dest_root: str):
    """Transform one mined case into a synth-log case under dest_root; return case_id or None."""
    cid = os.path.basename(src_case_dir.rstrip("/"))
    oracle = _load(os.path.join(src_case_dir, "_oracle", "oracle.json"))
    owner, files = oracle.get("owning_repo"), oracle.get("expected_files") or []
    if not owner or not files:
        return None
    built = synth_log_for_case(store, owner, files, cid)
    if not built:
        return None                                   # no indexable crash site (test-only / no symbols)
    text, kind = built
    ticket = _load(os.path.join(src_case_dir, "ticket.json"))
    dest = os.path.join(dest_root, cid)
    os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
    with open(os.path.join(dest, "logs", "crash.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    ticket["logs"] = [{"path": "logs/crash.txt", "kind": kind}]      # loop reads the synth failure log
    _dump(os.path.join(dest, "ticket.json"), ticket)
    _dump(os.path.join(dest, "_oracle", "oracle.json"), {**oracle, "synth_log": kind})
    return cid


def build_synth_dataset(src_root: str, atlas_db: str, dest_root: str, catalog_names: list[str]) -> list[str]:
    """Synth-log every viable mined case in src_root into dest_root; write the catalog; return case_ids."""
    store = Store(atlas_db)
    made = []
    for d in sorted(glob.glob(os.path.join(src_root, "*"))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "ticket.json")):
            cid = write_synth_case(d, store, dest_root)
            if cid:
                made.append(cid)
    _dump(os.path.join(dest_root, "catalog.json"), [{"name": n} for n in catalog_names])
    return made
