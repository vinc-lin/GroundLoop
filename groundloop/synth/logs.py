"""Synthesize AAOS-realistic failure-log tickets from a mined case's fix-commit files.

The mined GitHub-issue tickets are ~87% user prose without the failure-log signal the Stage-1
matcher (and the real in-vehicle system) keys on. But every case records its fix's changed source
files + owning repo (`_oracle/`), and the atlas holds the REAL crash-site class/method symbols for
those files. So we build a realistic logcat / native backtrace that names those symbols — the exact
diagnostic signal a triager reads to route a defect to its owning repo.

This is NOT leakage: a real failure log names the crashing class/package/.so; that is the grounded
signal, matched against the atlas (never the repo name). Test files are excluded (a fix's test isn't
the crash site). This module writes the on-disk case format directly — it does NOT touch the SP1b
miner (`groundloop.mine.*`).

Every crash class ALSO embeds the owner's real crash frames, so the diagnostic *signature* (which KB
skill fires) is orthogonal to the *grounding* (which repo `rank_repos` ranks top-1): the generic
signature strings (SIGABRT, "underrun", "FAILED BINDER TRANSACTION", ...) name no fleet repo, while
the owner's real class/method/.so keep the log routable to its owning repo. See
`CRASH_CLASSES` / `select_crash_class` for the per-skill signature builders."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

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


# ============================================================================ base builders

def build_java_logcat(frames: list[Frame], exc: str, rng: random.Random, *,
                      message: Optional[str] = None, extra_lines: Optional[list[str]] = None) -> str:
    """A logcat FATAL EXCEPTION naming the owner's real frames. `message` (when given) sets the
    exception text DETERMINISTICALLY so a crash class can carry its discriminating signature; `extra_lines`
    are inserted right after the exception line (e.g. a "!!! FAILED BINDER TRANSACTION !!!" banner or an
    extra framework frame). Back-compat: with neither, the message is a random generic phrase."""
    ts = "07-05 10:34:07.221  4821  4821 E AndroidRuntime: "
    msg = message if message is not None else rng.choice(
        ["null object reference", "invalid state", "index out of range"])
    lines = [ts + "FATAL EXCEPTION: main",
             ts + f"{exc}: {msg}"]
    for extra in (extra_lines or []):
        lines.append(ts + extra)
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


def build_native_abort(so: str, frames: list[Frame], rng: random.Random) -> str:
    """A SIGABRT heap-corruption tombstone (double-free abort_message) over the owner's frames."""
    ts = "07-05 10:34:07.221  4821  4821 F DEBUG   : "
    lines = [ts + "*** *** *** *** *** *** *** ***",
             ts + "signal 6 (SIGABRT), code -6 (SI_TKILL), fault addr --------",
             ts + "Abort message: 'free(): double free detected in tcache 2'",
             ts + "backtrace:",
             ts + f"    #00 pc {rng.randrange(0x1000, 0xfffff):08x}  /apex/com.android.runtime/lib/"
                  "bionic/libc.so (abort+164)"]
    for i, fr in enumerate(frames, start=1):
        pc = rng.randrange(0x1000, 0xfffff)
        lines.append(ts + f"    #{i:02d} pc {pc:08x}  {so} ({fr.cls}::{fr.method}+{rng.randrange(8, 512)})")
    return "\n".join(lines) + "\n"


def build_audio_underrun(so: str, frames: list[Frame], rng: random.Random) -> str:
    """An AAudio low-latency underrun on the real-time onAudioReady callback, over the owner's frames."""
    wts = "07-05 10:34:07.201  4821  4913 W AAudio  : "
    dts = "07-05 10:34:07.221  4821  4913 F DEBUG   : "
    lines = [
        wts + f"AAudioStream_getXRunCount() = {rng.randrange(4, 120)}: buffer underrun on low-latency stream",
        wts + "onAudioReady callback took too long and overran the buffer deadline (period budget exceeded)",
        dts + "backtrace of the audio callback thread:",
        dts + f"    #00 pc {rng.randrange(0x1000, 0xfffff):08x}  /system/lib/libaaudio.so "
              "(AAudioStreamCallback::onAudioReady+72)"]
    for i, fr in enumerate(frames, start=1):
        pc = rng.randrange(0x1000, 0xfffff)
        lines.append(dts + f"    #{i:02d} pc {pc:08x}  {so} ({fr.cls}::{fr.method}+{rng.randrange(8, 512)})")
    return "\n".join(lines) + "\n"


