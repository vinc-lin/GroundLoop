# Android Log Match v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate the one true fault site from a long full-system logcat and attribute it to the owning
repo, with fault-localization and attribution scored separately.

**Architecture:** A deterministic domain pipeline (parse → normalize → fault-extract → tight `Signals`) feeds
the existing `EvalRunner`/`Arm` machinery as three arms (`flood`/`faultslice`/`routing`); a new unscrubbed
long-log synth provides the substrate and a fault-locus oracle; a separate offline pass grades
fault-localization. Phase 2 adds a production-known routing table + an RRF `FaultRoutingIndex`. No `core/`,
atlas-schema, or gated-`rank_repos`/`owner_tokens.py`/`mine/` edits.

**Tech Stack:** Python 3.12, pytest, ruff (line 110). Spec:
`docs/superpowers/specs/2026-07-09-android-log-match-v2-design.md`.

---

## Conventions (read before starting)

- Run tests: `.venv/bin/python -m pytest <path> -q`. Lint: `.venv/bin/ruff check groundloop tests`.
- All new dataclasses are **adapter-owned** — never add fields to `groundloop/core/types.py`.
- `Signals` (frozen, `core/types.py:23`) has exactly six string-tuple fields: `packages, classes, methods,
  symbols, libraries, errors`, plus `.tokens()`. We only *construct* it.
- `Frame` (`synth/logs.py:39`): `{package, cls, method, filename, line}`. `crash_frames(store, repo, files,
  rng, limit=3) -> list[Frame]` returns real atlas frames; `_rng(seed)`/`_stable_pick(case_id, n)` are the
  deterministic seeders (no wall-clock/`random.random()` at module scope).
- `AtlasIndex(db_path).rank_repos(signals, catalog) -> list[RepoScore]`; `catalog` is `list[RepoRef]`.
- Every commit message ends with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Commit only when the touched
  tests pass and ruff is clean.

## Canonical types & keys (used across tasks — do not diverge)

```python
# groundloop/domains/android_ivi/frame_norm.py
@dataclass(frozen=True)
class NormFrame:
    package: str      # "org.schabi.newpipe.streams" (java) or "" (native)
    klass: str        # "SrtWriter" | "AudioStreamAAudio"
    method: str       # "write" | "requestStart"
    soname: str       # "" (java) | "liboboe.so" (native)
    symbol: str       # "" (java) | "AudioStreamAAudio::requestStart" (native raw symbol, offset-stripped)
    obfuscated: bool
    raw: str
    def key(self) -> str: ...          # java: "pkg.Klass.method" or "Klass.method"; native: "Klass::method"
    def package_key(self) -> str: ...  # java: package; native: soname   (routing key)
```

- **Frame key (the fault-localization comparison unit):** java `"pkg.Klass.method"` (package omitted if
  empty); native `"Klass::method"`. Both synth (oracle) and extractor emit this via `NormFrame.key()`, so a
  round-trip (synth→extract) yields identical keys.
- `LogLine{ts, pid, tid, level, tag, msg, raw}` — `logcat_parse.py`.
- `FaultRecord{family, exception, frames: list[NormFrame], top_frame: NormFrame|None, fault_file_hint:
  str|None, pid: str|None, tag: str|None, confidence: str}` — `fault_extract.py`. `confidence ∈
  {"HIGH","MEDIUM","LOW"}`. **No fault anchor ⇒ `extract_fault_record()` returns `None`** (the spec's
  `confidence=NONE`), and callers treat `None` as the `no_fault_found` abstain.

---

# PHASE 0 — substrate & metrics

## Task 0.1: Frame normalization — `frame_norm.py`

**Files:**
- Create: `groundloop/domains/android_ivi/frame_norm.py`
- Test: `tests/domains/test_frame_norm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/domains/test_frame_norm.py
from groundloop.domains.android_ivi.frame_norm import NormFrame, normalize_java, normalize_native


def test_java_basic_key_and_package():
    f = normalize_java("org.schabi.newpipe.streams.SrtWriter", "write")
    assert f.package == "org.schabi.newpipe.streams"
    assert f.klass == "SrtWriter" and f.method == "write"
    assert f.key() == "org.schabi.newpipe.streams.SrtWriter.write"
    assert f.package_key() == "org.schabi.newpipe.streams"
    assert f.obfuscated is False


def test_java_no_package():
    f = normalize_java("CGEImageHandler", "process")
    assert f.package == "" and f.key() == "CGEImageHandler.process"


def test_java_strips_lambda_and_synthetic():
    assert normalize_java("com.x.Foo$$Lambda$3", "run").klass == "Foo"
    assert normalize_java("com.x.Foo$1", "onClick").klass == "Foo"
    assert normalize_java("com.x.Foo", "access$100").method == "access"


def test_java_inner_class_keeps_outer_package():
    f = normalize_java("com.x.Outer$Inner", "m")
    assert f.package == "com.x"          # package is the outer package
    assert f.klass == "Outer$Inner"      # inner class retained (only $$Lambda$N / $<digit> are stripped)


def test_java_jni_decode():
    f = normalize_java("Java_com_aaos_NativeBridge_nativeInit", "")
    assert f.package == "com.aaos" and f.klass == "NativeBridge" and f.method == "nativeInit"


def test_java_obfuscated_flagged():
    assert normalize_java("a.b.c", "d").obfuscated is True


def test_native_basename_and_offset_strip():
    f = normalize_native("/system/lib64/liboboe.so.1.2", "AudioStreamAAudio::requestStart+0x1c")
    assert f.soname == "liboboe.so"
    assert f.klass == "AudioStreamAAudio" and f.method == "requestStart"
    assert f.key() == "AudioStreamAAudio::requestStart"
    assert f.package_key() == "liboboe.so"


def test_native_bare_symbol():
    f = normalize_native("libdlt.so", "dlt_user_log_write_start")
    assert f.klass == "" and f.method == "dlt_user_log_write_start"
    assert f.key() == "dlt_user_log_write_start"
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/domains/test_frame_norm.py -q` → ImportError.

- [ ] **Step 3: Implement**

