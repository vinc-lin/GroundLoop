"""Synthesize AAOS-realistic failure-log tickets from a mined case's fix-commit files.

The mined GitHub-issue tickets are ~87% user prose without the failure-log signal the Stage-1
matcher (and the real in-vehicle system) keys on. But every case records its fix's changed source
files + owning repo (`_oracle/`), and the atlas holds the REAL crash-site class/method symbols for
those files. So we build a realistic logcat / native backtrace that names those symbols — the exact
diagnostic signal a triager reads to route a defect to its owning repo.

This is NOT leakage: a real failure log names the crashing class/package/.so; that is the grounded
signal, matched against the atlas (never the repo name). Test files are excluded (a fix's test isn't
the crash site). This module writes the on-disk case format directly — it does NOT touch the SP1b
miner (`groundloop.mine.*`)."""
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass

# repos whose crash surfaces are native (.so backtraces, not JVM stacks)
_NATIVE_SO = {"oboe": "liboboe.so", "dlt-daemon": "libdlt.so",
              "android-gpuimage-plus": "libCGE.so"}
_JAVA_EXC = ["java.lang.NullPointerException", "java.lang.IllegalStateException",
             "java.lang.IndexOutOfBoundsException", "java.lang.IllegalArgumentException"]
_FRAMEWORK = ["android.os.Handler.dispatchMessage(Handler.java:106)",
              "android.os.Looper.loop(Looper.java:246)",
              "android.app.ActivityThread.main(ActivityThread.java:8512)"]


@dataclass
class Frame:
    package: str          # e.g. org.schabi.newpipe.streams  (java) or "" (native)
    cls: str              # e.g. SrtFromTtmlWriter
    method: str           # e.g. write / <init>
    filename: str         # e.g. SrtFromTtmlWriter.java
    line: int


def parse_source_file(path: str):
    """(lang, package, class) from a repo-relative source path; (None,..) if not indexable source."""
    if re.search(r"/(?:test|androidTest)/", path):     # a fix's test file is not the crash site
        return None, None, None
    m = re.search(r"/(?:java|kotlin)/(.+)\.(?:java|kt)$", path)
    if m:
        parts = m.group(1).split("/")
        return "java", ".".join(parts[:-1]), parts[-1]
    m = re.search(r"([A-Za-z0-9_]+)\.(?:cpp|cc|cxx|c|mm)$", path)
    if m:
        return "native", "", m.group(1)
    return None, None, None


def _rng(seed: str) -> random.Random:
    return random.Random(int.from_bytes(seed.encode("utf-8"), "big") % (2**63))


def build_java_logcat(frames: list[Frame], exc: str, rng: random.Random) -> str:
    ts = "07-05 10:34:07.221  4821  4821 E AndroidRuntime: "
    lines = [ts + "FATAL EXCEPTION: main",
             ts + f"{exc}: {rng.choice(['null object reference', 'invalid state', 'index out of range'])}"]
    for fr in frames:
        q = f"{fr.package}.{fr.cls}" if fr.package else fr.cls
        lines.append(ts + f"\tat {q}.{fr.method}({fr.filename}:{fr.line})")
    for fw in rng.sample(_FRAMEWORK, k=min(2, len(_FRAMEWORK))):
        lines.append(ts + f"\tat {fw}")
    return "\n".join(lines) + "\n"


def build_native_backtrace(so: str, frames: list[Frame], rng: random.Random) -> str:
    lines = ["07-05 10:34:07.221  4821  4821 F DEBUG   : *** *** *** *** *** *** *** ***",
             "07-05 10:34:07.221  4821  4821 F DEBUG   : signal 11 (SIGSEGV), code 1 (SEGV_MAPERR)",
             "07-05 10:34:07.221  4821  4821 F DEBUG   : backtrace:"]
    for i, fr in enumerate(frames):
        pc = rng.randrange(0x1000, 0xfffff)
        lines.append(f"07-05 10:34:07.221  4821  4821 F DEBUG   :     #{i:02d} pc {pc:08x}  "
                     f"{so} ({fr.cls}::{fr.method}+{rng.randrange(8, 512)})")
    return "\n".join(lines) + "\n"


def crash_frames(store, repo: str, files: list[str], rng: random.Random, limit: int = 3) -> list[Frame]:
    """Real crash-site frames: for each source file, pull a real class + method name from the atlas."""
    frames: list[Frame] = []
    for path in files:
        lang, pkg, cls = parse_source_file(path)
        if not lang:
            continue
        base = os.path.basename(path)
        method = _atlas_method(store, repo, base, cls) or rng.choice(["<init>", "run", "process", "onEvent"])
        frames.append(Frame(package=pkg or "", cls=cls, method=method, filename=base,
                            line=rng.randrange(40, 900)))
        if len(frames) >= limit:
            break
    return frames


def _atlas_method(store, repo: str, base: str, cls: str):
    """A real method/function name in this file from the atlas (label Method/Function), else None."""
    rows = store.db.execute(
        "SELECT name, meta FROM units WHERE repo=? AND kind='symbol' AND file LIKE ? LIMIT 40",
        (repo, f"%{base}%")).fetchall()
    for r in rows:
        try:
            label = json.loads(r["meta"] or "{}").get("label", "")
        except (ValueError, TypeError):
            label = ""
        name = r["name"] or ""
        if label in ("Method", "Function") and name and name != cls and re.fullmatch(r"[A-Za-z_]\w*", name):
            return name
    return None


def synth_log_for_case(store, owning_repo: str, files: list[str], case_id: str):
    """Build one realistic failure log naming the owner's crash-site symbols. Returns (text, kind) or None."""
    rng = _rng(case_id)
    frames = crash_frames(store, owning_repo, files, rng)
    if not frames:
        return None
    if owning_repo in _NATIVE_SO or all(not f.package for f in frames):
        so = _NATIVE_SO.get(owning_repo, f"lib{owning_repo.split('-')[0]}.so")
        return build_native_backtrace(so, frames, rng), "native_backtrace"
    return build_java_logcat(frames, rng.choice(_JAVA_EXC), rng), "logcat"
