# Type-2 Miner (E1-B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build `groundloop/mine/` — an online (`gh`) miner that harvests closed GitHub issues with a linked merged PR across the 9-repo eval fleet and emits leak-scrubbed defect-ticket cases with a hidden oracle, ready for the E1-C eval harness.

**Architecture:** Pure edge composition (`core/` frozen). A dependency-injected `gh` runner makes the whole pipeline hermetically testable (canned JSON, no network). Flow: `harvest` (GraphQL `closedByPullRequestsReferences`, same-repo filtered, deduped) → `filters` (production-only, single-concern) → `signal.split_issue_body` (prose + log blocks) → `scrub` (per-case oracle-parameterized redaction) → `admit` (leakage post-check that re-runs the real extractor) → `emit` (the exact `gpuimage-352` case layout, hidden metadata nested under `_oracle/`).

**Tech Stack:** Python 3.12, `gh` CLI (via `subprocess`, injected), `tomllib`/`json`, pytest (hermetic via injected gh + `tmp_path`). Reuses `groundloop.domains.android_ivi.signal_extractor.AndroidSignalExtractor` (for the leak post-check), `groundloop.adapters.mock.jira.MockJira` + `tests/conftest.Case` (round-trip test).

**Canonical design:** [`docs/type2-evaluation.md`](../../type2-evaluation.md) §4 (dataset pipeline). Grounded 2026-07-05 (gh shapes, scrubber, schema all code-verified). This is eval stage **E1-B**; the atlas substrate is **E1-A** (done), the eval harness is **E1-C**.

---

## Critical correctness rules (verified against real data / code — do not deviate)

1. **Same-repo closer filter (non-negotiable):** a closing PR can live in a *different* repo (real: NewPipe issue #13476 closed by `NewPipeExtractor` PR #1493). Admit a binding ONLY if `closingPR.repository.nameWithOwner == "<owner>/<name>"`. The surviving repo is `owning_repo`.
2. **Dedup per issue, not per PR:** one merged PR can close several issues (real: AntennaPod PR #8514 closes #8513 and #8512). Each issue is its own case; a PR may recur.
3. **`component` MUST be `""`** in ticket.json (`Ticket.component` "MUST NOT be the owning repo"). Never derive any loop-visible field from the owner/namespace/file.
4. **Case dir name == `ticket.json["id"]`** (MockJira.fetch opens `root/<case_id>/ticket.json`; `id` has no default → KeyError if missing).
5. **`owning_repo` must string-equal a `catalog.json` name AND an atlas.db repo name** (short slug, e.g. `android-gpuimage-plus`), or grader recall@1 is silently always 0.
6. **`expected_files`/`required_apis` are JSON arrays** (a JSON string makes grader iterate characters).
7. **Hidden metadata nests under `_oracle/`** (`provenance.json`, `leakage.json`, `raw/`) so the existing invariant-#4 read-spy (scoped to `_oracle/`) and `load_cases`' "never reads `_oracle/`" cover it for free.
8. **The scrubber is per-case, oracle-parameterized** — `androidx.media3` is an owner token for a media3 case but a KEPT dependency signal for an AntennaPod/NewPipe case. Never a global blocklist.
9. **Leakage post-check re-runs `AndroidSignalExtractor`** over the sanitized text; reject if any owner-unique token survives (the existing invariants only catch the literal repo slug, missing namespace/class/method leaks).
10. **Never scrub the hermetic `gpuimage-352` fixture** — it's the Type-1 positive control that must still match. The scrubber applies only to mined cases.

---

## File Structure

- **Create** `groundloop/mine/__init__.py`
- **Create** `groundloop/domains/android_ivi/owner_tokens.py` — `FLEET_OWNER_TOKENS` (9-repo table: namespaces/slugs/sonames/aliases) + `owner_tokens_for(repo)`.
- **Create** `groundloop/mine/signal.py` — `split_issue_body(md) -> (prose, [{kind,text}])` + `classify(block)`.
- **Create** `groundloop/mine/scrub.py` — `parse_patch`, `build_owner_tokens(oracle)`, `scrub(text, tok)`, `leakage_flags(...)`, `admit(...)`.
- **Create** `groundloop/mine/filters.py` — `production_files(files)`, `is_minable(pr, files, *, max_files)`.
- **Create** `groundloop/mine/harvest.py` — `harvest_repo(slug, *, gh, limit)` (GraphQL, injectable `gh`), returns `Candidate` records.
- **Create** `groundloop/mine/emit.py` — `emit_case(root, case)` + `emit_catalog(root, names)`.
- **Create** `groundloop/mine/gh_miner.py` — `mine(slugs, out, *, gh, ...)` orchestrator + `gloop mine` CLI.
- **Modify** `groundloop/cli/__init__.py` — register `mine` subcommand.
- **Create** `tests/mine/__init__.py` + one test file per module.

**Commands:** test `.venv/bin/python -m pytest tests/mine/<f>.py -q`; full `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check groundloop tests` (line 110). Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1: Fleet owner-token table

**Files:** Create `groundloop/domains/android_ivi/owner_tokens.py`; Test `tests/mine/__init__.py` (empty) + `tests/mine/test_owner_tokens.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_owner_tokens.py`:

```python
from groundloop.domains.android_ivi.owner_tokens import FLEET_OWNER_TOKENS, owner_tokens_for


def test_all_nine_repos_present():
    assert set(FLEET_OWNER_TOKENS) == {
        "osmand", "organicmaps", "antennapod", "newpipe", "oboe",
        "cameraview", "dlt-daemon", "media3", "android-gpuimage-plus",
    }


def test_media3_gotcha_namespace_is_owner_side():
    # androidx.media3 is owner-identifying for media3 (not a generic keep)
    assert "androidx.media3" in FLEET_OWNER_TOKENS["media3"]["namespaces"]
    # ...but antennapod/newpipe KEEP androidx.media3.* as a dependency signal
    assert any("androidx.media3" in k for k in FLEET_OWNER_TOKENS["antennapod"]["KEEP"])


def test_owner_tokens_for_returns_row_with_required_keys():
    row = owner_tokens_for("oboe")
    assert row["namespaces"] == ["oboe::"]
    assert "liboboe.so" in row["sonames"]
    for key in ("namespaces", "slugs", "sonames", "KEEP"):
        assert key in row


def test_unknown_repo_raises():
    import pytest
    with pytest.raises(KeyError):
        owner_tokens_for("not-a-repo")
```

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** `groundloop/domains/android_ivi/owner_tokens.py` — the verified 9-repo table:

```python
"""Per-repo owner-identifying token table for the Type-2 leak-scrubber (docs/type2-evaluation.md §4.3).

The scrubber is PER-CASE: a repo's tokens are redacted only when it is that case's owning_repo.
`androidx.media3` is owner-identifying for media3 yet a KEPT dependency signal for antennapod/newpipe.
"""
from __future__ import annotations

FLEET_OWNER_TOKENS: dict[str, dict] = {
    "osmand": {
        "namespaces": ["net.osmand"], "slugs": ["osmand", "osmandapp", "OsmAnd"],
        "sonames": ["libOsmAndCore.so", "libOsmAndCoreWithJNI.so", "libosmand.so"],
        "KEEP": ["android.", "androidx.", "java.", "kotlin.", "libc.so", "libGLESv2.so"],
    },
    "organicmaps": {
        "namespaces": ["app.organicmaps", "com.mapswithme"],  # com.mapswithme = historical alias
        "slugs": ["organicmaps", "OrganicMaps", "MapsWithMe", "mapswithme"],
        "sonames": ["liborganicmaps.so"],
        "KEEP": ["android.", "androidx.", "java.", "libc.so", "libGLESv2.so", "libjnigraphics.so"],
    },
    "antennapod": {
        "namespaces": ["de.danoeh.antennapod", "de.danoeh"],
        "slugs": ["antennapod", "AntennaPod", "danoeh"], "sonames": [],
        "KEEP": ["android.", "androidx.", "androidx.media3.", "android.media.", "java.", "kotlin."],
    },
    "newpipe": {
        "namespaces": ["org.schabi.newpipe", "org.schabi"],
        "slugs": ["newpipe", "NewPipe", "schabi"], "sonames": [],
        "KEEP": ["android.", "androidx.", "androidx.media3.", "java.", "kotlin."],
    },
    "oboe": {
        "namespaces": ["oboe::"], "slugs": ["oboe", "Oboe"], "sonames": ["liboboe.so"],
        "KEEP": ["libaaudio.so", "libOpenSLES.so", "android.media.AudioTrack", "libc.so"],
    },
    "cameraview": {
        "namespaces": ["com.otaliastudios.cameraview", "com.otaliastudios"],
        "slugs": ["otaliastudios", "natario1"],  # bare 'cameraview' is a generic word — redact via namespace only
        "sonames": [],
        "KEEP": ["androidx.camera.", "android.hardware.camera2.", "android.graphics.SurfaceTexture", "android."],
    },
    "dlt-daemon": {
        "namespaces": ["dlt_"], "slugs": ["dlt-daemon", "dlt", "COVESA", "GENIVI", "genivi"],
        "sonames": ["libdlt.so"], "KEEP": ["libc.so", "syslog", "libpthread.so"],
    },
    "media3": {
        "namespaces": ["androidx.media3", "com.google.android.exoplayer2"],  # exoplayer2 = pre-donation alias
        "slugs": ["media3", "ExoPlayer", "exoplayer"],
        "sonames": ["libexoplayerflac.so", "libmedia3.so"],
        "KEEP": ["android.media.", "androidx.media.", "androidx.core.", "android.", "java."],
    },
    "android-gpuimage-plus": {
        "namespaces": ["org.wysaid"], "slugs": ["wysaid", "android-gpuimage-plus", "gpuimage", "CGE", "cge"],
        "sonames": ["libCGE.so", "libCGE_java", "libcge.so"],
        "KEEP": ["libffmpeg.so", "java.lang.UnsatisfiedLinkError", "android.opengl.", "libGLESv2.so", "libEGL.so"],
    },
}


def owner_tokens_for(repo: str) -> dict:
    """The owner-token row for a fleet repo. Raises KeyError for an unknown repo."""
    return FLEET_OWNER_TOKENS[repo]
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(mine): fleet owner-token table for the leak-scrubber`).

---

## Task 2: Issue-body signal extraction

**Files:** Create `groundloop/mine/__init__.py` (empty), `groundloop/mine/signal.py`; Test `tests/mine/test_signal.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_signal.py`:

```python
from groundloop.mine.signal import split_issue_body, classify


def test_classify_kinds():
    assert classify("  at org.x.Foo.bar(Foo.java:1)") == "stacktrace"
    assert classify("E/AndroidRuntime: FATAL EXCEPTION: main") == "logcat"
    assert classify("  #00 pc 0000abcd  liba.so") == "native"
    assert classify("ANR in com.x (com.x/.Main)") == "anr"
    assert classify("just prose about a crash") == "other"


def test_fenced_log_block_extracted_and_cut_from_prose():
    md = (
        "The app crashes when I tap filter.\n\n"
        "```\n"
        "E/AndroidRuntime: FATAL EXCEPTION: GLThread\n"
        "java.lang.UnsatisfiedLinkError: No implementation found\n"
        "  at org.wysaid.CGEImageHandler.nativeCreateHandler(Native Method)\n"
        "```\n\n"
        "Device: Pixel 5.\n"
    )
    prose, logs = split_issue_body(md)
    assert len(logs) == 1
    assert logs[0]["kind"] == "logcat"
    assert "UnsatisfiedLinkError" in logs[0]["text"]
    # the fenced block is removed from prose; surrounding prose is kept
    assert "crashes when I tap filter" in prose
    assert "Device: Pixel 5" in prose
    assert "UnsatisfiedLinkError" not in prose