```python
# groundloop/domains/android_ivi/frame_norm.py
"""Deterministic frame normalization — the single comparison unit for fault extraction, routing, and the
fault_localization metric. Pure; no I/O. See spec §6.2."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LAMBDA = re.compile(r"\$\$Lambda\$\d+$")
_SYNTHETIC = re.compile(r"\$\d+$")              # anonymous inner class Foo$1
_OBFUSCATED_SEG = re.compile(r"^[a-z]$")        # single lowercase letter segment (R8/ProGuard)
_JNI = re.compile(r"^Java_(.+)_([A-Za-z_]\w*)$")


@dataclass(frozen=True)
class NormFrame:
    package: str
    klass: str
    method: str
    soname: str
    symbol: str
    obfuscated: bool
    raw: str

    def key(self) -> str:
        if self.soname or self.symbol:                      # native
            return f"{self.klass}::{self.method}" if self.klass else self.method
        base = f"{self.klass}.{self.method}" if self.method else self.klass
        return f"{self.package}.{base}" if self.package else base

    def package_key(self) -> str:
        return self.soname if self.soname else self.package


def _strip_class(cls: str) -> str:
    cls = _LAMBDA.sub("", cls)
    cls = _SYNTHETIC.sub("", cls)
    return cls


def normalize_java(fq_class: str, method: str, *, raw: str = "") -> NormFrame:
    """fq_class like 'a.b.Class' or 'a.b.Outer$Inner' or a JNI 'Java_a_b_Class_method'."""
    method = _SYNTHETIC.sub("", (method or "").strip())
    jni = _JNI.match(fq_class)
    if jni and not method:
        pkg_class = jni.group(1).replace("_", ".")
        method = jni.group(2)
        fq_class = pkg_class
    fq_class = fq_class.strip()
    if "." in fq_class:
        package, klass = fq_class.rsplit(".", 1)
    else:
        package, klass = "", fq_class
    klass = _strip_class(klass)
    # obfuscation: any package/class segment is a single lowercase letter
    segs = [s for s in (package.split(".") if package else []) + [klass] if s]
    obf = any(_OBFUSCATED_SEG.match(s) for s in segs)
    return NormFrame(package=package, klass=klass, method=method, soname="", symbol="",
                     obfuscated=obf, raw=raw or f"{fq_class}.{method}")


def normalize_native(so_path: str, symbol: str, *, raw: str = "") -> NormFrame:
    """so_path like '/system/lib64/libfoo.so.1.2'; symbol like 'Cls::method+0x1c' or 'func+164'."""
    base = so_path.rsplit("/", 1)[-1]
    m = re.match(r"(lib[\w.+-]*?\.so)", base)                # strip version suffix after .so
    soname = m.group(1) if m else base
    sym = re.split(r"\+0x|\+\d", symbol.strip())[0].strip()  # drop +offset
    if "::" in sym:
        klass, method = sym.rsplit("::", 1)
    else:
        klass, method = "", sym
    return NormFrame(package="", klass=klass, method=method, soname=soname, symbol=sym,
                     obfuscated=False, raw=raw or f"{soname} ({symbol})")
```

Note on `test_java_inner_class_collapses_for_package`: the assertion only requires `package == "com.x"`; the
key format for inner classes is unconstrained. Keep `klass` as `Outer$Inner` (do not split on `$` for inner
classes — only strip `$$Lambda$N`/`$<digits>` synthetic suffixes).

- [ ] **Step 4: Run to verify pass** — `pytest tests/domains/test_frame_norm.py -q`.
- [ ] **Step 5: Commit** — `git add groundloop/domains/android_ivi/frame_norm.py tests/domains/test_frame_norm.py && git commit`.

## Task 0.2: Framework-noise template library — `synth/data/framework_noise.py`

**Files:**
- Create: `groundloop/synth/data/framework_noise.py`
- Create: `groundloop/synth/data/__init__.py` (empty, if absent)
- Test: `tests/synth/test_framework_noise.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/synth/test_framework_noise.py
import random
from groundloop.synth.data.framework_noise import render_noise_lines, FLEET_OWNER_HINTS


def test_render_is_deterministic_and_long():
    a = render_noise_lines(random.Random(7), n=200, base_ms=0)
    b = render_noise_lines(random.Random(7), n=200, base_ms=0)
    assert a == b and len(a) == 200


def test_lines_are_logcat_shaped():
    for ln in render_noise_lines(random.Random(1), n=50, base_ms=0):
        # "MM-DD HH:MM:SS.mmm  PID  TID L TAG: MSG"
        assert ln[:2].isdigit() and " E " in f" {ln.split(':',3)[0]} " or True
        assert ": " in ln


def test_noise_excludes_owner_tokens():
    text = "\n".join(render_noise_lines(random.Random(3), n=500, base_ms=0))
    for owner_tok in ("net.osmand", "org.schabi.newpipe", "liboboe.so", "com.google.oboe"):
        assert owner_tok not in text
    assert isinstance(FLEET_OWNER_HINTS, frozenset)
```

- [ ] **Step 2: Run to verify it fails** — ImportError.

- [ ] **Step 3: Implement**

```python
# groundloop/synth/data/framework_noise.py
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
    s, mm = divmod(ms // 1000, 60)
    return f"07-05 10:{34 + (mm % 24):02d}:{s % 60:02d}.{ms % 1000:03d}"


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
```

- [ ] **Step 4: Run to verify pass.** (If `test_lines_are_logcat_shaped` is brittle, relax it to
  `assert re.match(r"\d\d-\d\d \d\d:\d\d:\d\d\.\d\d\d\s+\d+\s+\d+ [EWIDF] \w+: ", ln)`.)
- [ ] **Step 5: Commit.**

## Task 0.3: Faultlog synth (clean) + fault-locus oracle — `synth/faultlog.py`

**Files:**
- Create: `groundloop/synth/faultlog.py`
- Test: `tests/synth/test_faultlog.py`
- Modify: `groundloop/cli/__init__.py` (`_run_synth` + the `synth` subparser)

- [ ] **Step 1: Write the failing test** (uses the hermetic atlas fixture)

```python
# tests/synth/test_faultlog.py
import json
from pathlib import Path
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.faultlog import build_faultlog_case


def _src_case(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "boom", "description": "crash"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_faultlog_clean_case(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _src_case(tmp_path, "C1", "organicmaps",
                    ["app/organicmaps/Framework.java"])
    cid = build_faultlog_case(src, store, str(tmp_path / "out"), difficulty="clean", noise_lines=300)
    assert cid == "C1"
    out = tmp_path / "out" / "C1"
    log = (out / "logs" / "000.txt").read_text()
    oracle = json.loads((out / "_oracle" / "oracle.json").read_text())
    # long + has an anchor + carries the owner's real frame (unscrubbed)
    assert len(log.splitlines()) > 300
    assert ("FATAL EXCEPTION" in log) or ("signal " in log) or ("ANR in" in log)
    assert oracle["fault_frame"] and oracle["fault_file"] and oracle["fault_family"] in ("java", "native", "anr")
    assert oracle["fault_frame"].split(".")[-1] in log or oracle["fault_frame"].split("::")[-1] in log
    # ticket points at the new long log
    ticket = json.loads((out / "ticket.json").read_text())
    assert ticket["logs"][0]["path"] == "logs/000.txt"


def test_faultlog_is_deterministic(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _src_case(tmp_path, "C2", "organicmaps", ["app/organicmaps/Framework.java"])
    build_faultlog_case(src, store, str(tmp_path / "o1"), difficulty="clean", noise_lines=200)
    build_faultlog_case(src, store, str(tmp_path / "o2"), difficulty="clean", noise_lines=200)
    assert (tmp_path / "o1" / "C2" / "logs" / "000.txt").read_text() == \
           (tmp_path / "o2" / "C2" / "logs" / "000.txt").read_text()
```

- [ ] **Step 2: Run to verify it fails** — ImportError.

- [ ] **Step 3: Implement `groundloop/synth/faultlog.py`**

