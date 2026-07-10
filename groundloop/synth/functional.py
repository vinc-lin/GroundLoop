"""Functional (no-crash) synth: turn a mined positive into a prose-only ticket (UI-text) or a
prose + non-crash-log ticket (audio/CarPlay). Names the owner's real class/method from the atlas so
the case is groundable WITHOUT a crash frame; NO fault_frame is written. bug_kind='functional'.
A separate track (dataset_kind='functional_unscrubbed'). Deterministic per case id."""
from __future__ import annotations

import glob
import json
import os

from groundloop.synth.logs import _rng, crash_frames


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


_TEMPLATES = {
    "ui_text": ("Wrong label shown in {cls} screen",
                "The UI text under {cls}.{method} is incorrect / not localized. No crash occurs; "
                "the wrong string is simply displayed."),
    "audio": ("Audio stutters / drops when using {cls}",
              "Playback via {cls}.{method} underruns intermittently. No crash — audio just glitches."),
    "carplay": ("Projection connection drops in {cls}",
                "The CarPlay/Android-Auto session handled by {cls}.{method} fails to connect / "
                "disconnects. No crash is logged; the screen just goes blank."),
}
_AUDIO_LOG = "W AAudio  : liboboe.so onAudioReady buffer underrun (count=37)\n"
_CARPLAY_LOG = ("I CarConnection: projection connection state=CONNECTING\n"
                "W CarConnection: connection timeout after 5000ms; session not established\n")


def build_functional_case(src_case_dir: str, store, dest_root: str, *,
                          klass: str = "ui_text") -> str | None:
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
    top = frames[0]
    fq = f"{top.package}.{top.cls}" if top.package else top.cls
    summary_t, desc_t = _TEMPLATES.get(klass, _TEMPLATES["ui_text"])
    summary = summary_t.format(cls=fq, method=top.method)
    description = desc_t.format(cls=fq, method=top.method)

    dest = os.path.join(dest_root, cid)
    logs_field: list[dict] = []
    if klass in ("audio", "carplay"):
        os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
        text = _AUDIO_LOG if klass == "audio" else _CARPLAY_LOG
        with open(os.path.join(dest, "logs", "000.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        logs_field = [{"path": "logs/000.txt", "kind": "logcat"}]

    with open(os.path.join(src_case_dir, "ticket.json"), encoding="utf-8") as fh:
        ticket = json.load(fh)
    ticket.update({"summary": summary, "description": description, "component": "", "logs": logs_field})
    _dump(os.path.join(dest, "ticket.json"), ticket)
    new_oracle = {**oracle, "bug_kind": "functional", "functional_class": klass}
    new_oracle.pop("fault_frame", None)
    new_oracle.pop("synth_log", None)
    _dump(os.path.join(dest, "_oracle", "oracle.json"), new_oracle)
    return cid


def build_functional_dataset(src_root: str, atlas_db: str, dest_root: str,
                             catalog_names: list[str]) -> list[str]:
    from groundloop.engines.atlas.store import Store
    store = Store(atlas_db)
    classes = ("ui_text", "audio", "carplay")
    made: list[str] = []
    for i, d in enumerate(sorted(glob.glob(os.path.join(src_root, "*")))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "ticket.json")):
            cid = build_functional_case(d, store, dest_root, klass=classes[i % len(classes)])
            if cid:
                made.append(cid)
    _dump(os.path.join(dest_root, "catalog.json"), [{"name": n} for n in catalog_names])
    _dump(os.path.join(dest_root, "dataset_meta.json"),
          {"dataset_kind": "functional_unscrubbed"})
    return made