def test_issue_template_scaffolding_stripped():
    md = "### Steps to reproduce\n- [ ] checkbox\n<!-- comment -->\nreal prose here\n"
    prose, logs = split_issue_body(md)
    assert "checkbox" not in prose
    assert "real prose here" in prose


def test_body_with_no_logs_yields_empty_logs():
    prose, logs = split_issue_body("Feature request: please add dark mode.")
    assert logs == []
    assert "dark mode" in prose
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/mine/signal.py`:

```python
"""Split a markdown issue body into sanitized prose + typed log blocks (docs/type2-evaluation.md §4)."""
from __future__ import annotations

import re

RE_FENCE = re.compile(r"(?ms)^[ \t]*```[^\n]*\n(.*?)^[ \t]*```[ \t]*$")

RE_JAVA_FRAME = re.compile(r"(?m)^\s*at\s+[\w$.]+\.[\w$<>]+\(")
RE_EXC_HEADER = re.compile(r"(?m)^\s*(?:Caused by:\s*)?(?:[a-z][\w$]*\.)+[A-Z]\w*(?:Exception|Error)\b")
RE_LOGCAT_TAG = re.compile(r"(?m)^\s*[VDIWEF]/[\w$.\-]+\s*(?:\(\s*\d+\))?\s*:")
RE_LOGCAT_TS = re.compile(r"(?m)^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+\s+[VDIWEF]\s")
RE_FATAL = re.compile(r"\bFATAL EXCEPTION\b")
RE_ANDROIDRT = re.compile(r"\bE/AndroidRuntime\b")
RE_NAT_FRAME = re.compile(r"(?m)^\s*#\d{2}\s+pc\s+[0-9a-fA-F]+\b")
RE_NAT_SIG = re.compile(r"\bsignal\s+\d+\s+\(SIG[A-Z]+\)")
RE_NAT_BT = re.compile(r"(?m)^\s*backtrace:\s*$|\bAbort message\b|\bBuild fingerprint\b")
RE_ANR = re.compile(r"\bANR in\b|Input dispatching timed out")
RE_TEMPLATE = re.compile(r"(?m)^\s*(?:#{1,6}\s.*|-\s*\[[ xX]\].*|<!--.*?-->)\s*$")