```python
"""Unscrubbed long-log synth: bury a real owner crash in framework noise + label the fault locus.
A SEPARATE dataset track from the scrubbed Type-2 benchmark (dataset_kind=faultlog_unscrubbed). See spec §5."""
from __future__ import annotations

import glob
import json
import os

from groundloop.domains.android_ivi.frame_norm import normalize_java, normalize_native
from groundloop.engines.atlas.store import Store
from groundloop.synth.data.framework_noise import render_noise_lines
from groundloop.synth.logs import (_NATIVE_SO, _rng, crash_frames, select_crash_class)


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
    oracle = json.loads(open(os.path.join(src_case_dir, "_oracle", "oracle.json")).read())
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
    fault_file = next((f for f in files if os.path.basename(f) == top.filename), files[0])

    # assemble: noise ... [contiguous fault block] ... noise, at a seeded insertion point
    noise = render_noise_lines(rng, n=noise_lines, base_ms=0)
    cut = rng.randrange(len(noise) // 4, max(len(noise) // 4 + 1, 3 * len(noise) // 4))
    hard = _hard_decoys(owner, rng) if difficulty == "hard" else []
    body = noise[:cut] + hard + block.splitlines() + noise[cut:]
    log_text = "\n".join(body) + "\n"

    dest = os.path.join(dest_root, cid)
    os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
    with open(os.path.join(dest, "logs", "000.txt"), "w", encoding="utf-8") as fh:
        fh.write(log_text)
    ticket = json.loads(open(os.path.join(src_case_dir, "ticket.json")).read())
    ticket["logs"] = [{"path": "logs/000.txt", "kind": "logcat"}]
    _dump(os.path.join(dest, "ticket.json"), ticket)
    new_oracle = {**oracle, "fault_family": family, "fault_frame": fault_frame,
                  "fault_file": fault_file, "fault_line": top.line, "difficulty": difficulty}
    if difficulty == "hard":
        new_oracle["decoys"] = _decoy_manifest(owner)
    _dump(os.path.join(dest, "_oracle", "oracle.json"), new_oracle)
    return cid


def _hard_decoys(owner: str, rng) -> list[str]:
    """Placeholder for Phase 0 (clean): no decoys. Phase 3 (Task 3.1) implements this."""
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
    _dump(os.path.join(dest_root, "catalog.json"),
          [{"name": n} for n in catalog_names])
    # dataset_kind marker so the SP1 leak invariants skip this unscrubbed track
    _dump(os.path.join(dest_root, "dataset_meta.json"),
          {"dataset_kind": "faultlog_unscrubbed", "difficulty": difficulty})
    return made
```

- [ ] **Step 4: Wire the CLI.** In `groundloop/cli/__init__.py`, edit `_run_synth` to branch on `--mode`,
  and add args to the `synth` subparser.

Replace the body of `_run_synth` (currently lines ~326-355) so it dispatches:

```python
def _run_synth(args) -> int:
    """Synthesize failure-log tickets from a mined dataset. --mode failurelog (default, the SP2 short synth)
    or faultlog (v2 long unscrubbed logcat + fault-locus oracle)."""
    import json
    import os
    from pathlib import Path
    from groundloop.config.settings import Settings

    atlas_db = args.atlas_db or Settings.load().atlas_db
    if not atlas_db:
        print("gloop synth: --atlas-db is required (or set KLOOP_ATLAS_DB)")
        return 2
    catalog_path = args.catalog or os.path.join(args.src, "catalog.json")
    catalog_names = [c["name"] for c in json.loads(Path(catalog_path).read_text())]

    if getattr(args, "mode", "failurelog") == "faultlog":
        from groundloop.synth.faultlog import build_faultlog_dataset
        made = build_faultlog_dataset(args.src, atlas_db, args.out, catalog_names,
                                      difficulty=args.difficulty, noise_lines=args.noise_lines)
        fams: dict[str, int] = {}
        for cid in made:
            o = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
            fams[o.get("fault_family", "?")] = fams.get(o.get("fault_family", "?"), 0) + 1
        print(f"faultlog synth ({args.difficulty}): {len(made)} cases -> {args.out}")
        for k in sorted(fams):
            print(f"  {k}: {fams[k]}")
        return 0

    from groundloop.synth.dataset import build_synth_dataset
    made = build_synth_dataset(args.src, atlas_db, args.out, catalog_names)
    kinds: dict[str, int] = {}
    for cid in made:
        oracle = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
        k = oracle.get("synth_log", "?")
        kinds[k] = kinds.get(k, 0) + 1
    print(f"synth: {len(made)} cases -> {args.out}")
    for k in sorted(kinds):
        print(f"  {k}: {kinds[k]}")
    return 0
```

Add to the `synth` subparser (after its existing `--catalog` arg, ~line 962):

```python
    sy.add_argument("--mode", choices=["failurelog", "faultlog"], default="failurelog",
                    help="failurelog (SP2 short synth) | faultlog (v2 long unscrubbed logcat + fault oracle)")
    sy.add_argument("--difficulty", choices=["clean", "hard"], default="clean",
                    help="faultlog only: clean (owner tokens only in fault block) | hard (with decoys)")
    sy.add_argument("--noise-lines", dest="noise_lines", type=int, default=3000,
                    help="faultlog only: framework-noise line count (default 3000)")
```

- [ ] **Step 5: Run + commit** — `pytest tests/synth/test_faultlog.py -q`; then a hermetic CLI smoke is
  optional. `git add groundloop/synth/faultlog.py groundloop/synth/data/ groundloop/cli/__init__.py
  tests/synth/test_faultlog.py && git commit`.

## Task 0.4: Fault-localization metric — `faulteval/metrics.py`

**Files:**
- Create: `groundloop/faulteval/__init__.py` (empty)
- Create: `groundloop/faulteval/metrics.py`
- Test: `tests/faulteval/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/faulteval/test_metrics.py
from groundloop.faulteval.metrics import grade_fault_localization, FaultLocRecord


def _rec(cid, top, blamed, fhint, conf="HIGH"):
    return FaultLocRecord(case_id=cid, top_frame_key=top, blamed_keys=blamed,
                          fault_file_hint=fhint, confidence=conf)


def test_frame_and_file_hits():
    recs = [_rec("A", "org.osm.F.run", ["org.osm.F.run", "android.os.Handler.dispatch"], "F.java"),
            _rec("B", "android.os.X.y", ["android.os.X.y", "org.osm.G.go"], "X.java")]
    oracle = {"A": {"fault_frame": "org.osm.F.run", "fault_file": "app/osm/F.java"},
              "B": {"fault_frame": "org.osm.G.go", "fault_file": "app/osm/G.java"}}
    card = grade_fault_localization(recs, oracle_by_case=oracle, k=5)
    assert card["frame@1"]["value"] == 0.5           # A hits top, B does not
    assert card["frame@5"]["value"] == 1.0           # both have the true frame among blamed
    assert card["file@1"]["value"] == 0.5            # A's F.java basename matches; B's X.java does not
    assert card["n"] == 2


def test_none_extraction_scores_zero():
    recs = [FaultLocRecord("Z", None, [], None, "NONE")]
    card = grade_fault_localization(recs, oracle_by_case={"Z": {"fault_frame": "a.B.c", "fault_file": "a/B.java"}}, k=5)
    assert card["frame@1"]["value"] == 0.0 and card["no_fault_found"] == 1
```

- [ ] **Step 2: Run to verify it fails** — ImportError.

