"""Framework-noise generator for the faultlog synth: realistic multi-process AAOS logcat chatter that
names NO fleet owner (clean mode). Decoys (hard mode) are added separately in synth/faultlog.py. Pure +
deterministic (caller passes the rng)."""
from __future__ import annotations

import random

# Owner tokens that must NEVER appear in framework noise (clean mode invariant). Mirror the fleet's real
# namespaces/sonames; kept here as a guard, NOT sourced from any per-case oracle.
FLEET_OWNER_HINTS = frozenset({
    "net.osmand", "app.organicmaps", "org.schabi.newpipe", "com.google.oboe", "liboboe.so",
    "libdlt.so", "org.wysaid", "libCGE.so", "com.otaliastudios.cameraview", "androidx.media3",
})

# (tag, level, message-templates with <*> slots). Framework-only; no fleet owner appears.
_TEMPLATES = [
    ("ActivityManager", "I", ["Start proc <*> for activity {u0} pid=<*>", "Killing <*> (adj <*>): empty #<*>"]),
    ("PackageManager", "I", ["Package <*> installed for user 0", "Scanning package <*>"]),
    ("WindowManager", "W", ["Slow Looper main: doFrame took <*>ms", "Unable to start GC for <*>"]),
    ("SurfaceFlinger", "D", ["duplicate frame for layer <*>", "setTransactionState <*>"]),
    ("binder", "I", ["Binder call to <*> took <*>ms", "release <*> refs on <*>"]),
    ("system_server", "I", ["Waiting on <*> for <*>ms", "gc concurrent freed <*> objects"]),
    ("zygote", "I", ["Late-enabling -Xcheck:jni for <*>", "seccomp disabled by <*>"]),
    ("chatty", "I", ["uid=<*> expire <*> lines", "identical <*> lines dropped"]),
]
_PKGS = ["com.android.systemui", "com.android.settings", "com.android.car", "com.android.launcher3",
         "com.android.bluetooth", "com.android.phone", "android.process.media"]


def _fill(tmpl: str, rng: random.Random) -> str:
    out = tmpl
    while "<*>" in out:
        out = out.replace("<*>", rng.choice([str(rng.randrange(1, 9999)), rng.choice(_PKGS)]), 1)
    return out


def _ts(base_ms: int, i: int) -> str:
    ms = base_ms + i * 7
    mins, secs = divmod(ms // 1000, 60)
    return f"07-05 10:{34 + (mins % 24):02d}:{secs:02d}.{ms % 1000:03d}"


def render_noise_lines(rng: random.Random, n: int, base_ms: int) -> list[str]:
    """n framework logcat lines across ~30 synthetic pids; deterministic in rng."""
    pids = [rng.randrange(1000, 9000) for _ in range(30)]
    lines: list[str] = []
    for i in range(n):
        tag, level, tmpls = rng.choice(_TEMPLATES)
        pid = rng.choice(pids)
        msg = _fill(rng.choice(tmpls), rng)
        lines.append(f"{_ts(base_ms, i)} {pid:5d} {pid:5d} {level} {tag}: {msg}")
    return lines


# non-owner decoy vocab: other fleet repos' known namespaces/sonames + confusable near-misses.
# Keyed by owner so we NEVER inject the owner's own tokens. (Values are OTHER repos' production metadata.)
_DECOY_POOL = {
    "net.osmand": "osmand", "app.organicmaps": "organicmaps", "org.schabi.newpipe": "newpipe",
    "com.google.oboe": "oboe", "com.otaliastudios.cameraview": "cameraview", "androidx.media3": "media3",
    "liboboe.so": "oboe", "libdlt.so": "dlt-daemon", "libCGE.so": "android-gpuimage-plus",
}


def decoy_tokens_for(owner: str) -> list[str]:
    """Non-owner fleet tokens usable as decoys for an owner (never the owner's own)."""
    return [tok for tok, repo in _DECOY_POOL.items() if repo != owner]


def decoy_lines(owner: str, rng, n: int, base_ms: int) -> list[str]:
    """n non-fatal logcat lines that mention non-owner namespaces/sonames + binder chatter."""
    toks = decoy_tokens_for(owner)
    out = []
    for i in range(n):
        tok = rng.choice(toks)
        if tok.endswith(".so"):
            msg = f"dlopen {tok} from /system/lib64 ok"
            tag, lvl = "linker", "I"
        else:
            msg = rng.choice([f"Slow dispatch {tok}.MainActivity took {rng.randrange(200, 900)}ms",
                              f"handled non-fatal warning in {tok} (recovered)"])
            tag, lvl = rng.choice([("ActivityManager", "W"), ("binder", "I"), ("StrictMode", "E")])
        pid = rng.randrange(2000, 8000)
        out.append(f"07-05 10:35:{i % 60:02d}.{(base_ms + i) % 1000:03d} {pid:5d} {pid:5d} {lvl} {tag}: {msg}")
    return out