def build_anr(frames: list[Frame], rng: random.Random, proc: str = "com.android.car.app") -> str:
    """An ActivityManager ANR (input-dispatch timeout) with the owner's frames on the blocked main thread."""
    ats = "07-05 10:34:07.221  1337  1502 E ActivityManager: "
    tts = "07-05 10:34:12.400  4821  4821 I DEBUG   : "
    lines = [ats + f"ANR in {proc} ({proc}/.MainActivity)",
             ats + "Reason: Input dispatching timed out (Waiting to send non-key event to the window)",
             ats + "Load: 12.5 / 8.30 / 6.10",
             tts + '"main" prio=5 tid=1 Blocked']
    for fr in frames:
        q = f"{fr.package}.{fr.cls}" if fr.package else fr.cls
        lines.append(tts + f"  at {q}.{fr.method}({fr.filename}:{fr.line})")
    for fw in rng.sample(_FRAMEWORK, k=min(2, len(_FRAMEWORK))):
        lines.append(tts + f"  at {fw}")
    return "\n".join(lines) + "\n"


# ============================================================================ java crash-class wrappers
# Each carries its skill's discriminating signature (per aaos_kb_seed.toml [skill.match]) deterministically,
# on top of the owner's real frames (grounding). Signature: (frames, rng) -> str.

def build_fgs_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "android.app.RemoteServiceException", rng,
        message="Context.startForegroundService() did not then call Service.startForeground()")


def build_ise_saved_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "java.lang.IllegalStateException", rng,
        message="Can not perform this action after onSaveInstanceState")


def build_binder_too_large_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "android.os.TransactionTooLargeException", rng,
        message=f"data parcel size {rng.randrange(1_050_000, 2_000_000)} bytes",
        extra_lines=["!!! FAILED BINDER TRANSACTION !!! (JavaBinder)"])


def build_media_illegal_state_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "java.lang.IllegalStateException", rng,
        message="MediaCodec called in state 3",
        extra_lines=["\tat android.media.MediaCodec.native_dequeueOutputBuffer(Native Method)",
                     "\tat android.media.MediaCodec.dequeueOutputBuffer(MediaCodec.java:2761)"])


def build_camera_gl_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "java.lang.IllegalStateException", rng,
        message="Surface has already been released")


def build_cme_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "java.util.ConcurrentModificationException", rng,
        message="collection modified during iteration",
        extra_lines=["\tat java.util.ArrayList$Itr.checkForComodification(ArrayList.java:1042)",
                     "\tat java.util.ArrayList$Itr.next(ArrayList.java:996)"])


def build_native_lib_load_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "java.lang.UnsatisfiedLinkError", rng,
        message="No implementation found for boolean com.aaos.NativeBridge.nativeInit() "
                "(tried Java_com_aaos_NativeBridge_nativeInit)",
        extra_lines=["\tat com.aaos.NativeBridge.nativeInit(Native Method)"])


def build_fragment_npe_crash(frames: list[Frame], rng: random.Random) -> str:
    return build_java_logcat(
        frames, "java.lang.NullPointerException", rng,
        message="Attempt to invoke virtual method 'void android.view.View.setVisibility(int)' "
                "on a null object reference",
        extra_lines=["\tat androidx.fragment.app.Fragment.onDestroyView(Fragment.java:2044)"])


# ============================================================================ crash-class registry

class CrashClass(NamedTuple):
    skill_id: str                      # the KB skill this class is authored to fire
    surface: str                       # "native" | "java"
    builder: Callable                  # native: (so, frames, rng)->str ; java: (frames, rng)->str
    affinity: Optional[frozenset]      # None = any repo of this surface; else bias to these repos only
    required_api: str = ""             # a KB-guidance API absent from this class's log; "" => not resolution-gradeable


