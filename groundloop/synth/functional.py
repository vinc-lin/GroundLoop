"""Functional (no-crash) synth: turn a mined positive into a prose-only ticket (UI-text) or a
prose + non-crash-log ticket (audio/CarPlay). Names the owner's real class/method from the atlas so
the case is groundable WITHOUT a crash frame; NO fault_frame is written. bug_kind='functional'.
A separate track (dataset_kind='functional_unscrubbed'). Deterministic per case id."""
from __future__ import annotations

import glob
import json
import os

from groundloop.synth.logs import _NATIVE_SO, _rng, crash_frames


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


# Slug-free domain prose per fleet repo — a functional ticket is SYMPTOM prose and must NOT name the
# owner (no slug, no package, no FQ class), else the flood baseline recovers the owner from the ticket
# (spec §10 invariant #3). The owner's real code tells belong only in the optional LOG (like a crash log).
_DOMAIN = {
    "android-gpuimage-plus": "real-time photo filter and GPU effect",
    "cameraview": "camera preview and capture",
    "dlt-daemon": "diagnostic trace logging",
    "antennapod": "podcast subscription and episode download",
    "newpipe": "video streaming and playback feed",
    "oboe": "low-latency audio playback",
    "osmand": "offline map and turn-by-turn navigation",
    "media3": "media player and video track selection",
    "organicmaps": "offline map and place navigation",
}
_TEMPLATES = {
    "ui_text": ("Wrong label shown in the {domain} screen",
                "A string in the {domain} UI is incorrect / not localized. No crash — the wrong "
                "text is simply displayed."),
    "audio": ("Audio stutters in {domain}",
              "Playback in the {domain} feature underruns intermittently. No crash — audio glitches."),
    "carplay": ("Projection connection drops in {domain}",
                "The CarPlay / Android-Auto session for the {domain} feature fails to connect or "
                "disconnects. No crash is logged; the screen just goes blank."),
}
_AUDIO_LOG_T = "W AAudio  : {so} onAudioReady buffer underrun (count=37)\n"
_CARPLAY_LOG_T = ("I CarConnection: projection connection state=CONNECTING\n"
                  "W CarConnection: connection timeout after 5000ms; session not established\n"
                  "W CarConnection: last active handler at {fq}.{method}({file})\n")


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
    domain = _DOMAIN.get(owner, "the affected module")
    summary_t, desc_t = _TEMPLATES.get(klass, _TEMPLATES["ui_text"])
    summary = summary_t.format(domain=domain)
    description = desc_t.format(domain=domain)

    dest = os.path.join(dest_root, cid)
    logs_field: list[dict] = []
    if klass in ("audio", "carplay"):
        os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
        if klass == "audio":
            so = _NATIVE_SO.get(owner, f"lib{owner.split('-')[0]}.so")
            text = _AUDIO_LOG_T.format(so=so)
        else:
            fq = f"{top.package}.{top.cls}" if top.package else top.cls
            text = _CARPLAY_LOG_T.format(fq=fq, method=top.method, file=top.filename)
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