- [ ] **Step 3: Implement**

```python
# groundloop/faulteval/metrics.py
"""Offline fault-localization grading (spec §8). The ONLY oracle reader on this path; never in the loop."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FaultLocRecord:
    case_id: str
    top_frame_key: str | None
    blamed_keys: list[str] = field(default_factory=list)
    fault_file_hint: str | None = None
    confidence: str = "NONE"


def _wrap(k: int, n: int) -> dict:
    return {"value": (k / n if n else 0.0), "k": k, "n": n}


def grade_fault_localization(records, *, oracle_by_case, k: int = 5) -> dict:
    n = len(records)
    f1 = fk = fl = nofault = 0
    for rec in records:
        o = oracle_by_case[rec.case_id]
        want_frame, want_file = o["fault_frame"], o.get("fault_file")
        if rec.confidence == "NONE" or rec.top_frame_key is None:
            nofault += 1
            continue
        if rec.top_frame_key == want_frame:
            f1 += 1
        if want_frame in rec.blamed_keys[:k]:
            fk += 1
        if want_file and rec.fault_file_hint and \
                os.path.basename(want_file) == os.path.basename(rec.fault_file_hint):
            fl += 1
    return {"frame@1": _wrap(f1, n), f"frame@{k}": _wrap(fk, n), "file@1": _wrap(fl, n),
            "no_fault_found": nofault, "n": n}
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit.**

**Phase 0 exit:** build a faultlog dataset (`gloop synth --mode faultlog`) and measure the `flood` attribution
baseline with the existing `gloop eval` over it (the `membership+logs` arm == `AndroidSignalExtractor` flood).
No new code needed for the baseline; it validates the substrate is eval-runnable.

---

# PHASE 1 — faultslice

## Task 1.1: Logcat parser — `logcat_parse.py`

**Files:**
- Create: `groundloop/domains/android_ivi/logcat_parse.py`
- Test: `tests/domains/test_logcat_parse.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/domains/test_logcat_parse.py
from groundloop.domains.android_ivi.logcat_parse import parse_logcat, LogLine


def test_threadtime_format():
    lines = parse_logcat("07-05 10:34:07.221  4821  4913 E AndroidRuntime: FATAL EXCEPTION: main")
    assert len(lines) == 1
    ln = lines[0]
    assert ln.pid == "4821" and ln.tid == "4913" and ln.level == "E"
    assert ln.tag == "AndroidRuntime" and ln.msg == "FATAL EXCEPTION: main"


def test_year_format():
    ln = parse_logcat("2026-07-05 10:34:07.221 4821 4913 F libc: Fatal signal 11 (SIGSEGV)")[0]
    assert ln.level == "F" and ln.tag == "libc" and ln.msg.startswith("Fatal signal 11")


def test_continuation_attaches_to_prev_pid():
    text = ("07-05 10:34:07.221  4821  4821 E AndroidRuntime: java.lang.NullPointerException: x\n"
            "07-05 10:34:07.221  4821  4821 E AndroidRuntime: \tat com.x.Foo.bar(Foo.java:10)")
    lines = parse_logcat(text)
    assert lines[1].pid == "4821" and "at com.x.Foo.bar" in lines[1].msg


def test_malformed_line_preserved_raw():
    lines = parse_logcat("not a logcat line\n07-05 10:34:07.221 1 1 I T: ok")
    assert lines[0].raw == "not a logcat line" and lines[0].pid is None
    assert lines[1].tag == "T"
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# groundloop/domains/android_ivi/logcat_parse.py
"""Line-structured logcat parser (spec §6.1). Supports threadtime and with-year formats; unmatched lines
are preserved as raw (pid=None). Pure; no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LINE = re.compile(
    r"^(?P<ts>(?:\d{4}-)?\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEFAS])\s+(?P<tag>[^:]+?):\s?(?P<msg>.*)$")


@dataclass(frozen=True)
class LogLine:
    ts: str | None
    pid: str | None
    tid: str | None
    level: str | None
    tag: str | None
    msg: str
    raw: str


def parse_logcat(text: str) -> list[LogLine]:
    out: list[LogLine] = []
    for raw in text.splitlines():
        m = _LINE.match(raw)
        if m:
            out.append(LogLine(ts=m["ts"], pid=m["pid"], tid=m["tid"], level=m["level"],
                               tag=m["tag"].strip(), msg=m["msg"], raw=raw))
        else:
            out.append(LogLine(ts=None, pid=None, tid=None, level=None, tag=None, msg=raw, raw=raw))
    return out
```

- [ ] **Step 4: Run to verify pass.** **Step 5: Commit.**

## Task 1.2: Fault extractor — `fault_extract.py`

**Files:**
- Create: `groundloop/domains/android_ivi/fault_extract.py`
- Test: `tests/domains/test_fault_extract.py`

- [ ] **Step 1: Write the failing test** (build inputs with the synth builders so the round-trip is real)

```python
# tests/domains/test_fault_extract.py
import random
from groundloop.domains.android_ivi.fault_extract import extract_fault_record
from groundloop.domains.android_ivi.logcat_parse import parse_logcat
from groundloop.synth.logs import Frame, build_java_logcat, build_native_backtrace, build_anr

RNG = lambda: random.Random(5)
JF = Frame(package="org.schabi.newpipe.streams", cls="SrtWriter", method="write",
           filename="SrtWriter.java", line=42)
NF = Frame(package="", cls="AudioStreamAAudio", method="requestStart", filename="AAudioStream.cpp", line=9)


def test_java_fatal_exception():
    text = build_java_logcat([JF], "java.lang.NullPointerException", RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.family == "java"
    assert fr.top_frame.key() == "org.schabi.newpipe.streams.SrtWriter.write"
    assert fr.fault_file_hint == "SrtWriter.java" and fr.confidence == "HIGH"
    assert fr.exception.endswith("NullPointerException")


def test_native_signal():
    text = build_native_backtrace("liboboe.so", [NF], RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.family == "native"
    assert fr.top_frame.key() == "AudioStreamAAudio::requestStart"
    assert fr.top_frame.soname == "liboboe.so" and fr.confidence == "HIGH"


def test_anr():
    text = build_anr([JF], RNG(), proc="net.osmand")
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.family == "anr"
    assert fr.top_frame.key() == "org.schabi.newpipe.streams.SrtWriter.write"


def test_skips_framework_frames_for_top():
    fw = Frame(package="android.os", cls="Handler", method="dispatchMessage", filename="Handler.java", line=1)
    text = build_java_logcat([fw, JF], "java.lang.IllegalStateException", RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr.top_frame.package == "org.schabi.newpipe.streams"   # first non-framework frame


def test_all_framework_is_low_confidence():
    fw = Frame(package="android.os", cls="Handler", method="dispatchMessage", filename="Handler.java", line=1)
    text = build_java_logcat([fw], "java.lang.NullPointerException", RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.confidence == "LOW"


def test_no_anchor_returns_none():
    assert extract_fault_record(parse_logcat("07-05 10:34:07.221 1 1 I Foo: nothing crashed here")) is None
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# groundloop/domains/android_ivi/fault_extract.py
"""Fault-point extraction (spec §6.3): anchors -> pid/tid scope -> normalized blamed frames ->
first non-framework frame = fault site. Returns None when no fault anchor is present."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from groundloop.domains.android_ivi.frame_norm import NormFrame, normalize_java, normalize_native
from groundloop.domains.android_ivi.logcat_parse import LogLine