# One class per KB skill (aaos_kb_seed.toml). Affinity biases a class to its natural owners but never
# hard-gates coverage: every surface keeps affinity-free classes so no repo starves.
# `required_api` (last field) is populated ONLY where a KB-guidance API is a genuine, correct fix for
# the bug class AND is absent from that class's generated log (headroom: a no-KB `none` arm can't read it
# for free). Each planted value is asserted named-in-guidance + not-in-log by tests/synth/test_required_api.py.
# Classes whose fix API leaks into their own log (e.g. FGS's startForeground IS in its log) or is ambiguous
# (native SEGV underrun, binder, media, GL, lib-load, ANR) keep required_api="" (not resolution-gradeable).
CRASH_CLASSES: list[CrashClass] = [
    CrashClass("native-null-deref-segv", "native", build_native_backtrace, None, "GetLongField"),
    CrashClass("native-heap-corruption-abort", "native", build_native_abort, None, "std::unique_ptr"),
    CrashClass("realtime-audio-callback-underrun", "native", build_audio_underrun, frozenset({"oboe"})),
    CrashClass("foreground-service-not-started", "java", build_fgs_crash, None, "NotificationChannel"),
    CrashClass("illegalstate-after-savedinstancestate", "java", build_ise_saved_crash, None,
               "commitAllowingStateLoss"),
    CrashClass("binder-transaction-too-large", "java", build_binder_too_large_crash, None),
    # repo-agnostic: MediaCodec / Surface signatures are generic android.media/GL tokens (no owner leak),
    # and the affine repos (media3/cameraview/gpuimage) are too thin to carry these classes — so keep them
    # affinity-free to guarantee firing coverage across the fleet.
    CrashClass("media-player-illegal-state", "java", build_media_illegal_state_crash, None),
    CrashClass("camera-gl-surface-lifecycle", "java", build_camera_gl_crash, None),
    CrashClass("shared-state-race-cme", "java", build_cme_crash, None, "CopyOnWriteArrayList"),
    CrashClass("native-lib-load-failure", "java", build_native_lib_load_crash, None),
    CrashClass("fragment-view-after-destroy-npe", "java", build_fragment_npe_crash, None,
               "getViewLifecycleOwner"),
    CrashClass("main-thread-blocking-anr", "java", build_anr, None),
]


def _stable_pick(case_id: str, n: int) -> int:
    """Deterministic index in [0, n): a stable hash of case_id (NOT the frame rng, so frame randomness
    is untouched) spreads crash classes evenly across cases for balanced KB-skill coverage."""
    h = int.from_bytes(hashlib.sha1(case_id.encode("utf-8")).digest()[:8], "big")
    return h % n


def select_crash_class(owner: str, frames: list[Frame], case_id: str) -> CrashClass:
    """Pick the crash class for one case: derive the crash surface from the owner + its frames, keep the
    classes compatible with that surface (dropping any whose affinity excludes the owner), then pick one
    deterministically by case_id for even coverage."""
    native = owner in _NATIVE_SO or all(not f.package for f in frames)
    surface = "native" if native else "java"
    compat = [c for c in CRASH_CLASSES
              if c.surface == surface and (c.affinity is None or owner in c.affinity)]
    if not compat:                                     # defensive: fall back to affinity-free classes
        compat = [c for c in CRASH_CLASSES if c.surface == surface and c.affinity is None]
    return compat[_stable_pick(case_id, len(compat))]


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
    """Build one realistic failure log naming the owner's crash-site symbols. Returns
    (text, kind, required_api) or None; required_api is "" when the fired class is not resolution-gradeable.

    The crash class (which KB skill the log fires) is chosen deterministically per case for even coverage;
    every class embeds the owner's real frames so the log still ranks the owner top-1 over the atlas."""
    rng = _rng(case_id)
    frames = crash_frames(store, owning_repo, files, rng)
    if not frames:
        return None
    cc = select_crash_class(owning_repo, frames, case_id)
    if cc.surface == "native":
        so = _NATIVE_SO.get(owning_repo, f"lib{owning_repo.split('-')[0]}.so")
        return cc.builder(so, frames, rng), "native", cc.required_api
    return cc.builder(frames, rng), "logcat", cc.required_api