_LOG_LINE = (RE_JAVA_FRAME, RE_LOGCAT_TAG, RE_LOGCAT_TS, RE_NAT_FRAME)


def classify(block: str) -> str:
    if RE_NAT_FRAME.search(block) or RE_NAT_SIG.search(block) or RE_NAT_BT.search(block):
        return "native"
    if RE_ANR.search(block):
        return "anr"
    if (RE_LOGCAT_TAG.search(block) or RE_LOGCAT_TS.search(block)
            or RE_ANDROIDRT.search(block) or RE_FATAL.search(block)):
        return "logcat"
    if RE_JAVA_FRAME.search(block) or RE_EXC_HEADER.search(block):
        return "stacktrace"
    return "other"


def _looks_like_log(block: str) -> bool:
    return classify(block) != "other" or bool(RE_JAVA_FRAME.search(block))


def split_issue_body(md: str) -> tuple[str, list[dict]]:
    """Return (sanitized prose, [{kind, text}]). Fenced + unfenced log runs become logs; the rest is prose."""
    logs: list[dict] = []
    spans: list[tuple[int, int]] = []
    for m in RE_FENCE.finditer(md):
        body = m.group(1)
        if _looks_like_log(body):
            logs.append({"kind": classify(body), "text": body.strip("\n")})
            spans.append(m.span())
    prose = _cut(md, spans)

    # Unfenced runs: >=3 consecutive log-looking lines (many issues paste raw logcat).
    prose, extra = _harvest_unfenced(prose)
    logs += extra
    prose = RE_TEMPLATE.sub("", prose)
    return prose.strip(), logs


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    out, prev = [], 0
    for a, b in sorted(spans):
        out.append(text[prev:a])
        prev = b
    out.append(text[prev:])
    return "".join(out)


def _harvest_unfenced(text: str) -> tuple[str, list[dict]]:
    lines = text.splitlines()
    keep: list[str] = []
    logs: list[dict] = []
    run: list[str] = []

    def flush_run():
        if len(run) >= 3:
            block = "\n".join(run)
            logs.append({"kind": classify(block), "text": block})
        else:
            keep.extend(run)
        run.clear()

    for ln in lines:
        if any(r.search(ln) for r in _LOG_LINE):
            run.append(ln)
        else:
            flush_run()
            keep.append(ln)
    flush_run()
    return "\n".join(keep), logs
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(mine): split_issue_body — prose + typed log blocks`).

---

## Task 3: Leak-scrubber (per-case, oracle-parameterized)

**Files:** Create `groundloop/mine/scrub.py`; Test `tests/mine/test_scrub.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_scrub.py`:

```python
from groundloop.mine.scrub import build_owner_tokens, scrub, leakage_flags, admit, parse_patch


def _oracle_gpuimage():
    return {
        "owning_repo": "android-gpuimage-plus",
        "owner_namespaces": ["org.wysaid"],
        "owner_slugs": ["wysaid", "android-gpuimage-plus", "gpuimage"],
        "owner_sonames": ["libCGE.so"],
        "expected_files": ["library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"],
        "fix_patch": "@@\n-int old = 0;\n+long nativeCreateHandler() { return newImpl(); }\n",
    }


def test_parse_patch_extracts_added_methods_and_lines():
    p = parse_patch("@@\n-old\n+long nativeCreateHandler() { return x; }\n")
    assert "nativeCreateHandler" in p["methods"] or "nativeCreateHandler" in p["symbols"]
    assert any("nativeCreateHandler" in ln for ln in p["added_lines"])


def test_scrub_redacts_owner_namespace_class_and_method():
    tok = build_owner_tokens(_oracle_gpuimage())
    text = ("java.lang.UnsatisfiedLinkError: No implementation found for "
            "org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler()\n"
            "  at org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler(Native Method)")
    out = scrub(text, tok)
    assert "org.wysaid" not in out
    assert "CGEImageHandler" not in out
    assert "nativeCreateHandler" not in out
    # generic framework signal is KEPT
    assert "UnsatisfiedLinkError" in out


def test_generic_framework_tokens_survive():
    tok = build_owner_tokens(_oracle_gpuimage())
    text = "at android.opengl.GLSurfaceView.run() threw java.lang.UnsatisfiedLinkError; libffmpeg.so loaded"
    out = scrub(text, tok)
    assert "android.opengl.GLSurfaceView" in out
    assert "UnsatisfiedLinkError" in out
    assert "libffmpeg.so" in out  # ffmpeg is generic (GENERIC_SO_KEEP), not owner-unique


def test_media3_namespace_is_owner_for_media3_but_kept_for_newpipe():
    media3_tok = build_owner_tokens({
        "owning_repo": "media3", "owner_namespaces": ["androidx.media3"],
        "owner_slugs": ["media3"], "owner_sonames": [], "expected_files": [], "fix_patch": "",
    })
    text = "at androidx.media3.exoplayer.ExoPlayerImpl.release()"
    assert "androidx.media3" not in scrub(text, media3_tok)          # redacted for a media3 case
    # a newpipe case does NOT put androidx.media3 in owner tokens -> it survives
    newpipe_tok = build_owner_tokens({
        "owning_repo": "newpipe", "owner_namespaces": ["org.schabi.newpipe"],
        "owner_slugs": ["newpipe"], "owner_sonames": [], "expected_files": [], "fix_patch": "",
    })
    assert "androidx.media3" in scrub(text, newpipe_tok)


def test_leakage_flags_reject_when_owner_token_survives_then_admit_when_clean():
    tok = build_owner_tokens(_oracle_gpuimage())
    dirty = "at org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler(Native Method)"
    flags, sig = leakage_flags(dirty, [dirty], tok, "android-gpuimage-plus")
    assert any(flags.values())
    assert admit(flags, sig) == "REJECT"

    clean_desc = "The app throws UnsatisfiedLinkError on start."
    clean_log = "java.lang.UnsatisfiedLinkError: No implementation found"
    flags2, sig2 = leakage_flags(clean_desc, [clean_log], tok, "android-gpuimage-plus")
    assert not any(flags2.values())
    assert admit(flags2, sig2) == "ADMIT"
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/mine/scrub.py` (adapt the grounding templates B + C):

```python
"""Per-case, oracle-parameterized leak-scrubber + leakage post-check (docs/type2-evaluation.md §4.3).

Redacts OWNER-identifying tokens (namespace/class/method/.so/slug/patch) while keeping generic
framework signal, then re-runs the real matcher's extractor to prove no owner-unique token survives.
"""
from __future__ import annotations

import re