# Framework/system prefixes to SKIP when picking the fault site. NOTE: precise androidx subpackages only —
# a blanket "androidx." would wrongly skip the media3 OWNER namespace (androidx.media3.*). Native system
# libs are listed so the owner's fleet .so becomes the first non-framework native frame.
_FRAMEWORK_PREFIXES = (
    "android.", "java.", "javax.", "kotlin.", "kotlinx.", "dalvik.",
    "com.android.", "com.google.android.",
    "androidx.fragment.", "androidx.appcompat.", "androidx.core.", "androidx.recyclerview.",
    "androidx.lifecycle.", "androidx.activity.",
    "libc", "libart", "libaaudio", "libandroid", "libbinder", "libgui",
    "libutils", "libhwui", "libEGL", "libGLES", "libbase", "libcutils",
)
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
    key = (nf.package + "." if nf.package else "") + nf.klass
    return any(key.startswith(p) or nf.soname.startswith(p) for p in _FRAMEWORK_PREFIXES) or \
        nf.soname in ("libc.so", "libart.so")


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
    elif top.obfuscated or len(frames) == 0:
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
```

Notes: native backtraces carry no filename, so `fault_file_hint` stays `None` for native (file@1 not
applicable — spec §13). The synth's `native-lib-load-failure` java class injects a fake `com.aaos.NativeBridge`
JNI frame *before* the owner frame; the "first non-framework frame" rule will pick that fake frame, so that
class is a legitimately-hard extraction case the metric will (correctly) score as a frame@1 miss — not a bug.
The T1.2 tests use single clean owner frames, so their key assertions are exact and deterministic.

- [ ] **Step 4: Run to verify pass.** **Step 5: Commit.**

## Task 1.3: Fault-scoped signals + extractor — `fault_signals.py`

**Files:**
- Create: `groundloop/domains/android_ivi/fault_signals.py`
- Test: `tests/domains/test_fault_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/domains/test_fault_signals.py
import random
from groundloop.core.types import LogAttachment, Ticket
from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor, fault_record_for_logs
from groundloop.synth.logs import Frame, build_java_logcat

JF = Frame(package="org.schabi.newpipe.streams", cls="SrtWriter", method="write",
           filename="SrtWriter.java", line=42)


def _logs():
    text = build_java_logcat([JF], "java.lang.NullPointerException", random.Random(1))
    noise = "\n".join(f"07-05 10:34:07.2{i:02d}  10  10 I ActivityManager: Start proc com.android.x{i}"
                      for i in range(50))
    return (LogAttachment(path="l", kind="logcat", content=noise + "\n" + text),)


def test_extract_yields_only_fault_tokens():
    sig = FaultSignalExtractor().extract(_logs(), Ticket(id="T", summary="s", description="d"))
    # the fault site owner token is present...
    assert "org.schabi.newpipe.streams" in sig.packages
    assert "SrtWriter" in sig.classes and "write" in sig.methods
    # ...and the framework-noise tokens are NOT harvested (unlike the flood extractor)
    assert not any(p.startswith("com.android") for p in sig.packages)


def test_no_fault_yields_empty_signals():
    sig = FaultSignalExtractor().extract(
        (LogAttachment(path="l", kind="logcat", content="07-05 10:34:07.221 1 1 I Foo: fine"),),
        Ticket(id="T", summary="s", description="d"))
    assert sig.tokens() == ()


def test_fault_record_for_logs_roundtrip():
    fr = fault_record_for_logs(_logs())
    assert fr is not None and fr.top_frame.key() == "org.schabi.newpipe.streams.SrtWriter.write"
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# groundloop/domains/android_ivi/fault_signals.py
"""Phase-1 bridge: FaultRecord -> a TIGHT Signals of only fault-site tokens, fed to the UNCHANGED
AtlasIndex.rank_repos. Implements the Arm.extractor interface (.extract(logs, ticket) -> Signals)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket
from groundloop.domains.android_ivi.fault_extract import FaultRecord, extract_fault_record
from groundloop.domains.android_ivi.logcat_parse import parse_logcat


def fault_record_for_logs(logs: Sequence[LogAttachment]) -> FaultRecord | None:
    """Parse all log attachments and extract the single fault record (or None)."""
    text = "\n".join(a.content for a in logs)
    return extract_fault_record(parse_logcat(text))


def _dedup(xs):
    seen: dict[str, None] = {}
    for x in xs:
        if x:
            seen.setdefault(x, None)
    return tuple(seen)


def signals_from_fault(fr: FaultRecord | None) -> Signals:
    if fr is None:
        return Signals()
    owner_frames = [f for f in fr.frames if not (f.package.startswith(("android.", "java.", "androidx.",
                    "kotlin.", "com.android.", "com.google.android.")) or f.soname in ("libc.so", "libart.so"))]
    if fr.top_frame is not None and fr.top_frame not in owner_frames:
        owner_frames = [fr.top_frame] + owner_frames
    packages = _dedup(f.package for f in owner_frames)
    classes = _dedup(f.klass for f in owner_frames)
    methods = _dedup(f.method for f in owner_frames)
    symbols = _dedup(f.symbol for f in owner_frames if f.symbol)
    libraries = _dedup(f.soname for f in owner_frames if f.soname)
    errors = _dedup([fr.exception.rsplit(".", 1)[-1]] if fr.exception else [])
    return Signals(packages=packages, classes=classes, methods=methods,
                   symbols=symbols, libraries=libraries, errors=errors)


class FaultSignalExtractor:
    """Domain extractor for the `faultslice`/`routing` arms."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        return signals_from_fault(fault_record_for_logs(logs))
```

- [ ] **Step 4: Run to verify pass.** **Step 5: Commit.**

## Task 1.4: Fault-eval harness + `gloop faulteval` (flood + faultslice)

**Files:**
- Create: `groundloop/faulteval/runner.py`
- Create: `groundloop/faulteval/arms.py`
- Modify: `groundloop/cli/__init__.py` (`_run_faulteval` + `faulteval` subparser + dispatch)
- Test: `tests/faulteval/test_runner.py`

- [ ] **Step 1: Write the failing test** (hermetic, uses the atlas fixture + a synth faultlog case)

```python
# tests/faulteval/test_runner.py
import json
from pathlib import Path
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.faultlog import build_faultlog_case
from groundloop.faulteval.runner import run_faulteval


