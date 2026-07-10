"""Fault-point extraction (Android Log Match v2 §6.3): anchors -> pid/tid scope -> normalized blamed
frames -> first non-framework frame = fault site. Returns None when no fault anchor is present."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from groundloop.domains.android_ivi.frame_norm import NormFrame, normalize_java, normalize_native
from groundloop.domains.android_ivi.logcat_parse import LogLine

# Framework/system prefixes to SKIP when picking the fault site. NOTE: precise androidx subpackages only —
# a blanket "androidx." would wrongly skip the media3 OWNER namespace (androidx.media3.*).
_FRAMEWORK_PREFIXES = (
    "android.", "java.", "javax.", "kotlin.", "kotlinx.", "dalvik.",
    "com.android.", "com.google.android.",
    "androidx.fragment.", "androidx.appcompat.", "androidx.core.", "androidx.recyclerview.",
    "androidx.lifecycle.", "androidx.activity.",
)
# Full system sonames (EXACT match, not startswith — a bare "libc" prefix would wrongly skip owner
# libs like libcge.so / libcamera.so). normalize_native strips the version suffix, so these are canonical.
_FRAMEWORK_SONAMES = frozenset({
    "libc.so", "libart.so", "libaaudio.so", "libandroid.so", "libbinder.so", "libgui.so",
    "libutils.so", "libhwui.so", "libEGL.so", "libGLESv1_CM.so", "libGLESv2.so", "libGLESv3.so",
    "libbase.so", "libcutils.so",
})
_JAVA_FRAME = re.compile(r"\bat\s+([A-Za-z_][\w.$]+)\.([A-Za-z_<][\w$>]*)\(([^:)]+)(?::(\d+))?\)")
_NATIVE_FRAME = re.compile(r"#\d+\s+pc\s+[0-9a-fA-F]+\s+(\S+\.so[\w.]*)\s*\(([^)]+)\)")
_EXC = re.compile(r"^\s*((?:[a-z]\w*\.)+[A-Z]\w*(?:Error|Exception))", re.M)


@dataclass(frozen=True)
class FaultRecord:
    family: str                          # "java" | "native" | "anr"
    exception: str
    frames: list[NormFrame] = field(default_factory=list)
    top_frame: NormFrame | None = None
    fault_file_hint: str | None = None
    pid: str | None = None
    tag: str | None = None
    confidence: str = "LOW"


def _is_framework(nf: NormFrame) -> bool:
    if nf.soname:                                    # native frame
        return nf.soname in _FRAMEWORK_SONAMES
    key = (nf.package + "." if nf.package else "") + nf.klass
    return any(key.startswith(p) for p in _FRAMEWORK_PREFIXES)


def _first_owner(frames: list[NormFrame]) -> NormFrame | None:
    for f in frames:
        if not _is_framework(f):
            return f
    return None


def _anchor(lines: list[LogLine]):
    """Return (index, family) of the first fault anchor, else None."""
    for i, ln in enumerate(lines):
        msg = ln.msg or ""
        if "FATAL EXCEPTION" in msg:
            return i, "java"
        if (ln.tag == "libc" and "Fatal signal" in msg) or re.search(r"\bsignal \d+ \(SIG", msg):
            return i, "native"
        if "ANR in" in msg:
            return i, "anr"
    return None


def extract_fault_record(lines: list[LogLine]) -> FaultRecord | None:
    hit = _anchor(lines)
    if hit is None:
        return None
    idx, family = hit
    pid = lines[idx].pid
    tag = lines[idx].tag
    # scope: the crash block is the window after the anchor (frames are contiguous; interleaved noise simply
    # won't match the frame regexes). ANR blames a DIFFERENT pid than the ActivityManager anchor line, so we
    # deliberately do NOT pid-filter the window.
    block = lines[idx:idx + 400]
    text = "\n".join(ln.msg or ln.raw for ln in block)
    frames: list[NormFrame] = []
    for m in _JAVA_FRAME.finditer(text):
        frames.append(normalize_java(m.group(1), m.group(2), raw=m.group(0)))
    for m in _NATIVE_FRAME.finditer(text):
        frames.append(normalize_native(m.group(1), m.group(2), raw=m.group(0)))
    exc = ""
    em = _EXC.search(text)
    if em:
        exc = em.group(1)
    top = _first_owner(frames)
    if top is None:
        conf = "LOW"
        top = frames[0] if frames else None
    elif top.obfuscated:
        conf = "MEDIUM"
    else:
        conf = "HIGH"
    if top is None:
        return None
    fault_file_hint = None
    m = _JAVA_FRAME.search(top.raw)
    if m and m.group(3):
        fault_file_hint = m.group(3)
    return FaultRecord(family=family, exception=exc, frames=frames, top_frame=top,
                       fault_file_hint=fault_file_hint, pid=pid, tag=tag, confidence=conf)