GENERIC_SO_KEEP = {
    "libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so", "libart.so", "libbinder.so",
    "libEGL.so", "libGLESv1_CM.so", "libGLESv2.so", "libGLESv3.so", "libvulkan.so", "libOpenSLES.so",
    "libaaudio.so", "libmediandk.so", "libnativehelper.so", "libjnigraphics.so", "libz.so",
    "libc++.so", "libstdc++.so", "libffmpeg.so",
}
GENERIC_IDENT_KEEP = {
    "onCreate", "onStart", "onResume", "run", "init", "main", "read", "write", "open", "close",
    "Activity", "Fragment", "Service", "View", "Handler", "Runnable",
}
MIN_SHINGLE = 24

_ADDED = re.compile(r"(?m)^\+(?!\+\+).*")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_DECL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")  # a name immediately followed by '(' = a method/decl


def parse_patch(patch: str) -> dict:
    added = [m.group(0)[1:] for m in _ADDED.finditer(patch or "")]
    methods, symbols = set(), set()
    for ln in added:
        for m in _DECL.finditer(ln):
            methods.add(m.group(1))
        for m in _IDENT.finditer(ln):
            symbols.add(m.group(0))
    return {"classes": set(), "methods": methods, "symbols": symbols, "added_lines": added}


def _shingles(lines, ks=(1, 2, 3)):
    norm = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    norm = [ln for ln in norm if ln and ln not in {"return null;", "}", "{", "});"} and not ln.startswith("import ")]
    out = set()
    for k in ks:
        for i in range(len(norm) - k + 1):
            out.add(" ".join(norm[i:i + k]))
    return out


def _ns_variants(ns: str) -> re.Pattern:
    dot, slash = re.escape(ns), re.escape(ns.replace(".", "/"))
    tail = r"(?:[./][A-Za-z_$][\w$]*)*"
    return re.compile(rf"\bL?(?:{dot}|{slash}){tail};?")


def build_owner_tokens(oracle: dict) -> dict:
    fix = parse_patch(oracle.get("fix_patch", ""))
    exp = list(oracle.get("expected_files", []))
    bases = {f.rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in exp}
    return {
        "REPO": set(oracle.get("owner_slugs", [])),
        "PKG": set(oracle.get("owner_namespaces", [])),
        "PATH": set(exp) | bases,
        "CLASS": set(fix["classes"]),
        "METHOD": set(fix["methods"]) | set(fix["symbols"]),
        "SO": {s for s in oracle.get("owner_sonames", []) if s not in GENERIC_SO_KEEP},
        "PATCH": {sh for sh in _shingles(fix["added_lines"]) if len(sh) >= MIN_SHINGLE},
    }


def scrub(text: str, tok: dict) -> str:
    for ns in sorted(tok["PKG"], key=len, reverse=True):
        text = _ns_variants(ns).sub("<REDACTED_PKG>", text)
    for so in sorted(tok["SO"], key=len, reverse=True):
        stem = so[:-3] if so.endswith(".so") else so
        text = re.compile(rf"\b{re.escape(so)}\b|\b{re.escape(stem)}\b", re.I).sub("<REDACTED_SO>", text)
    for p in sorted(tok["PATH"], key=len, reverse=True):
        text = re.compile(rf"\b{re.escape(p)}\b").sub("<REDACTED_PATH>", text)
    for c in sorted(tok["CLASS"], key=len, reverse=True):
        if len(c) >= 4 and c not in GENERIC_IDENT_KEEP and (c != c.lower() or any(ch.isdigit() for ch in c)):
            text = re.compile(rf"\b{re.escape(c)}\b").sub("<REDACTED_CLASS>", text)
    for mth in sorted(tok["METHOD"], key=len, reverse=True):
        if len(mth) >= 4 and mth not in GENERIC_IDENT_KEEP and (mth != mth.lower() or len(mth) >= 8):
            text = re.compile(rf"\b{re.escape(mth)}\b").sub("<REDACTED_METHOD>", text)
    for slug in sorted(tok["REPO"], key=len, reverse=True):
        text = re.compile(rf"\b{re.escape(slug)}\b", re.I).sub("<REDACTED_REPO>", text)
    for sh in sorted(tok["PATCH"], key=len, reverse=True):
        text = text.replace(sh, "<REDACTED_PATCH>")
    return text


def leakage_flags(sanitized_desc: str, sanitized_logs: list[str], tok: dict, owning_repo: str):
    from groundloop.core.types import LogAttachment, Ticket
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor

    text = sanitized_desc + "\n" + "\n".join(sanitized_logs)
    repo_alt = "|".join(re.escape(s) for s in (tok["REPO"] | {owning_repo}))
    flags = {
        "reponame_in_text": bool(re.search(rf"(?i)\b(?:{repo_alt})\b", text)) if repo_alt else False,
        "package_in_text": any(_ns_variants(ns).search(text) for ns in tok["PKG"]),
        "file_in_text": any(re.search(rf"\b{re.escape(p)}\b", text) for p in tok["PATH"]),
        "class_in_text": any(re.search(rf"\b{re.escape(c)}\b", text) for c in tok["CLASS"]),
        "so_in_text": any(re.search(rf"(?i)\b{re.escape(s[:-3] if s.endswith('.so') else s)}\b", text)
                          for s in tok["SO"]),
        "patch_in_text": any(sh in text for sh in tok["PATCH"]),
    }
    tk = Ticket(id="x", summary="", description=sanitized_desc)
    atts = tuple(LogAttachment(path=f"logs/{i}.txt", kind="other", content=b)
                 for i, b in enumerate(sanitized_logs))
    sig = AndroidSignalExtractor().extract(atts, tk)
    owner_all = (tok["REPO"] | tok["PKG"] | tok["CLASS"] | tok["METHOD"]
                 | {s[:-3] for s in tok["SO"]} | {owning_repo})
    flags["extractor_leak"] = any(
        any(o == t or o in t.replace("/", ".") for o in owner_all) for t in sig.tokens())
    return flags, sig


def admit(flags: dict, sig) -> str:
    if any(flags.values()):
        return "REJECT"
    generic = [t for group in (sig.errors, sig.libraries, sig.classes) for t in group]
    return "ADMIT" if generic else "BUCKET_PROSE_ONLY"
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(mine): per-case leak-scrubber + extractor leakage post-check`).

*Note for the implementer:* verify `LogAttachment`/`Ticket`/`Signals.tokens()` field names against `groundloop/core/types.py` and `signal_extractor.py` before finalizing; adjust the `leakage_flags` construction to match (do not change the test asserts). If `sig.classes`/`sig.errors`/`sig.libraries` attribute names differ, map to the real `Signals` fields.

---

## Task 4: Quality filters

**Files:** Create `groundloop/mine/filters.py`; Test `tests/mine/test_filters.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_filters.py`:

```python
from groundloop.mine.filters import production_files, is_minable


def _f(name, status="modified", adds=5, dels=2):
    return {"filename": name, "status": status, "additions": adds, "deletions": dels}