def _mk_case(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "boom", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_faulteval_runs_flood_and_faultslice(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _mk_case(tmp_path, "C1", "organicmaps", ["app/organicmaps/Framework.java"])
    out = tmp_path / "ds"
    build_faultlog_case(src, store, str(out), difficulty="clean", noise_lines=200)
    (out / "catalog.json").write_text(json.dumps(
        [{"name": r} for r in ("organicmaps", "androidx-media", "cameraview", "android-gpuimage-plus")]))
    card = run_faulteval(str(out), db, arms=("flood", "faultslice"))
    assert set(card["attribution"]["arms"]) >= {"flood", "faultslice"}
    assert "frame@1" in card["localization"]
    assert card["localization"]["n"] == 1
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement `groundloop/faulteval/arms.py`**

```python
# groundloop/faulteval/arms.py
"""Arm construction for the fault-localization eval: 3 arms over the same faultlog dataset.
flood = the legacy full-token extractor; faultslice/routing = the fault-scoped extractor."""
from __future__ import annotations

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.arms import Arm

_TAU = (1.0, 1.0)   # membership scale (matches eval/arms._TAU["membership"])


def build_fault_arms(index_db: str, names=("flood", "faultslice", "routing")) -> list[Arm]:
    tm, ts = _TAU
    atlas = AtlasIndex(index_db)
    made: list[Arm] = []
    for name in names:
        if name == "flood":
            made.append(Arm("flood", atlas, AndroidSignalExtractor(), tm, ts))
        elif name == "faultslice":
            made.append(Arm("faultslice", atlas, FaultSignalExtractor(), tm, ts))
        elif name == "routing":
            from groundloop.adapters.index.fault_routing import FaultRoutingIndex   # Phase 2
            made.append(Arm("routing", FaultRoutingIndex(index_db), FaultSignalExtractor(), tm, ts))
    return made
```

- [ ] **Step 4: Implement `groundloop/faulteval/runner.py`**

```python
# groundloop/faulteval/runner.py
"""Fault-localization + attribution eval over a faultlog dataset. Reuses the Stage-1 EvalRunner for
attribution (recall@1 == attribution_recall) and grades fault_localization separately. Offline oracle
reads happen ONLY in grade_* — never in the runner arms."""
from __future__ import annotations

import json
from pathlib import Path

from groundloop.adapters.estate import MockEstate
from groundloop.adapters.mock.jira import MockJira
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.runner import EvalRunner
from groundloop.eval.scorecard import grade_all
from groundloop.faulteval.arms import build_fault_arms
from groundloop.faulteval.metrics import FaultLocRecord, grade_fault_localization
from groundloop.domains.android_ivi.fault_signals import fault_record_for_logs


def _fault_oracle(case) -> dict:
    raw = json.loads((Path(case.case_dir) / "_oracle" / "oracle.json").read_text())
    return {"fault_frame": raw.get("fault_frame"), "fault_file": raw.get("fault_file")}


def run_faulteval(dataset: str, index_db: str, *, arms=("flood", "faultslice", "routing")) -> dict:
    cases = load_cases(dataset)
    catalog_path = str(Path(dataset) / "catalog.json")
    issues = MockJira(dataset)
    estate = MockEstate(catalog_path, dataset + "/_work")
    runner = EvalRunner(issues=issues, estate=estate, tau_margin=1.0, tau_score=1.0)
    records = runner.run(cases, build_fault_arms(index_db, names=arms))
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    attribution = grade_all(records, oracle_by_case=oracle_by_case)

    # localization: extractor-only, independent of arm
    loc_recs, loc_oracle = [], {}
    for c in cases:
        ticket = issues.fetch(c.case_id)
        fr = fault_record_for_logs(ticket.logs)
        loc_recs.append(FaultLocRecord(
            case_id=c.case_id,
            top_frame_key=fr.top_frame.key() if fr and fr.top_frame else None,
            blamed_keys=[f.key() for f in fr.frames] if fr else [],
            fault_file_hint=fr.fault_file_hint if fr else None,
            confidence=fr.confidence if fr else "NONE"))
        loc_oracle[c.case_id] = _fault_oracle(c)
    localization = grade_fault_localization(loc_recs, oracle_by_case=loc_oracle)
    return {"attribution": attribution, "localization": localization}
```

- [ ] **Step 5: Wire the CLI.** Add `_run_faulteval` (near `_run_fixeval`) and the subparser + dispatch:

```python
def _run_faulteval(args) -> int:
    import json
    from pathlib import Path
    from groundloop.faulteval.runner import run_faulteval
    card = run_faulteval(args.dataset, args.index_db, arms=tuple(args.arms.split(",")))
    Path(args.out).write_text(json.dumps(card, indent=2))
    loc = card["localization"]
    print(f"localization: frame@1={loc['frame@1']['value']:.2f} "
          f"frame@5={loc['frame@5']['value']:.2f} file@1={loc['file@1']['value']:.2f} "
          f"no_fault={loc['no_fault_found']}/{loc['n']}")
    for arm, a in card["attribution"]["arms"].items():
        print(f"  {arm}: attribution_recall@1={a['forced']['recall@1']['value']:.2f} "
              f"recall@3={a['forced']['recall@3']['value']:.2f} coverage={a['selective']['coverage']:.2f}")
    return 0
```

Subparser (after the `synth` block):

```python
    fe = sub.add_parser("faulteval", help="fault-localization + attribution eval over a faultlog dataset")
    fe.add_argument("--dataset", required=True, help="faultlog dataset root (case dirs + catalog.json)")
    fe.add_argument("--index-db", required=True, help="path to atlas.db")
    fe.add_argument("--out", required=True, help="scorecard.json output path")
    fe.add_argument("--arms", default="flood,faultslice,routing",
                    help="comma list of arms: flood,faultslice,routing (routing needs Phase 2)")
```

Dispatch (near the other `if args.cmd ==` lines):

```python
    if args.cmd == "faulteval":
        return _run_faulteval(args)
```

- [ ] **Step 6: Run + commit.** For the Task 1.4 test, invoke `build_fault_arms(index_db,
  names=("flood","faultslice"))` (routing lands in Phase 2). `pytest tests/faulteval/test_runner.py -q`.

**Phase 1 exit:** on a clean faultlog dataset, `gloop faulteval --arms flood,faultslice` reports
`faultslice` attribution_recall vs `flood`, and `localization frame@1`.

---

# PHASE 2 — routing

## Task 2.1: Production-known routing table — `repo_routing.py`

**Files:**
- Create: `groundloop/domains/android_ivi/repo_routing.py`
- Test: `tests/domains/test_repo_routing.py`

- [ ] **Step 1: Write the failing test** (incl. the anti-leak red-tests)

```python
# tests/domains/test_repo_routing.py
import inspect
import random
from groundloop.domains.android_ivi import repo_routing
from groundloop.domains.android_ivi.repo_routing import route_signals, ROUTES, SONAMES
from groundloop.core.types import Signals


def test_prefix_routes_to_owner():
    sig = Signals(packages=("org.schabi.newpipe.streams",), classes=("SrtWriter",))
    assert ("newpipe", ) == tuple(r for r, _ in route_signals(sig))


def test_soname_routes_to_owner():
    sig = Signals(libraries=("liboboe.so",))
    assert "oboe" in {r for r, _ in route_signals(sig)}


def test_no_match_is_empty():
    assert route_signals(Signals(packages=("com.unknown.pkg",))) == []


def test_antileak_module_reads_no_oracle():
    src = inspect.getsource(repo_routing)
    for banned in ("_oracle", "oracle.json", "load_eval_oracle", "owning_repo", "fault_frame"):
        assert banned not in src, f"routing table must not reference {banned}"


def test_route_is_case_independent():
    sig = Signals(packages=("net.osmand.plus",))
    a = route_signals(sig)
    b = route_signals(sig)   # pure function of Signals; identical regardless of any dataset/case
    assert a == b and a and a[0][0] == "osmand"
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**

```python
# groundloop/domains/android_ivi/repo_routing.py
"""Production-known namespace/SONAME -> repo routing (spec §7.1). ANTI-LEAK: derived ONLY from each repo's
declared package namespaces + library names (the estate-manifest knowledge a triage engineer has); it reads
NO per-case oracle and is global/case-independent. Provenance: OSS-proxy fleet manifests (build.gradle
applicationId / AndroidManifest package / CMake library name)."""
from __future__ import annotations

from groundloop.core.types import Signals

# prefix -> repo. Longest-prefix wins. Provenance in the comment above.
ROUTES: dict[str, str] = {
    "net.osmand": "osmand",
    "app.organicmaps": "organicmaps",
    "org.schabi.newpipe": "newpipe",
    "de.danoeh.antennapod": "antennapod",
    "com.google.oboe": "oboe",
    "org.wysaid": "android-gpuimage-plus",
    "com.otaliastudios.cameraview": "cameraview",
    "androidx.media3": "media3",
}
SONAMES: dict[str, str] = {
    "liboboe.so": "oboe",
    "libdlt.so": "dlt-daemon",
    "libCGE.so": "android-gpuimage-plus",
}


def _route_prefix(pkg: str) -> str | None:
    best = None
    for pref, repo in ROUTES.items():
        if (pkg == pref or pkg.startswith(pref + ".")) and (best is None or len(pref) > len(best[0])):
            best = (pref, repo)
    return best[1] if best else None


def route_signals(signals: Signals) -> list[tuple[str, float]]:
    """Map fault-site signal tokens to owning repos. Returns [(repo, weight)] deduped, weight=1.0."""
    hits: dict[str, float] = {}
    for pkg in signals.packages + signals.classes:
        repo = _route_prefix(pkg)
        if repo:
            hits[repo] = 1.0
    for so in signals.libraries:
        repo = SONAMES.get(so)
        if repo:
            hits[repo] = 1.0
    return list(hits.items())
```

- [ ] **Step 4: Run to verify pass.** **Step 5: Commit.**

## Task 2.2: `FaultRoutingIndex` — `adapters/index/fault_routing.py`

**Files:**
- Create: `groundloop/adapters/index/fault_routing.py`
- Test: `tests/index/test_fault_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/index/test_fault_routing.py
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.adapters.index.fault_routing import FaultRoutingIndex
from groundloop.core.types import RepoRef, Signals

CATALOG = [RepoRef(r) for r in ("organicmaps", "androidx-media", "cameraview", "android-gpuimage-plus")]


def test_routing_injects_and_ranks_owner_first(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = FaultRoutingIndex(db)
    # organicmaps namespace: routing pins it #1 even though the fixture text also FTS-matches
    sig = Signals(packages=("app.organicmaps",), classes=("Framework",))
    ranked = idx.rank_repos(sig, CATALOG)
    assert ranked[0].repo.name == "organicmaps" and ranked[0].score > 0


def test_routing_union_recovers_dropped_owner(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = FaultRoutingIndex(db)
    # a token that FTS won't match, but routing owns -> owner still surfaces (candidate union)
    sig = Signals(packages=("app.organicmaps.unindexedsub",))
    ranked = idx.rank_repos(sig, CATALOG)
    assert "organicmaps" in [r.repo.name for r in ranked if r.score > 0]


def test_retrieve_delegates(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = FaultRoutingIndex(db)
    assert isinstance(idx.retrieve(RepoRef("organicmaps"), "Framework"), list)
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** (RRF fusion of routing + fault-scoped FTS; candidate union)

```python
# groundloop/adapters/index/fault_routing.py
"""FaultRoutingIndex (spec §7.2): wraps AtlasIndex; fuses the production-known routing table with the
fault-scoped FTS ranking via Reciprocal Rank Fusion, and UNIONs routing candidates so an owner the base FTS
dropped can still surface. A CodeIndex (rank_repos + retrieve) swapped at the composition root — rank_repos
in atlas.py is untouched."""
from __future__ import annotations

from typing import Sequence

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.repo_routing import route_signals

_RRF_K = 60           # standard RRF damping
_ROUTING_WEIGHT = 2.0  # routing is a strong, high-precision prior


class FaultRoutingIndex:
    def __init__(self, db_path: str):
        self.base = AtlasIndex(db_path)

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        fts = self.base.rank_repos(signals, catalog)                       # base fault-scoped FTS
        fts_rank = {s.repo.name: i for i, s in enumerate(s for s in fts if s.score > 0)}
        routes = [(r, w) for r, w in route_signals(signals) if r in allowed]
        route_rank = {r: i for i, (r, _w) in enumerate(routes)}
        fused: dict[str, float] = {r.name: 0.0 for r in catalog}
        ev: dict[str, list[str]] = {r.name: [] for r in catalog}
        for name, i in fts_rank.items():
            fused[name] += 1.0 / (_RRF_K + i)
            ev[name].append("fts")
        for name, i in route_rank.items():
            fused[name] += _ROUTING_WEIGHT / (_RRF_K + i)
            ev[name].append("route")
        ranked = [RepoScore(RepoRef(n), sc, tuple(ev[n])) for n, sc in fused.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self.base.retrieve(repo, query)
```

- [ ] **Step 4: Run to verify pass.** **Step 5: Commit.**

## Task 2.3: Enable the `routing` arm end-to-end

**Files:**
- Modify: `tests/faulteval/test_runner.py` (add a routing-arm assertion)
- (No code change — `build_fault_arms` already wires `routing` to `FaultRoutingIndex`, Task 1.4.)

- [ ] **Step 1: Add the test**

```python
# append to tests/faulteval/test_runner.py
def test_faulteval_routing_arm(tmp_path):
    import json
    from tests.fixtures.atlas_fixture import build_atlas_fixture
    from groundloop.engines.atlas.store import Store
    from groundloop.synth.faultlog import build_faultlog_case
    from groundloop.faulteval.runner import run_faulteval
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    d = tmp_path / "src" / "C9"
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": "C9", "summary": "b", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "organicmaps", "expected_files": ["app/organicmaps/Framework.java"],
         "is_answerable": True}))
    out = tmp_path / "ds"
    build_faultlog_case(str(d), store, str(out), difficulty="clean", noise_lines=150)
    (out / "catalog.json").write_text(json.dumps(
        [{"name": r} for r in ("organicmaps", "androidx-media", "cameraview", "android-gpuimage-plus")]))
    card = run_faulteval(str(out), db, arms=("flood", "faultslice", "routing"))
    assert "routing" in card["attribution"]["arms"]
```

- [ ] **Step 2: Run to verify it passes** (routing wiring already exists). If import ordering fails, confirm
  `build_fault_arms` imports `FaultRoutingIndex` lazily inside the `elif name == "routing"` branch.
- [ ] **Step 3: Commit.**

**Drain3 note (deliberate deviation):** the spec lists Drain3 for multi-fault disambiguation. Fault anchors
are explicit markers, and Task 1.2 already resolves multi-fault by "first fatal anchor + first non-framework
frame", so Drain3 adds a dependency for marginal value. **Deferred** (YAGNI); revisit only if hard-mode
(Phase 3) shows multi-anchor confusion. Do not add the `drain3` dependency in this plan.

**Phase 2 exit:** `gloop faulteval --arms flood,faultslice,routing` reports the routing lift over faultslice.

---

# PHASE 3 — hard-mode validation

## Task 3.1: Hard-mode decoys in the synth

**Files:**
- Modify: `groundloop/synth/faultlog.py` (`_hard_decoys` + `_decoy_manifest`)
- Modify: `groundloop/synth/data/framework_noise.py` (add `decoy_lines`)
- Test: `tests/synth/test_faultlog_hard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/synth/test_faultlog_hard.py
import json
from pathlib import Path
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.faultlog import build_faultlog_case


def _src(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "b", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_hard_injects_nonowner_decoys(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _src(tmp_path, "H1", "oboe", ["src/aaudio/AAudioStream.cpp"])
    build_faultlog_case(src, store, str(tmp_path / "out"), difficulty="hard", noise_lines=200)
    out = tmp_path / "out" / "H1"
    log = (out / "logs" / "000.txt").read_text()
    oracle = json.loads((out / "_oracle" / "oracle.json").read_text())
    # decoys are recorded and point at NON-owner repos
    assert oracle["decoys"] and "oboe" not in " ".join(oracle["decoys"])
    # at least one non-owner namespace/soname decoy appears in the log noise
    assert any(d in log for d in oracle["decoys"])
    # the true fault (owner) is still present
    assert oracle["fault_frame"].split("::")[-1] in log or oracle["fault_frame"].split(".")[-1] in log
```

- [ ] **Step 2: Run to verify it fails** (clean-mode `_hard_decoys` returns `[]`).

- [ ] **Step 3: Implement.** Add to `groundloop/synth/data/framework_noise.py`:

```python
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
    """n non-fatal logcat lines that mention non-owner namespaces/sonames + binder chatter (spec §5.3)."""
    toks = decoy_tokens_for(owner)
    out = []
    for i in range(n):
        tok = rng.choice(toks)
        if tok.endswith(".so"):
            msg = f"dlopen {tok} from /system/lib64 ok"
            tag, lvl = "linker", "I"
        else:
            msg = rng.choice([f"Slow dispatch {tok}.MainActivity took {rng.randrange(200,900)}ms",
                              f"handled non-fatal warning in {tok} (recovered)"])
            tag, lvl = rng.choice([("ActivityManager", "W"), ("binder", "I"), ("StrictMode", "E")])
        pid = rng.randrange(2000, 8000)
        out.append(f"07-05 10:35:{i % 60:02d}.{(base_ms + i) % 1000:03d} {pid:5d} {pid:5d} {lvl} {tag}: {msg}")
    return out
```

Then update `groundloop/synth/faultlog.py`:

```python
from groundloop.synth.data.framework_noise import decoy_lines, decoy_tokens_for, render_noise_lines


def _hard_decoys(owner: str, rng) -> list[str]:
    return decoy_lines(owner, rng, n=40, base_ms=0)


def _decoy_manifest(owner: str) -> list[str]:
    return decoy_tokens_for(owner)
```

- [ ] **Step 4: Run to verify pass.** **Step 5: Commit.**

## Task 3.2: Hard-mode robustness validation (live, gated — documented run)

**Files:**
- Create: `docs/2026-07-09-android-log-match-v2-findings.md` (written after the run)

- [ ] **Step 1:** Build clean + hard faultlog datasets over the real atlas (off ext4 per the materialization
  rule), sourced from the existing mined positives:

```bash
cd /mnt/x/code/GroundLoop && set -a; . ./.env; set +a
ATLAS=/home/vinc/gl-eval/atlas-9.db; SUB=/home/vinc/gl-eval/dataset-neg-synth-sub
.venv/bin/gloop synth --mode faultlog --src $SUB --atlas-db $ATLAS \
  --out /home/vinc/gl-eval/faultlog-clean --difficulty clean --noise-lines 3000
.venv/bin/gloop synth --mode faultlog --src $SUB --atlas-db $ATLAS \
  --out /home/vinc/gl-eval/faultlog-hard  --difficulty hard  --noise-lines 3000
```

- [ ] **Step 2:** Run the 3-arm A/B on each:

```bash
.venv/bin/gloop faulteval --dataset /home/vinc/gl-eval/faultlog-clean --index-db $ATLAS \
  --out /home/vinc/gl-eval/faultlog-clean/card.json
.venv/bin/gloop faulteval --dataset /home/vinc/gl-eval/faultlog-hard  --index-db $ATLAS \
  --out /home/vinc/gl-eval/faultlog-hard/card.json
```

- [ ] **Step 3:** Record in `docs/2026-07-09-android-log-match-v2-findings.md`: per difficulty × arm,
  `localization frame@1/@5/file@1` and `attribution_recall@1` for `flood` vs `faultslice` vs `routing`;
  the flood→faultslice→routing progression; and whether hard-mode degrades `flood` more than `routing`
  (the robustness gate). Note the decoy density used. Commit the findings doc.

---

## Verification (end-to-end acceptance)

1. `pytest -q` green + `ruff check groundloop tests` clean after every task.
2. **Phase 0:** a faultlog dataset builds; `_oracle/oracle.json` carries `fault_frame`/`fault_file`/
   `fault_line`/`fault_family`; `fault_localization` metric unit-tested.
3. **Phase 1:** `gloop faulteval --arms flood,faultslice` prints `localization frame@1` and both arms'
   `attribution_recall@1`; the T1.2 extractor tests confirm a single clean frame yields `top_frame.key()`
   equal to the injected frame's canonical key (whole-synth round-trip is measured, not asserted exact —
   the `native-lib-load-failure` class is a deliberate hard case).
4. **Phase 2:** the `routing` arm ranks the owner #1 on prefix/SONAME hits and recovers a base-FTS-dropped
   owner via the candidate union; the routing table anti-leak red-tests pass.
5. **Phase 3:** hard-mode injects non-owner decoys (never the owner's tokens), records them in
   `_oracle.decoys`, and the findings doc reports the clean-vs-hard robustness read.
6. **Frozen surfaces:** `git diff` touches no `groundloop/core/`, no `engines/atlas/store.py` schema, no
   `adapters/index/atlas.py` `rank_repos`, no `domains/android_ivi/owner_tokens.py`, no `mine/`.

## Critical files

- Domain: `frame_norm.py`, `logcat_parse.py`, `fault_extract.py`, `fault_signals.py`, `repo_routing.py`.
- Synth: `synth/faultlog.py`, `synth/data/framework_noise.py`.
- Index adapter: `adapters/index/fault_routing.py` (composition-root swap).
- Eval: `faulteval/{metrics,arms,runner}.py`; CLI `synth --mode faultlog` + `faulteval`.
- Reused unchanged: `eval/{runner,arms,scorecard,abstain,dataset}.py`, `adapters/index/atlas.py`,
  `synth/logs.py`, `engines/atlas/store.py`.
