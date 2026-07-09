"""Unscrubbed long-log synth: bury a real owner crash in framework noise + label the fault locus.
A SEPARATE dataset track from the scrubbed Type-2 benchmark (dataset_kind=faultlog_unscrubbed)."""
from __future__ import annotations

import glob
import json
import os

from groundloop.domains.android_ivi.frame_norm import normalize_java, normalize_native
from groundloop.engines.atlas.store import Store
from groundloop.synth.data.framework_noise import render_noise_lines
from groundloop.synth.logs import (_NATIVE_SO, _rng, crash_frames, parse_source_file,
                                   select_crash_class)


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def _family(cc) -> str:
    if cc.surface == "native":
        return "native"
    return "anr" if cc.skill_id == "main-thread-blocking-anr" else "java"


def _oracle_frame(top, family: str, so: str):
    """Canonical NormFrame.key() for the top owner frame — matches what the extractor will emit."""
    if family == "native":
        return normalize_native(so, f"{top.cls}::{top.method}").key()
    fq = f"{top.package}.{top.cls}" if top.package else top.cls
    return normalize_java(fq, top.method).key()


def build_faultlog_case(src_case_dir: str, store: Store, dest_root: str, *,
                        difficulty: str = "clean", noise_lines: int = 3000) -> str | None:
    """Transform one mined positive into an unscrubbed long-log case; return case_id or None."""
    cid = os.path.basename(src_case_dir.rstrip("/"))
    with open(os.path.join(src_case_dir, "_oracle", "oracle.json"), encoding="utf-8") as fh:
        oracle = json.load(fh)
    owner, files = oracle.get("owning_repo"), oracle.get("expected_files") or []
    if not owner or not files:
        return None
    rng = _rng(cid)
    frames = crash_frames(store, owner, files, rng)
    if not frames:
        return None
    cc = select_crash_class(owner, frames, cid)
    family = _family(cc)
    so = _NATIVE_SO.get(owner, f"lib{owner.split('-')[0]}.so")
    block = cc.builder(so, frames, rng) if cc.surface == "native" else cc.builder(frames, rng)
    top = frames[0]
    fault_frame = _oracle_frame(top, family, so)
    fault_file = next((f for f in files
                       if parse_source_file(f)[0] and os.path.basename(f) == top.filename),
                      files[0])

    noise = render_noise_lines(rng, n=noise_lines, base_ms=0)
    cut = rng.randrange(len(noise) // 4, max(len(noise) // 4 + 1, 3 * len(noise) // 4))
    hard = _hard_decoys(owner, rng) if difficulty == "hard" else []
    body = noise[:cut] + hard + block.splitlines() + noise[cut:]
    log_text = "\n".join(body) + "\n"

    dest = os.path.join(dest_root, cid)
    os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
    with open(os.path.join(dest, "logs", "000.txt"), "w", encoding="utf-8") as fh:
        fh.write(log_text)
    with open(os.path.join(src_case_dir, "ticket.json"), encoding="utf-8") as fh:
        ticket = json.load(fh)
    ticket["logs"] = [{"path": "logs/000.txt", "kind": "logcat"}]
    _dump(os.path.join(dest, "ticket.json"), ticket)
    new_oracle = {**oracle, "fault_family": family, "fault_frame": fault_frame,
                  "fault_file": fault_file, "fault_line": top.line, "difficulty": difficulty}
    if difficulty == "hard":
        new_oracle["decoys"] = _decoy_manifest(owner)
    _dump(os.path.join(dest, "_oracle", "oracle.json"), new_oracle)
    return cid


def _hard_decoys(owner: str, rng) -> list[str]:
    """Clean mode: no decoys. Phase 3 (a later task) implements hard-mode decoys here."""
    return []


def _decoy_manifest(owner: str) -> list[str]:
    return []


def build_faultlog_dataset(src_root: str, atlas_db: str, dest_root: str, catalog_names: list[str], *,
                           difficulty: str = "clean", noise_lines: int = 3000) -> list[str]:
    store = Store(atlas_db)
    made = []
    for d in sorted(glob.glob(os.path.join(src_root, "*"))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "ticket.json")):
            cid = build_faultlog_case(d, store, dest_root, difficulty=difficulty, noise_lines=noise_lines)
            if cid:
                made.append(cid)
    _dump(os.path.join(dest_root, "catalog.json"), [{"name": n} for n in catalog_names])
    _dump(os.path.join(dest_root, "dataset_meta.json"),
          {"dataset_kind": "faultlog_unscrubbed", "difficulty": difficulty})
    return made