def test_production_files_keeps_source_drops_test_doc_build():
    files = [
        _f("app/src/main/java/com/x/Foo.java"),
        _f("app/src/test/java/com/x/FooTest.java"),
        _f("app/src/androidTest/java/com/x/FooIT.java"),
        _f("README.md"),
        _f("docs/guide.md"),
        _f("gradle.properties"),
        _f("src/test/resources/mocks/data.json"),
    ]
    prod = production_files(files)
    assert prod == ["app/src/main/java/com/x/Foo.java"]


def test_minable_requires_production_source_and_small_diff():
    ok = [_f("src/main/java/A.java")]
    assert is_minable({"merged": True, "changed_files": 1}, ok, max_files=5) is True


def test_reject_merge_and_revert_and_unmerged():
    ok = [_f("src/main/java/A.java")]
    assert is_minable({"merged": False, "changed_files": 1}, ok, max_files=5) is False
    assert is_minable({"merged": True, "changed_files": 1, "title": "Merge branch main"}, ok, max_files=5) is False
    assert is_minable({"merged": True, "changed_files": 1, "title": "Revert \"fix X\""}, ok, max_files=5) is False


def test_reject_too_many_files_and_no_production_files():
    ok = [_f(f"src/main/java/A{i}.java") for i in range(6)]
    assert is_minable({"merged": True, "changed_files": 6}, ok, max_files=5) is False   # >max_files
    docs = [_f("README.md"), _f("docs/x.md")]
    assert is_minable({"merged": True, "changed_files": 2}, docs, max_files=5) is False  # no production files
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/mine/filters.py`:

```python
"""Quality filters for mined issue↔PR pairs (docs/type2-evaluation.md §4.2)."""
from __future__ import annotations

import re

_PROD_ROOTS = ("src/main/", "app/src/main/", "library/src/main/")
_PROD_EXT = (".java", ".kt", ".cpp", ".cc", ".c", ".h", ".hpp", ".mm")
_EXCLUDE = ("/test/", "/androidtest/", "/src/test/", "/resources/mocks",
            "/testdata/", "/fixtures/", "/samples/")
_KEEP_STATUS = {"added", "modified", "renamed"}
_MERGE_RE = re.compile(r"^\s*(?:merge\b|revert\b|revert \")", re.I)


def production_files(files: list[dict]) -> list[str]:
    """Repo-relative production source paths from a PR /files payload (drops test/doc/build)."""
    out: list[str] = []
    for f in files:
        name = f.get("filename", "")
        low = name.lower()
        if f.get("status") not in _KEEP_STATUS:
            continue
        if not low.endswith(_PROD_EXT):
            continue
        if any(x in low for x in _EXCLUDE):
            continue
        if not (any(r in low for r in _PROD_ROOTS) or low.startswith("src/") or "/src/" in low):
            continue
        out.append(name)
    return out


def is_minable(pr: dict, files: list[dict], *, max_files: int = 5) -> bool:
    """Admit only a merged, single-concern PR that touches >=1 production file and <= max_files."""
    if not pr.get("merged"):
        return False
    if _MERGE_RE.match(pr.get("title", "")):
        return False
    if pr.get("changed_files", len(files)) > max_files:
        return False
    return len(production_files(files)) >= 1
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(mine): quality filters — production-only, single-concern`).

---

## Task 5: Harvest (GraphQL via injected gh)

**Files:** Create `groundloop/mine/harvest.py`; Test `tests/mine/test_harvest.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_harvest.py` (canned GraphQL, no network):

```python
from groundloop.mine.harvest import harvest_repo, Candidate

# Minimal shape of the GraphQL page the harvester consumes.
_PAGE = {
    "data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [
            {   # good: same-repo merged closer, 1 production file
                "number": 100, "title": "Crash on filter", "body": "boom\n```\nat x.Y.z()\n```",
                "createdAt": "2026-01-01T00:00:00Z", "url": "u",
                "labels": {"nodes": [{"name": "bug"}]},
                "closedByPullRequestsReferences": {"nodes": [{
                    "number": 200, "merged": True, "mergedAt": "2026-02-01T00:00:00Z",
                    "mergeCommit": {"oid": "deadbeef"},
                    "repository": {"nameWithOwner": "acme/widget"},
                    "files": {"totalCount": 1, "nodes": [
                        {"path": "src/main/java/A.java", "changeType": "MODIFIED", "additions": 3, "deletions": 1}]},
                }]},
            },
            {   # cross-repo closer -> MUST be dropped
                "number": 101, "title": "Extractor bug", "body": "x",
                "createdAt": "2026-01-02T00:00:00Z", "url": "u2", "labels": {"nodes": []},
                "closedByPullRequestsReferences": {"nodes": [{
                    "number": 300, "merged": True, "mergedAt": "2026-02-02T00:00:00Z",
                    "mergeCommit": {"oid": "cafe"},
                    "repository": {"nameWithOwner": "acme/widget-extractor"},  # DIFFERENT repo
                    "files": {"totalCount": 1, "nodes": [
                        {"path": "src/main/java/B.java", "changeType": "MODIFIED", "additions": 1, "deletions": 0}]},
                }]},
            },
            {   # no merged closer -> dropped
                "number": 102, "title": "Question", "body": "how?", "createdAt": "2026-01-03T00:00:00Z",
                "url": "u3", "labels": {"nodes": []}, "closedByPullRequestsReferences": {"nodes": []},
            },
        ],
    }}}
}


def test_harvest_keeps_same_repo_merged_and_drops_cross_repo_and_unlinked():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return _PAGE

    cands = harvest_repo("acme/widget", gh=fake_gh, limit=50)

    assert [c.issue_number for c in cands] == [100]
    c = cands[0]
    assert isinstance(c, Candidate)
    assert c.owning_slug == "acme/widget"
    assert c.pr_number == 200
    assert c.merge_commit_sha == "deadbeef"
    assert c.files[0]["filename"] == "src/main/java/A.java"
    assert c.files[0]["status"] == "modified"        # normalized from GraphQL UPPERCASE
    assert c.issue_title == "Crash on filter"


def test_dedup_same_issue_across_pages():
    node = _PAGE["data"]["repository"]["issues"]["nodes"][0]
    page = {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node, node]}}}}
    cands = harvest_repo("acme/widget", gh=lambda a: page, limit=50)
    assert len(cands) == 1
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/mine/harvest.py`:

```python
"""Harvest closed issues with a same-repo merged closing PR via the GitHub GraphQL API.

`gh` is injected as a callable: gh(args:list[str]) -> parsed JSON. The default shells out to
`gh api graphql`. GraphQL is used (not `gh search`) because closedByPullRequestsReferences gives
the issue->merged-PR binding directly in one paginated call (search does not expose it).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable

_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    issues(states:CLOSED, first:25, after:$cursor,
           orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body createdAt url
        labels(first:20) { nodes { name } }
        closedByPullRequestsReferences(first:5, includeClosedPrs:true) {
          nodes {
            number merged mergedAt mergeCommit { oid }
            repository { nameWithOwner }
            files(first:100) { totalCount nodes { path changeType additions deletions } }
          }
        }
      }
    }
  }
}
"""

_STATUS = {"ADDED": "added", "MODIFIED": "modified", "REMOVED": "removed",
           "RENAMED": "renamed", "COPIED": "copied", "CHANGED": "changed"}


@dataclass(frozen=True)
class Candidate:
    owning_slug: str          # "owner/name"
    issue_number: int
    issue_title: str
    issue_body: str
    issue_url: str
    labels: tuple[str, ...]
    created_at: str
    pr_number: int
    merge_commit_sha: str
    merged_at: str
    files_total: int
    files: list[dict] = field(default_factory=list)  # [{filename,status,additions,deletions}]


def _default_gh(args: list[str]) -> dict:
    cp = subprocess.run(["gh", *args], capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"gh {args[:2]} failed: {(cp.stderr or '')[-300:]}")
    return json.loads(cp.stdout or "{}")


def _gql_args(owner: str, name: str, cursor: str | None) -> list[str]:
    args = ["api", "graphql", "-f", f"query={_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"]
    if cursor:
        args += ["-F", f"cursor={cursor}"]
    return args


def harvest_repo(slug: str, *, gh: Callable[[list[str]], dict] = _default_gh,
                 limit: int = 200) -> list[Candidate]:
    """Return same-repo merged-closer candidates for a repo, deduped per issue."""
    owner, name = slug.split("/", 1)
    seen: set[int] = set()
    out: list[Candidate] = []
    cursor: str | None = None
    while len(out) < limit:
        page = gh(_gql_args(owner, name, cursor))
        conn = page["data"]["repository"]["issues"]
        for node in conn["nodes"]:
            if node["number"] in seen:
                continue
            closer = _pick_closer(node, slug)
            if closer is None:
                continue
            seen.add(node["number"])
            out.append(_to_candidate(slug, node, closer))
            if len(out) >= limit:
                break
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return out


def _pick_closer(node: dict, slug: str) -> dict | None:
    for pr in node.get("closedByPullRequestsReferences", {}).get("nodes", []):
        if pr.get("merged") and pr.get("repository", {}).get("nameWithOwner") == slug:
            return pr        # same-repo merged closer (the non-negotiable filter)
    return None


def _to_candidate(slug: str, node: dict, pr: dict) -> Candidate:
    files = [{"filename": f["path"], "status": _STATUS.get(f["changeType"], f["changeType"].lower()),
              "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)}
             for f in pr.get("files", {}).get("nodes", [])]
    return Candidate(
        owning_slug=slug, issue_number=node["number"], issue_title=node.get("title", ""),
        issue_body=node.get("body") or "", issue_url=node.get("url", ""),
        labels=tuple(x["name"] for x in node.get("labels", {}).get("nodes", [])),
        created_at=node.get("createdAt", ""), pr_number=pr["number"],
        merge_commit_sha=(pr.get("mergeCommit") or {}).get("oid", ""),
        merged_at=pr.get("mergedAt", ""), files_total=pr.get("files", {}).get("totalCount", len(files)),
        files=files)
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(mine): GraphQL harvest with same-repo merged-closer filter + dedup`).

---

## Task 6: Emit case dirs (+ round-trip through MockJira/Case)

**Files:** Create `groundloop/mine/emit.py`; Test `tests/mine/test_emit.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_emit.py` (proves the on-disk schema loads):

```python
import json
from pathlib import Path

from groundloop.mine.emit import emit_case, emit_catalog, MinedCase
from groundloop.adapters.mock.jira import MockJira
import tests.conftest as conftest  # for the Case oracle-loading contract


def _case():
    return MinedCase(
        case_id="ND-100", summary="Crash on search", description="It crashes.",
        logs=[{"kind": "stacktrace", "text": "java.lang.NullPointerException\n  at a.b.c()"}],
        owning_repo="newpipe", expected_files=["app/src/main/java/org/schabi/newpipe/Foo.java"],
        required_apis=["doSearch"], owning_repo_sha="deadbeef", is_answerable=True,
        provenance={"issue": {"number": 100}}, leakage={"leakage_flags": {}, "scrubber_version": "1.0.0"},
        raw={"issue": {"n": 1}, "pr_files": []},
    )


def test_emit_case_writes_loadable_layout(tmp_path):
    emit_case(str(tmp_path), _case())
    d = tmp_path / "ND-100"
    # loop-visible
    assert (d / "ticket.json").is_file()
    t = json.loads((d / "ticket.json").read_text())
    assert t["id"] == "ND-100" and t["component"] == "" and isinstance(t["comments"], list)
    assert t["logs"][0]["path"].startswith("logs/")
    assert (d / t["logs"][0]["path"]).is_file()
    # hidden, nested under _oracle/
    assert (d / "_oracle" / "oracle.json").is_file()
    assert (d / "_oracle" / "provenance.json").is_file()
    assert (d / "_oracle" / "leakage.json").is_file()
    assert (d / "_oracle" / "raw" / "issue.json").is_file()


def test_emitted_ticket_loads_via_mockjira(tmp_path):
    emit_case(str(tmp_path), _case())
    ticket = MockJira(str(tmp_path)).fetch("ND-100")
    assert ticket.id == "ND-100"
    assert ticket.component == ""
    assert ticket.logs[0].content.startswith("java.lang.NullPointerException")


def test_oracle_roundtrips_and_drops_extra_keys(tmp_path):
    emit_case(str(tmp_path), _case())
    raw = json.loads((tmp_path / "ND-100" / "_oracle" / "oracle.json").read_text())
    assert raw["owning_repo"] == "newpipe"
    assert isinstance(raw["expected_files"], list)     # array, not string
    assert raw["owning_repo_sha"] == "deadbeef"        # extra key present on disk...
    from groundloop.core.types import Oracle
    _ORACLE_KEYS = {"owning_repo", "expected_files", "required_apis"}
    oracle = Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                       for k, v in raw.items() if k in _ORACLE_KEYS})   # ...dropped by the loader
    assert oracle.owning_repo == "newpipe"
    assert oracle.expected_files == ("app/src/main/java/org/schabi/newpipe/Foo.java",)


def test_emit_catalog_writes_name_array(tmp_path):
    emit_catalog(str(tmp_path), ["newpipe", "osmand", "media3"])
    cat = json.loads((tmp_path / "catalog.json").read_text())
    assert cat == [{"name": "newpipe"}, {"name": "osmand"}, {"name": "media3"}]
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/mine/emit.py`:

```python
"""Emit a mined case to disk in the exact gpuimage-352 layout (docs/type2-evaluation.md §4.4).

Hidden owner-bearing metadata nests under _oracle/ so the invariant-#4 read-spy covers it for free.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MinedCase:
    case_id: str
    summary: str
    description: str
    logs: list[dict]                 # [{kind, text}]
    owning_repo: str
    expected_files: list[str]
    required_apis: list[str]
    owning_repo_sha: str = ""
    is_answerable: bool = True
    provenance: dict = field(default_factory=dict)
    leakage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def emit_case(root: str, case: MinedCase) -> str:
    d = Path(root) / case.case_id
    log_entries = []
    for i, lg in enumerate(case.logs):
        rel = f"logs/{i:03d}.txt"
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(lg["text"])
        log_entries.append({"path": rel, "kind": lg.get("kind", "other")})
    _write_json(d / "ticket.json", {
        "id": case.case_id, "summary": case.summary, "description": case.description,
        "component": "",  # anti-leak: never the owner
        "status": "Open", "comments": [], "logs": log_entries,
    })
    _write_json(d / "_oracle" / "oracle.json", {
        "owning_repo": case.owning_repo,
        "expected_files": list(case.expected_files),
        "required_apis": list(case.required_apis),
        "owning_repo_sha": case.owning_repo_sha,
        "is_answerable": case.is_answerable,
    })
    _write_json(d / "_oracle" / "provenance.json", case.provenance)
    _write_json(d / "_oracle" / "leakage.json", case.leakage)
    _write_json(d / "_oracle" / "raw" / "issue.json", case.raw.get("issue", {}))
    _write_json(d / "_oracle" / "raw" / "pr_files.json", case.raw.get("pr_files", []))
    return str(d)


def emit_catalog(root: str, names: list[str]) -> str:
    p = Path(root) / "catalog.json"
    _write_json(p, [{"name": n} for n in names])
    return str(p)
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(mine): emit mined case dirs (round-trips through MockJira/Oracle)`).

---

## Task 7: Miner orchestrator + `gloop mine`

**Files:** Create `groundloop/mine/gh_miner.py`; Modify `groundloop/cli/__init__.py`; Test `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Failing test** — `tests/mine/test_gh_miner.py` (full pipeline, injected gh + real fleet tokens):

```python
import json
from pathlib import Path

from groundloop.mine.gh_miner import mine
from groundloop.adapters.mock.jira import MockJira


def _page(slug, number, body, path):
    return {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [{
            "number": number, "title": "Crash", "body": body,
            "createdAt": "2026-01-01T00:00:00Z", "url": "u", "labels": {"nodes": [{"name": "bug"}]},
            "closedByPullRequestsReferences": {"nodes": [{
                "number": number + 1000, "merged": True, "mergedAt": "2026-02-01T00:00:00Z",
                "mergeCommit": {"oid": "sha1"}, "repository": {"nameWithOwner": slug},
                "files": {"totalCount": 1, "nodes": [
                    {"path": path, "changeType": "MODIFIED", "additions": 3, "deletions": 1}]},
            }]},
        }],
    }}}}


def test_mine_end_to_end_emits_admitted_scrubbed_case(tmp_path):
    # A NewPipe issue whose body leaks the owner namespace + a generic exception.
    body = ("Crashes on search.\n```\n"
            "java.lang.NullPointerException\n"
            "  at org.schabi.newpipe.SearchFragment.doSearch(SearchFragment.java:42)\n```\n")
    gh = lambda args: _page("TeamNewPipe/NewPipe", 100, body,
                            "app/src/main/java/org/schabi/newpipe/SearchFragment.java")

    report = mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand", "media3"], limit=10)

    assert report["admitted"] == 1
    # catalog written
    assert json.loads((tmp_path / "catalog.json").read_text()) == [
        {"name": "newpipe"}, {"name": "osmand"}, {"name": "media3"}]
    # the emitted ticket loads and is SCRUBBED (owner namespace gone, generic error kept)
    case_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    ticket = MockJira(str(tmp_path)).fetch(case_dir.name)
    blob = ticket.description + "\n" + "\n".join(a.content for a in ticket.logs)
    assert "org.schabi.newpipe" not in blob
    assert "NullPointerException" in blob          # generic signal kept
    # oracle is hidden + correct
    oracle = json.loads((case_dir / "_oracle" / "oracle.json").read_text())
    assert oracle["owning_repo"] == "newpipe"
    assert oracle["expected_files"] == ["app/src/main/java/org/schabi/newpipe/SearchFragment.java"]


def test_mine_rejects_when_no_production_files(tmp_path):
    body = "Docs typo.\n```\nat x.Y.z()\n```\n"
    gh = lambda args: _page("TeamNewPipe/NewPipe", 101, body, "README.md")
    report = mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe"], limit=10)
    assert report["admitted"] == 0
    assert report["dropped_filters"] >= 1
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/mine/gh_miner.py`:

```python
"""Miner orchestrator: harvest -> filter -> signal split -> scrub -> admit -> emit. `gloop mine`."""
from __future__ import annotations

from typing import Callable, Optional

from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for
from groundloop.mine.harvest import Candidate, harvest_repo
from groundloop.mine.filters import is_minable, production_files
from groundloop.mine.signal import split_issue_body
from groundloop.mine.scrub import build_owner_tokens, scrub, leakage_flags, admit
from groundloop.mine.emit import MinedCase, emit_case, emit_catalog


def _oracle_for(cand: Candidate, repo_name: str, expected_files: list[str]) -> dict:
    row = owner_tokens_for(repo_name)
    return {
        "owning_repo": repo_name,
        "owner_namespaces": list(row["namespaces"]), "owner_slugs": list(row["slugs"]),
        "owner_sonames": list(row["sonames"]), "expected_files": expected_files,
        "fix_patch": "",  # E1-B v1 derives class/method from the issue text, not the diff body
    }


def mine(slugs: list[str], out: str, *, gh: Optional[Callable] = None, repo_name: str,
         fleet_names: list[str], limit: int = 200, max_files: int = 5) -> dict:
    """Mine one repo slug (repo_name = its short catalog name) into `out/`. Returns a report dict."""
    report = {"harvested": 0, "dropped_filters": 0, "rejected_leak": 0, "bucketed": 0, "admitted": 0}
    emit_catalog(out, fleet_names)
    kwargs = {"limit": limit} if gh is None else {"gh": gh, "limit": limit}
    for slug in slugs:
        for cand in harvest_repo(slug, **kwargs):
            report["harvested"] += 1
            prod = production_files(cand.files)
            if not is_minable({"merged": True, "changed_files": cand.files_total,
                               "title": cand.issue_title}, cand.files, max_files=max_files):
                report["dropped_filters"] += 1
                continue
            prose, logs = split_issue_body(cand.issue_body)
            oracle = _oracle_for(cand, repo_name, prod)
            tok = build_owner_tokens(oracle)
            s_desc = scrub(prose, tok)
            s_summary = scrub(cand.issue_title, tok)
            s_logs = [scrub(lg["text"], tok) for lg in logs]
            flags, sig = leakage_flags(s_desc + "\n" + s_summary, s_logs, tok, repo_name)
            verdict = admit(flags, sig)
            if verdict == "REJECT":
                report["rejected_leak"] += 1
                continue
            if verdict == "BUCKET_PROSE_ONLY":
                report["bucketed"] += 1
                s_logs = []  # nothing matchable survived; keep prose-only
            case = MinedCase(
                case_id=f"{repo_name}-{cand.issue_number}", summary=s_summary, description=s_desc,
                logs=[{"kind": lg["kind"], "text": t} for lg, t in zip(logs, s_logs)],
                owning_repo=repo_name, expected_files=prod, required_apis=[],
                owning_repo_sha=cand.merge_commit_sha, is_answerable=True,
                provenance={"issue": {"number": cand.issue_number, "url": cand.issue_url, "repo": slug},
                            "pr": {"number": cand.pr_number, "merge_commit_sha": cand.merge_commit_sha},
                            "link_method": "github_linked_pr", "created_at": cand.created_at},
                leakage={"leakage_flags": {k: v for k, v in flags.items() if k != "extractor_leak"},
                         "scrubber_version": "1.0.0"},
                raw={"issue": {"number": cand.issue_number, "title": cand.issue_title,
                               "body": cand.issue_body}, "pr_files": cand.files})
            emit_case(out, case)
            report["admitted"] += 1
    return report
```

Then wire the CLI in `groundloop/cli/__init__.py` (subparser + dispatch):

```python
    mn = sub.add_parser("mine", help="harvest issue->fix cases for a fleet repo (online, gh)")
    mn.add_argument("--slug", required=True, help="owner/name GitHub slug, e.g. TeamNewPipe/NewPipe")
    mn.add_argument("--repo-name", required=True, help="short fleet/catalog name, e.g. newpipe")
    mn.add_argument("--out", required=True, help="dataset output dir")
    mn.add_argument("--limit", type=int, default=200)
    mn.add_argument("--max-files", type=int, default=5)
```

```python
def _run_mine(args) -> int:
    from groundloop.mine.gh_miner import mine
    from groundloop.engines.atlas.registry import load_registry
    from groundloop.config.settings import Settings
    reg = Settings.load().registry
    fleet = [e.name for e in load_registry(reg)] if reg else [args.repo_name]
    report = mine([args.slug], args.out, repo_name=args.repo_name, fleet_names=fleet,
                  limit=args.limit, max_files=args.max_files)
    print(f"mine {args.repo_name}: " + " ".join(f"{k}={v}" for k, v in report.items()))
    return 0
```

And add the dispatch: `if args.cmd == "mine": return _run_mine(args)`.

- [ ] **Step 4: Run → pass.** Then `.venv/bin/python -m pytest -q` (full suite green), `.venv/bin/ruff check groundloop tests`, `.venv/bin/gloop mine --help` (exit 0).
- [ ] **Step 5: Commit** (`feat(mine): miner orchestrator + gloop mine`).

---

## Task 8: Type-1 dataset leak-invariant

**Files:** Test `tests/mine/test_dataset_integrity.py`.

- [ ] **Step 1: Write the test** (this IS the deliverable — it hard-guards the benchmark's integrity):

```python
"""Every mined case must round-trip through MockJira/Oracle AND leak no owner-unique token."""
from pathlib import Path

from groundloop.mine.gh_miner import mine
from groundloop.mine.scrub import build_owner_tokens, leakage_flags
from groundloop.mine.emit import MinedCase, emit_case  # noqa: F401 (schema reference)
from groundloop.adapters.mock.jira import MockJira
from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for


def _oracle(repo, files):
    row = owner_tokens_for(repo)
    return {"owning_repo": repo, "owner_namespaces": list(row["namespaces"]),
            "owner_slugs": list(row["slugs"]), "owner_sonames": list(row["sonames"]),
            "expected_files": files, "fix_patch": ""}


def test_mined_case_never_leaks_owner_token(tmp_path):
    body = ("Crash.\n```\njava.lang.NullPointerException\n"
            "  at org.schabi.newpipe.player.Player.load(Player.java:9)\n```\n")
    gh = lambda a: {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{
            "number": 7, "title": "Player NPE", "body": body, "createdAt": "t", "url": "u",
            "labels": {"nodes": []}, "closedByPullRequestsReferences": {"nodes": [{
                "number": 8, "merged": True, "mergedAt": "t", "mergeCommit": {"oid": "s"},
                "repository": {"nameWithOwner": "TeamNewPipe/NewPipe"},
                "files": {"totalCount": 1, "nodes": [{
                    "path": "app/src/main/java/org/schabi/newpipe/player/Player.java",
                    "changeType": "MODIFIED", "additions": 2, "deletions": 1}]}}]}}]}}}}
    mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
         fleet_names=["newpipe", "osmand", "media3"], limit=5)

    for case_dir in [p for p in Path(tmp_path).iterdir() if p.is_dir()]:
        ticket = MockJira(str(tmp_path)).fetch(case_dir.name)
        assert ticket.component == ""
        tok = build_owner_tokens(_oracle("newpipe",
              ["app/src/main/java/org/schabi/newpipe/player/Player.java"]))
        flags, sig = leakage_flags(ticket.description,
                                   [a.content for a in ticket.logs], tok, "newpipe")
        assert not any(flags.values()), f"leak in {case_dir.name}: {flags}"
```

- [ ] **Step 2: Run → pass** (if it fails, the scrubber/emit has a leak — fix the code, not the test). **Step 3: Commit** (`test(mine): Type-1 dataset leak-invariant over mined cases`).

---

## Self-Review

**Spec coverage (`type2-evaluation.md` §4):** mine (Task 5, same-repo filter + dedup) ✓; quality filters (Task 4) ✓; signal extraction (Task 2) ✓; per-case oracle-parameterized scrubber + leakage post-check (Tasks 1, 3) ✓; case-dir schema with `_oracle/`-nested hidden metadata (Task 6) ✓; catalog.json (Task 6) ✓; integrity invariant (Task 8) ✓. **Deferred (noted, not silent):** fix-patch-derived class/method scrubbing (Task 7 `_oracle_for` sets `fix_patch=""` for v1 — class/method leaks are still caught by the namespace pass + the extractor post-check; wiring the real PR diff into `fix_patch` is an E1-B v2 follow-up); unanswerable/OOF cases (`is_answerable` field emitted, but OOF construction + the runner-side `catalog_holdout` filter belong to E1-C); `media3` commit-trailer provenance (Gerrit) — mining media3 via GraphQL linked-PRs only, per §13 open-Q2.

**Placeholder scan:** none — every module has complete code. `fix_patch=""` is an explicit, documented v1 scope, not a placeholder.

**Type consistency:** `Candidate` (harvest) → consumed by `gh_miner`; `MinedCase` (emit) fields match `emit_case`; scrubber `tok` dict keys (`REPO/PKG/PATH/CLASS/METHOD/SO/PATCH`) consistent across `build_owner_tokens`/`scrub`/`leakage_flags`; `owner_tokens_for` row keys (`namespaces/slugs/sonames/KEEP`) consistent with `_oracle_for`. **One cross-check flagged for the implementer** (Task 3 note): verify `Signals`/`LogAttachment`/`Ticket` field names in `core/types.py` + the `AndroidSignalExtractor` output attributes before finalizing `leakage_flags`, adjusting construction (not asserts) to match.
