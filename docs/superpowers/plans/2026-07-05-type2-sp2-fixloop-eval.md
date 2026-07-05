# Type-2 SP2 — Downstream Fix/RCA Loop + Hermetic Fix-Eval (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Execute in **three review batches**: Phase A (Tasks 1–2, grade primitives) → Phase B (Tasks 3–6, the hermetic fix-loop harness) → Phase C (Tasks 7–11, grading + CLI + gated live arm).

**Goal:** Build a **hermetic, oracle-blind fix-loop evaluation** — a `FixEvalRunner` that drives localize→propose-patch directly (never the frozen `run_ticket`), with harness-owned abstain, graded offline into a fix-scorecard carrying the AAOS-real metrics (`file_recall@k`, `patch_applies`, `required_api_pass_rate`, `resolved_rate` advisory, `cost_per_solved`) **and** the whole-loop **`fabrication_rate`** refusal metric over SP1's typed negatives. Ships a `gloop fixeval` + `gloop compare` surface, testable with a canned model + a tiny checked-in fixture repo, plus a **gated** live `GatewayModel` arm (real deepseek propose-patch).

**Architecture:** New package `groundloop/fixeval/` mirroring `groundloop/eval/` (SP1a). `core/` is FROZEN — the fix loop plugs in as a `FixEngine` adapter + a fixture `RepoEstate` at the composition root (`cli/__init__.py`), and the eval drives the ports **directly** in `FixEvalRunner` (exactly as SP1a's `EvalRunner` bypasses `run_ticket`). Verified: `core/workflow.py`, `core/ports.py`, `core/types.py` need **no edit** — an abstain is modeled as `Patch(diff="")`, and grade extras ride oracle-side (read by the eval layer, ignored by frozen `core.types.Oracle`).

**Tech Stack:** Python 3.12, `.venv` (uv), pytest, ruff (line 110), **git CLI** (for `git apply --check`; confirmed git ≥2.34). No new pip deps (`httpx` already used by `GatewayJudge`). Test: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`.

**Spec:** `docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md` §2. Design provenance + the bfl migration reference: `docs/downstream-fix-loop.md`. Design inputs gathered + adversarially verified via workflow (frozen-core: CONFIRMED; fully-hermetic: PARTIAL with the named gates below).

## Design decisions (read before implementing)

- **D1 — Fix-eval drives the ports directly (frozen core).** `FixEvalRunner` fetches ticket → extract signals → `rank_repos`+`decide` → materialize → `localize` → `fixer.propose` → `patch_applies`, emitting its own abstain-capable `FixRecord`. It does **not** call `run_ticket` (which is branchless and always emits a patch). `core/` untouched.
- **D2 — Two harness-owned abstain gates, both deterministic (grounding-over-narrative).** PRIMARY = SP1a's `decide()` (Stage-1 match abstain → `abstain_reason="no_repo_match"`). SECONDARY = empty localize (`"no_localization"`) and `git apply --check` failing after a bounded refine (`"patch_unappliable"`, downgraded to `Patch(diff="")`). **No new calibrated fix-stage confidence score** is invented. `decide()` runs **before** `fixer.propose` — else `fabrication_rate` degenerates to ~100%.
- **D3 — `fabrication_rate` is graded on CLEAN-APPLYING patches only.** A Bucket-1 negative (`is_answerable=false`) that emits a non-empty patch that **applies** = fabrication (`−c`); an abstain = `+1`. Whole-loop Φ_c reuses `metrics.phi_c` with the record `{answered:=patch_emitted, answerable:=is_answerable, correct:=patch_applies and file_recall@1>0}`. The apply-check gate already downgrades garbage diffs to abstain, so the metric can't be gamed by un-appliable junk.
- **D4 — Hermetic substrate + the load-bearing 3-surface path agreement.** `CannedModel` (scripted golden diff) + `GitFixtureEstate` (checked-in **plain files** → a synthesized single-commit git repo under the tmp work-root at materialize time — never a nested `.git` in the source tree) + a **separate** `build_fix_atlas_fixture` (don't perturb SP1a's `atlas_fixture.py`). **CRITICAL:** the atlas `Unit.file`, the oracle `expected_files[0]`, the checked-in fixture repo path, and the golden diff's `+++ b/` header MUST all be the same repo-relative path — a `norm_path` helper + a `test_fixture_consistency.py` guard enforce it (path drift silently zeros `file_recall`/`resolved`).
- **D5 — AAOS-real metrics; `resolved_rate` is advisory.** `file_recall@k` (basename-matched, not brittle exact-path), `patch_applies` (git-only, oracle-free), `required_api_pass_rate` (whole-word API scan over added diff lines), `resolved_rate` computed **only over the grounded-gradeable subset** (cases with BOTH `expected_files` and `required_apis`; others reported as `n_excluded`), `cost_per_solved`. **Test-execution `resolved` is DEFERRED** — AAOS corpus repos lack runnable suites.
- **D6 — Live is gated; real materializer is deferred.** `GatewayModel` (deepseek propose-patch, a clone of `GatewayJudge`) + `ModelPatchEngine` run under a `skipif`-gated e2e test. The **real** `GitArchiveEstate` over corpora at pinned SHAs is **out of this plan** — it needs `corpora/corpus.toml` (absent) + a miner-emitted `base_sha=fix^` (miner records `merge_commit_sha` only) + multi-GB AAOS trees. Noted as a gated follow-on.
- **D7 — WSL/whitespace:** author `golden.diff` with LF endings and call `git apply --check --whitespace=nowarn` (avoids spurious apply failures under WSL).

## File structure
**New package `groundloop/fixeval/`:** `__init__.py`, `patch.py` (diff parsing + `patch_applies` + `norm_path`), `localize.py`, `runner.py` (`FixEvalRunner`+`FixRecord`), `scorecard.py` (`grade_fix_all`), `report.py`.
**New adapters:** `groundloop/adapters/fix/model_patch.py` (`ModelPatchEngine`), `groundloop/adapters/model/gateway.py` (`GatewayModel`, gated). **Modify:** `groundloop/adapters/estate.py` (add `GitFixtureEstate`), `groundloop/eval/dataset.py` (add `EvalOracle.required_apis`), `groundloop/cli/__init__.py` (`fixeval` + `compare`).
**New fixtures:** `tests/fixtures/repos/android-gpuimage-plus/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp` (plain file), a golden + broken diff, `tests/fixtures/fix_atlas_fixture.py`, and ≥1 more Bucket-1 negative case.

---

# PHASE A — grade primitives (pure/hermetic; Tasks 1–2)

### Task 1: `fixeval/patch.py` — diff parsing + `norm_path`

**Files:** Create `groundloop/fixeval/__init__.py` (empty), `groundloop/fixeval/patch.py`; Test: `tests/fixeval/__init__.py` (empty), `tests/fixeval/test_patch.py`.

- [ ] **Step 1: Write the failing test** — create `tests/fixeval/test_patch.py`:
```python
from groundloop.fixeval.patch import (
    extract_unified_diff, touched_files, added_lines, references_api, norm_path)

_FENCED = "blah\n```diff\n--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+int nativeCreateHandler(){return 1;}\n```\ntrailer"
_BARE = "--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+int fixed;\n"


def test_extract_unified_diff_fenced_and_bare():
    assert "+++ b/x/A.cpp" in extract_unified_diff(_FENCED)
    assert extract_unified_diff(_FENCED).strip().endswith("nativeCreateHandler(){return 1;}")
    assert "+++ b/x/A.cpp" in extract_unified_diff(_BARE)
    assert extract_unified_diff("no diff here at all") == ""


def test_touched_files_strips_b_prefix():
    assert touched_files(_BARE) == ["x/A.cpp"]
    assert touched_files("--- a/dev/null\n+++ b/dev/null\n") == ["dev/null"]  # basic parse; dev-null handled by caller


def test_added_lines_excludes_header():
    al = added_lines(_FENCED)
    assert any("nativeCreateHandler" in a for a in al)
    assert not any(a.startswith("+++") for a in al)


def test_references_api_whole_word_over_added_only():
    assert references_api(_FENCED, "nativeCreateHandler") is True
    assert references_api(_FENCED, "nativeCreateHandlerX") is False        # not a substring match
    assert references_api("--- a/A\n+++ b/A\n@@\n-nativeCreateHandler\n", "nativeCreateHandler") is False  # removed line


def test_norm_path():
    assert norm_path("b/x/A.cpp") == "x/A.cpp" and norm_path("a/x/A.cpp") == "x/A.cpp"
    assert norm_path("./x//A.cpp") == "x/A.cpp" and norm_path("x/A.cpp") == "x/A.cpp"
```

- [ ] **Step 2: Run — expect FAIL** (module missing): `.venv/bin/python -m pytest tests/fixeval/test_patch.py -q`.

- [ ] **Step 3: Implement** — create `groundloop/fixeval/__init__.py` (empty) and `tests/fixeval/__init__.py` (empty), then `groundloop/fixeval/patch.py`:
```python
"""Unified-diff parsing + apply-check for the fix-loop eval. Pure/oracle-free; ported from the
knowledgeLoop eval extract.py (docs/downstream-fix-loop.md §1)."""
from __future__ import annotations

import re

_FENCE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)\n```", re.S)
_DIFF_START = re.compile(r"(?m)^(diff --git |--- )")


def extract_unified_diff(text: str) -> str:
    """Pull a unified diff from model output: a ```diff fence if present, else from the first
    `diff --git`/`--- ` header to end. Returns "" when no diff is found."""
    if not text:
        return ""
    m = _FENCE.search(text)
    if m and _DIFF_START.search(m.group(1)):
        return m.group(1).strip("\n")
    m2 = _DIFF_START.search(text)
    return text[m2.start():].strip("\n") if m2 else ""


def touched_files(diff: str) -> list[str]:
    """Repo-relative paths from `+++ b/<path>` headers (b/ stripped), in order, deduped."""
    out: list[str] = []
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            p = norm_path(ln[4:].split("\t", 1)[0].strip())
            if p and p not in out:
                out.append(p)
    return out


def added_lines(diff: str) -> list[str]:
    """Content of `+` lines, excluding the `+++` file header."""
    return [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


def references_api(diff: str, api: str) -> bool:
    """Whole-word `\\bapi\\b` over ADDED lines only."""
    pat = re.compile(rf"\b{re.escape(api)}\b")
    return any(pat.search(ln) for ln in added_lines(diff))


def norm_path(p: str) -> str:
    """Normalize a diff/oracle path to a bare repo-relative form: strip a/ b/ ./ and collapse //."""
    p = p.strip()
    for pre in ("a/", "b/", "./"):
        if p.startswith(pre):
            p = p[len(pre):]
    return re.sub(r"/+", "/", p)
```

- [ ] **Step 4: Run — expect PASS.** `.venv/bin/python -m pytest tests/fixeval/test_patch.py -q` + `.venv/bin/ruff check groundloop tests`.

- [ ] **Step 5: Commit**
```bash
git add groundloop/fixeval/__init__.py groundloop/fixeval/patch.py tests/fixeval/__init__.py tests/fixeval/test_patch.py
git commit -m "feat(fixeval): unified-diff parsing + norm_path (grade primitives)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `patch_applies` via `git apply --check`

**Files:** Modify `groundloop/fixeval/patch.py`; Test: `tests/fixeval/test_patch_applies.py`.

- [ ] **Step 1: Write the failing test** — create `tests/fixeval/test_patch_applies.py`:
```python
import subprocess
from pathlib import Path

from groundloop.fixeval.patch import patch_applies


def _git_worktree(tmp_path, rel, content):
    d = tmp_path / "wt"
    (d / Path(rel).parent).mkdir(parents=True)
    (d / rel).write_text(content)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(d), *args], check=True)
    return str(d)


def test_patch_applies_true_false(tmp_path):
    wt = _git_worktree(tmp_path, "x/A.cpp", "// bug\n")
    good = "--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+// fixed\n"
    assert patch_applies(good, wt) is True
    bad = "--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-nonexistent context\n+// fixed\n"
    assert patch_applies(bad, wt) is False
    assert patch_applies("", wt) is False          # empty diff never applies
```

- [ ] **Step 2: Run — expect FAIL** (`patch_applies` missing).

- [ ] **Step 3: Implement** — append to `groundloop/fixeval/patch.py`:
```python
import subprocess
import tempfile
from pathlib import Path


def patch_applies(diff: str, worktree_path: str) -> bool:
    """True iff `diff` applies cleanly against the tree at worktree_path (git apply --check).
    Empty diff => False. LF + --whitespace=nowarn (WSL-safe). git-only, oracle-free."""
    if not diff.strip():
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False, newline="\n") as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
        patch_file = fh.name
    try:
        cp = subprocess.run(["git", "-C", worktree_path, "apply", "--check",
                             "--whitespace=nowarn", patch_file],
                            capture_output=True, text=True)
        return cp.returncode == 0
    finally:
        Path(patch_file).unlink(missing_ok=True)
```
(Keep `subprocess`/`tempfile`/`Path` imports at the top of the module with the others.)

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit**
```bash
git add groundloop/fixeval/patch.py tests/fixeval/test_patch_applies.py
git commit -m "feat(fixeval): patch_applies via git apply --check (Tier-1.5 gate)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

*(Phase A ends: pure grade primitives, fully hermetic.)*

---

# PHASE B — hermetic fix-loop harness (Tasks 3–6)

### Task 3: `GitFixtureEstate` + the checked-in fixture repo

**Files:** Modify `groundloop/adapters/estate.py`; Create fixture `tests/fixtures/repos/android-gpuimage-plus/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp`; Test: `tests/adapters/test_fixture_estate.py`.

The fixture path is the **load-bearing** repo-relative path — it MUST equal the gpuimage-352 oracle's `expected_files[0]`. **First, read `tests/fixtures/android_ivi/gpuimage-352/_oracle/oracle.json` and use its exact `expected_files[0]` as the fixture path** (the plan assumes `library/src/main/jni/interface/cgeImageHandlerAndroid.cpp`; if the oracle differs, use the oracle's value everywhere in Phase B/C).

- [ ] **Step 1: Write the failing test** — create `tests/adapters/test_fixture_estate.py`:
```python
import subprocess
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef

FIX = Path(__file__).parent.parent / "fixtures" / "repos"
REL = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


def test_materialize_synthesizes_single_commit_repo(tmp_path):
    est = GitFixtureEstate(str(FIX), str(tmp_path / "work"))
    wt = est.materialize(RepoRef("android-gpuimage-plus"))
    assert (Path(wt.path) / REL).is_file()
    # exactly one commit, no branches/tags reaching a 'fix'
    log = subprocess.run(["git", "-C", wt.path, "log", "--oneline"], capture_output=True, text=True)
    assert len(log.stdout.strip().splitlines()) == 1
    tags = subprocess.run(["git", "-C", wt.path, "tag"], capture_output=True, text=True)
    assert tags.stdout.strip() == ""


def test_missing_repo_yields_empty_dir(tmp_path):
    est = GitFixtureEstate(str(FIX), str(tmp_path / "work"))
    wt = est.materialize(RepoRef("no-such-repo"))
    assert Path(wt.path).is_dir() and not any(Path(wt.path).iterdir())   # empty → drives abstain
```

- [ ] **Step 2: Run — expect FAIL** (`GitFixtureEstate` missing; fixture file missing).

- [ ] **Step 3: Implement**
  1. Create the fixture file `tests/fixtures/repos/android-gpuimage-plus/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp` with LF endings and a `// bug` first line (so a golden diff can target it), oracle-blind (no `android-gpuimage-plus` token in path/content — the path uses class/dir names only):
```cpp
// bug
#include "cgeImageHandler.h"
namespace CGE {
jlong nativeCreateHandler(JNIEnv*, jclass) {
    return 0;  // TODO: allocate handler
}
}  // namespace CGE
```
  2. In `groundloop/adapters/estate.py`, add (keep `MockEstate` unchanged):
```python
import shutil
import subprocess


class GitFixtureEstate:
    """Hermetic @base materializer: copy a checked-in plain-file repo snapshot into a fresh
    tmp work-tree and synthesize a SINGLE-COMMIT git repo (the docs §3 anti-leak recipe in
    miniature — no upstream history/tags to mine). Makes `git apply --check` meaningful.
    A repo with no snapshot → an empty dir (which drives the honest localize/apply abstain)."""

    def __init__(self, fixtures_root: str, work_root: str):
        self.fixtures_root = Path(fixtures_root)
        self.work_root = Path(work_root)

    def catalog(self):   # not used by the fix loop, present for RepoEstate parity
        return []

    def materialize(self, repo: RepoRef) -> WorkTree:
        dst = self.work_root / repo.name
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        src = self.fixtures_root / repo.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            for args in (["init", "-q"], ["config", "user.email", "t@t"],
                         ["config", "user.name", "fixeval"], ["add", "-A"],
                         ["commit", "-q", "-m", "base"]):
                subprocess.run(["git", "-C", str(dst), *args], check=True)
        return WorkTree(repo=repo, path=str(dst))
```
  (`Path`, `RepoRef`, `WorkTree` are already imported at the top of estate.py — verify and don't duplicate.)

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit**
```bash
git add groundloop/adapters/estate.py tests/fixtures/repos tests/adapters/test_fixture_estate.py
git commit -m "feat(fixeval): GitFixtureEstate — hermetic single-commit @base work-tree + fixture repo" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `build_fix_atlas_fixture` + the 3-surface consistency guard

**Files:** Read `tests/fixtures/atlas_fixture.py` (the template) + `groundloop/engines/atlas/store.py` (Unit shape); Create `tests/fixtures/fix_atlas_fixture.py`; Test: `tests/fixeval/test_fixture_consistency.py`.

- [ ] **Step 1: Write the failing test** — create `tests/fixeval/test_fixture_consistency.py`:
```python
import json
from pathlib import Path

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals
from groundloop.fixeval.patch import norm_path, touched_files
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

ROOT = Path(__file__).parent.parent / "fixtures"
GOLDEN = ("--- a/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
          "+++ b/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
          "@@ -1 +1 @@\n-// bug\n+// fixed by nativeCreateHandler\n")


def test_three_surface_path_agreement(tmp_path):
    # 1) oracle expected_files[0]
    oracle = json.loads((ROOT / "android_ivi" / "gpuimage-352" / "_oracle" / "oracle.json").read_text())
    expected = norm_path(oracle["expected_files"][0])
    # 2) atlas retrieve returns that path
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    hits = [norm_path(h) for h in AtlasIndex(db).retrieve("android-gpuimage-plus",
                                                          "CGEImageHandler nativeCreateHandler")]
    assert expected in hits, f"retrieve {hits} missing oracle path {expected}"
    # 3) checked-in fixture repo contains that path
    assert (ROOT / "repos" / "android-gpuimage-plus" / expected).is_file()
    # 4) golden diff touches that path
    assert norm_path(touched_files(GOLDEN)[0]) == expected
```

- [ ] **Step 2: Run — expect FAIL** (`build_fix_atlas_fixture` missing).

- [ ] **Step 3: Implement** — read `tests/fixtures/atlas_fixture.py` for the exact `Store`/`Unit` API + how it seeds units, then create `tests/fixtures/fix_atlas_fixture.py` that builds an `atlas.db` where `android-gpuimage-plus` has a Unit whose `file` == the oracle `expected_files[0]` (repo-relative) and whose text carries the discriminative tokens `CGEImageHandler`/`nativeCreateHandler`, so `AtlasIndex.retrieve` returns that exact path first. Mirror `build_atlas_fixture` but with the **real oracle path** as the Unit file (this is the fix vs SP1a's synthetic `{repo}/src.ext` paths). Keep it a SEPARATE builder — do not edit `atlas_fixture.py`.

  *(The implementer must confirm `AtlasIndex.retrieve(repo, query)` arg order + return type by reading `groundloop/adapters/index/atlas.py`, and the `Store.upsert_units`/`Unit` field names by reading `atlas_fixture.py` + `engines/atlas/store.py`. Seed the Unit with `file=<oracle expected_files[0]>`.)*

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit**
```bash
git add tests/fixtures/fix_atlas_fixture.py tests/fixeval/test_fixture_consistency.py
git commit -m "test(fixeval): fix-atlas fixture + 3-surface path-agreement guard" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `localize` + `ModelPatchEngine`

**Files:** Create `groundloop/fixeval/localize.py`, `groundloop/adapters/fix/model_patch.py`; Test: `tests/fixeval/test_localize.py`, `tests/fixeval/test_model_patch_engine.py`.

- [ ] **Step 1: Write failing tests**

`tests/fixeval/test_localize.py`:
```python
from pathlib import Path

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals
from groundloop.fixeval.localize import localize
from groundloop.fixeval.patch import norm_path
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture


def test_localize_returns_gold_path_first(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    sig = Signals(classes=("CGEImageHandler",), methods=("nativeCreateHandler",))
    locs = localize(AtlasIndex(db), "android-gpuimage-plus", sig, summary="crash", k=5)
    assert locs and "cgeImageHandlerAndroid.cpp" in norm_path(locs[0])


def test_localize_empty_signals_returns_empty(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    assert localize(AtlasIndex(db), "android-gpuimage-plus", Signals(), summary="", k=5) == []
```

`tests/fixeval/test_model_patch_engine.py`:
```python
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.mock.model import CannedModel
from groundloop.core.types import Ticket, WorkTree, RepoRef

GOLD = ("```diff\n--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+int nativeCreateHandler(){return 1;}\n```")


def test_propose_extracts_patch_from_model(tmp_path):
    (tmp_path / "x").mkdir(); (tmp_path / "x" / "A.cpp").write_text("// bug\n")
    eng = ModelPatchEngine(CannedModel({"default": GOLD}))
    patch = eng.propose(WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d"), ["x/A.cpp"])
    assert patch.files == ("x/A.cpp",) and "nativeCreateHandler" in patch.diff


def test_propose_empty_model_output_is_abstain(tmp_path):
    eng = ModelPatchEngine(CannedModel({"default": ""}))
    patch = eng.propose(WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d"), [])
    assert patch.diff == "" and patch.files == ()
```

- [ ] **Step 2: Run — expect FAIL** (modules missing). *(Verify `CannedModel`'s constructor + `.complete` signature and `Ticket`/`WorkTree` fields by reading `groundloop/adapters/mock/model.py` + `groundloop/core/types.py` first; adjust the test's `CannedModel({...})` key if it keys on something other than a `default`/substring.)*

- [ ] **Step 3: Implement**

`groundloop/fixeval/localize.py`:
```python
"""Deterministic, oracle-free localize: candidate repo-relative paths from the matched repo."""
from __future__ import annotations

from groundloop.fixeval.patch import norm_path


def localize(index, repo: str, signals, summary: str = "", *, k: int = 5) -> list[str]:
    """Query = signals.tokens() (fallback: summary). index.retrieve(repo, query) → dedup top-k paths.
    Empty result => localize-abstain."""
    query = " ".join(signals.tokens()) if signals.tokens() else summary
    if not query.strip():
        return []
    out: list[str] = []
    for hit in index.retrieve(repo, query):
        p = norm_path(hit)
        if p and p not in out:
            out.append(p)
        if len(out) >= k:
            break
    return out
```

`groundloop/adapters/fix/model_patch.py`:
```python
"""Real PROPOSE-PATCH FixEngine: reads @base snippets from the work-tree, asks the Model for a
unified diff, extracts it. Hermetic via CannedModel; live via GatewayModel. Satisfies core FixEngine."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from groundloop.core.types import Patch, Ticket, WorkTree
from groundloop.fixeval.patch import extract_unified_diff, touched_files


class ModelPatchEngine:
    def __init__(self, model):
        self.model = model

    def _snippet(self, wt_path: str, loc: str, max_lines: int = 40) -> str:
        p = Path(wt_path) / loc
        if not p.is_file():
            return ""
        return f"### {loc}\n" + "\n".join(p.read_text(errors="replace").splitlines()[:max_lines])

    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch:
        snippets = "\n\n".join(self._snippet(worktree.path, loc) for loc in locations)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Candidate files:\n{snippets}\n\n"
                  "Reply ONLY with a unified diff (```diff fenced) that fixes the bug, or empty if you cannot.")
        diff = extract_unified_diff(self.model.complete(prompt) or "")
        return Patch(diff=diff, files=tuple(touched_files(diff)))
```

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit**
```bash
git add groundloop/fixeval/localize.py groundloop/adapters/fix/model_patch.py tests/fixeval/test_localize.py tests/fixeval/test_model_patch_engine.py
git commit -m "feat(fixeval): localize + ModelPatchEngine (model→unified-diff patch)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `FixEvalRunner` + `FixRecord` (the oracle-blind harness)

**Files:** Create `groundloop/fixeval/runner.py`; Test: `tests/fixeval/test_runner.py`, `tests/fixeval/test_runner_oracle_blind.py`.

- [ ] **Step 1: Write failing tests**

`tests/fixeval/test_runner.py`:
```python
import json
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
GOLD = ("```diff\n--- a/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "+++ b/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "@@ -1 +1 @@\n-// bug\n+// fixed nativeCreateHandler\n```")


def _dataset(tmp_path):
    import shutil
    ds = tmp_path / "ds"; ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return str(ds)


def test_happy_path_emits_applying_patch(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    runner = FixEvalRunner(issues=MockJira(_dataset(tmp_path)),
                           estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "work")),
                           tau_margin=0.0, tau_score=0.0)
    arms = build_arms(membership_index=AtlasIndex(db))
    recs = runner.run(load_cases(_dataset(tmp_path)), arms, fixer=ModelPatchEngine(CannedModel({"default": GOLD})))
    logs = next(r for r in recs if r.arm == "membership+logs")
    assert logs.predicted_repo == "android-gpuimage-plus"
    assert logs.patch_emitted and logs.patch_applies and not logs.abstained
    assert logs.cost_usd == 0.0     # CannedModel


def test_match_abstain_yields_no_patch(tmp_path):
    # tau_score huge → Stage-1 abstain → no localize/propose, patch empty
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    runner = FixEvalRunner(issues=MockJira(_dataset(tmp_path)),
                           estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "work")),
                           tau_margin=1.0, tau_score=1e9)
    arms = build_arms(membership_index=AtlasIndex(db))
    recs = runner.run(load_cases(_dataset(tmp_path)), arms, fixer=ModelPatchEngine(CannedModel({"default": GOLD})))
    r = recs[0]
    assert r.abstained and r.abstain_reason == "no_repo_match" and not r.patch_emitted
```

`tests/fixeval/test_runner_oracle_blind.py`:
```python
import pathlib
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner

FIX = Path(__file__).parent.parent / "fixtures"


def test_fix_runner_never_reads_oracle(tmp_path, monkeypatch):
    ds = tmp_path / "ds"; ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    db = AtlasIndex  # placeholder to force import
    from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture
    idx = AtlasIndex(build_fix_atlas_fixture(str(tmp_path / "atlas.db")))
    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])
    FixEvalRunner(issues=MockJira(str(ds)), estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "w")),
                  tau_margin=0.0, tau_score=0.0).run(
        load_cases(str(ds)), build_arms(membership_index=idx),
        fixer=ModelPatchEngine(CannedModel({"default": ""})))
    leaked = [r for r in reads if "_oracle" in pathlib.Path(r).parts]
    assert not leaked, f"fix runner read the oracle: {leaked}"
```

- [ ] **Step 2: Run — expect FAIL** (`FixEvalRunner` missing).

- [ ] **Step 3: Implement** `groundloop/fixeval/runner.py` — mirror `groundloop/eval/runner.py` (read it for the `decide`/`Arm`/`case_catalog` usage), driving localize→fix directly with both abstain gates:
```python
"""Oracle-blind whole-loop fix eval. Per (case x arm): Stage-1 match+abstain (SP1a decide) →
localize → propose → apply-check (bounded refine). Emits an abstain-capable FixRecord. Never calls
run_ticket (frozen/branchless); never reads _oracle/ (offline grade is the sole oracle read)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from groundloop.core.types import RepoRef
from groundloop.eval.abstain import decide
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef, case_catalog
from groundloop.fixeval.localize import localize
from groundloop.fixeval.patch import patch_applies


@dataclass(frozen=True)
class FixRecord:
    case_id: str
    arm: str
    predicted_repo: str | None
    locations: list[str]
    patch_diff: str
    patch_files: list[str]
    patch_emitted: bool
    patch_applies: bool
    abstained: bool
    abstain_reason: str | None
    refine_iters: int
    cost_usd: float


class FixEvalRunner:
    def __init__(self, *, issues, estate, tau_margin: float, tau_score: float, max_refine: int = 1):
        self.issues = issues
        self.estate = estate
        self.tau_margin = tau_margin
        self.tau_score = tau_score
        self.max_refine = max_refine

    def run(self, cases: Sequence[CaseRef], arms: Sequence[Arm], *, fixer) -> list[FixRecord]:
        global_catalog = self.estate.catalog() if hasattr(self.estate, "catalog") else []
        records: list[FixRecord] = []
        for case in cases:
            catalog = case_catalog(case) or global_catalog
            ticket = self.issues.fetch(case.case_id)
            for arm in arms:
                records.append(self._one(case, arm, ticket, catalog, fixer))
        return records

    def _one(self, case, arm, ticket, catalog, fixer) -> FixRecord:
        def rec(**kw):
            base = dict(case_id=case.case_id, arm=arm.name, predicted_repo=None, locations=[],
                        patch_diff="", patch_files=[], patch_emitted=False, patch_applies=False,
                        abstained=True, abstain_reason=None, refine_iters=0, cost_usd=self._cost(fixer))
            base.update(kw)
            return FixRecord(**base)

        signals = arm.extractor.extract(ticket.logs, ticket)
        ranked = arm.index.rank_repos(signals, catalog)
        tm = arm.tau_margin if arm.tau_margin is not None else self.tau_margin
        ts = arm.tau_score if arm.tau_score is not None else self.tau_score
        d = decide(ranked, tau_margin=tm, tau_score=ts)
        if d.predicted is None:                                   # PRIMARY abstain gate
            return rec(abstain_reason="no_repo_match")
        predicted = d.predicted
        c0 = self._cost(fixer)
        wt = self.estate.materialize(RepoRef(predicted))
        locations = localize(arm.index, predicted, signals, ticket.summary)
        if not locations:                                        # SECONDARY: localize abstain
            return rec(predicted_repo=predicted, abstain_reason="no_localization",
                       cost_usd=self._cost(fixer) - c0)
        patch = fixer.propose(wt, ticket, locations)
        applies = patch_applies(patch.diff, wt.path)
        iters = 0
        while patch.diff and not applies and iters < self.max_refine:  # bounded in-world refine
            iters += 1
            patch = fixer.propose(wt, ticket, locations)
            applies = patch_applies(patch.diff, wt.path)
        if not patch.diff or not applies:                        # SECONDARY: unappliable → abstain
            return rec(predicted_repo=predicted, locations=locations, refine_iters=iters,
                       abstain_reason="patch_unappliable", cost_usd=self._cost(fixer) - c0)
        return FixRecord(case_id=case.case_id, arm=arm.name, predicted_repo=predicted,
                         locations=locations, patch_diff=patch.diff, patch_files=list(patch.files),
                         patch_emitted=True, patch_applies=True, abstained=False, abstain_reason=None,
                         refine_iters=iters, cost_usd=self._cost(fixer) - c0)

    @staticmethod
    def _cost(fixer) -> float:
        model = getattr(fixer, "model", None)
        return float(getattr(model, "cost_usd", 0.0))
```
  *(Confirm `Arm` has `extractor`/`index`/`tau_margin`/`tau_score` and `decide` returns `.predicted` by reading `groundloop/eval/{arms,abstain}.py` — they do per SP1a. The cost delta reads `fixer.model.cost_usd` — 0.0 for CannedModel, real for GatewayModel.)*

- [ ] **Step 4: Run — expect PASS** (both test files). Full suite + ruff.

- [ ] **Step 5: Commit**
```bash
git add groundloop/fixeval/runner.py tests/fixeval/test_runner.py tests/fixeval/test_runner_oracle_blind.py
git commit -m "feat(fixeval): FixEvalRunner + FixRecord — oracle-blind localize→fix with two abstain gates" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

*(Phase B ends: the hermetic fix-loop harness runs end-to-end over fixtures + a canned model.)*

---

# PHASE C — grading + CLI + gated live (Tasks 7–11)

### Task 7: expose `required_apis` on `EvalOracle`

**Files:** Modify `groundloop/eval/dataset.py`; Test: `tests/eval/test_negatives_dataset.py` (append).

- [ ] **Step 1: Write the failing test** — append:
```python
def test_load_eval_oracle_reads_required_apis(tmp_path):
    case = _write_case(tmp_path, "r", {"owning_repo": "x", "required_apis": ["nativeCreateHandler"]})
    assert load_eval_oracle(case).required_apis == ("nativeCreateHandler",)
```
- [ ] **Step 2: Run — expect FAIL** (`EvalOracle` has no `required_apis`).
- [ ] **Step 3: Implement** — add `required_apis: tuple[str, ...] = ()` to the `EvalOracle` dataclass and `required_apis=tuple(raw.get("required_apis", []))` in `load_eval_oracle` (frozen `core.types.Oracle` untouched).
- [ ] **Step 4: Run — expect PASS** (+ existing `test_negatives_dataset.py` green). Ruff.
- [ ] **Step 5: Commit** `feat(fixeval): expose required_apis on EvalOracle`.

---

### Task 8: `grade_fix_all` — file_recall / patch_applies / required_api / resolved-advisory

**Files:** Create `groundloop/fixeval/scorecard.py`; Test: `tests/fixeval/test_scorecard.py`.

- [ ] **Step 1: Write the failing test** — create `tests/fixeval/test_scorecard.py`:
```python
from groundloop.eval.dataset import EvalOracle
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all

REL = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


def _rec(**kw):
    base = dict(case_id="c", arm="a", predicted_repo="r", locations=[REL], patch_diff="+ nativeCreateHandler",
                patch_files=[REL], patch_emitted=True, patch_applies=True, abstained=False,
                abstain_reason=None, refine_iters=0, cost_usd=0.0)
    base.update(kw)
    return FixRecord(**base)


def test_resolved_positive(tmp_path):
    oracle = EvalOracle("r", expected_files=(REL,), required_apis=("nativeCreateHandler",))
    card = grade_fix_all([_rec()], oracle_by_case={"c": oracle})
    a = card["arms"]["a"]
    assert a["file_recall@1"]["value"] == 1.0 and a["patch_apply_rate"] == 1.0
    assert a["required_api_pass_rate"]["value"] == 1.0
    assert a["resolved_rate"]["value"] == 1.0 and a["n_gradeable"] == 1 and a["n_excluded"] == 0


def test_case_without_required_apis_excluded_from_resolved(tmp_path):
    oracle = EvalOracle("r", expected_files=(REL,), required_apis=())   # not grounded-gradeable
    card = grade_fix_all([_rec()], oracle_by_case={"c": oracle})
    a = card["arms"]["a"]
    assert a["n_gradeable"] == 0 and a["n_excluded"] == 1
    assert a["resolved_rate"]["value"] is None      # advisory, undefined over empty subset
```

- [ ] **Step 2: Run — expect FAIL** (`grade_fix_all` missing).

- [ ] **Step 3: Implement** `groundloop/fixeval/scorecard.py` — reuse `eval/metrics.py` (`recall_at_k`, `success_at_k`, `wilson`) and `eval/cost.py`, and `fixeval/patch.references_api`:
```python
"""Offline grade for the fix loop — the SOLE oracle read. Mirrors eval/scorecard.grade_all."""
from __future__ import annotations

from collections import defaultdict

from groundloop.eval.metrics import recall_at_k, success_at_k, wilson
from groundloop.fixeval.patch import norm_path, references_api


def _wrap(v, n):
    if not n:
        return {"value": None, "n": 0}
    return {"value": v, "wilson95": list(wilson(round(v * n), n)), "n": n}


def grade_fix_all(records, *, oracle_by_case, ks=(1, 3, 5)) -> dict:
    by_arm = defaultdict(list)
    for r in records:
        by_arm[r.arm].append(r)
    arms = {}
    for arm, recs in by_arm.items():
        n = len(recs)
        answered = [r for r in recs if r.patch_emitted]
        # localization over cases WITH expected_files
        loc = [(r, oracle_by_case[r.case_id]) for r in recs if oracle_by_case[r.case_id].expected_files]
        def _fr(k):
            if not loc:
                return {"value": None, "n": 0}
            vals = [recall_at_k([norm_path(x) for x in r.locations],
                                {norm_path(e) for e in o.expected_files}, k) for r, o in loc]
            return _wrap(sum(vals) / len(vals), len(vals))
        # required apis over cases WITH required_apis
        api = [(r, oracle_by_case[r.case_id]) for r in recs if oracle_by_case[r.case_id].required_apis]
        api_pass = [all(references_api(r.patch_diff, a) for a in o.required_apis) for r, o in api]
        # resolved (advisory) over grounded-gradeable = expected_files AND required_apis both present
        grd = [(r, oracle_by_case[r.case_id]) for r in recs
               if oracle_by_case[r.case_id].expected_files and oracle_by_case[r.case_id].required_apis]
        solved = [r for r, o in grd if r.patch_applies
                  and recall_at_k([norm_path(x) for x in r.locations], {norm_path(e) for e in o.expected_files}, 1) > 0
                  and all(references_api(r.patch_diff, a) for a in o.required_apis)]
        arms[arm] = {
            "n": n,
            "fix_coverage": len(answered) / n if n else 0.0,
            "abstain_rate": (n - len(answered)) / n if n else 0.0,
            **{f"file_recall@{k}": _fr(k) for k in ks},
            "patch_apply_rate": (sum(r.patch_applies for r in answered) / len(answered)) if answered else 0.0,
            "required_api_pass_rate": _wrap(sum(api_pass) / len(api_pass), len(api_pass)) if api_pass else {"value": None, "n": 0},
            "resolved_rate": _wrap(len(solved) / len(grd), len(grd)) if grd else {"value": None, "n": 0},
            "n_gradeable": len(grd),
            "n_excluded": n - len(grd),
            "cost_total": sum(r.cost_usd for r in recs),
            "cost_per_solved": (sum(r.cost_usd for r in recs) / len(solved)) if solved else None,
        }
    return {"arms": arms, "n_cases": len({r.case_id for recs in by_arm.values() for r in recs})}
```

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit** `feat(fixeval): grade_fix_all (file_recall/patch_applies/required_api/resolved-advisory + cost)`.

---

### Task 9: `fabrication_rate` + whole-loop Φ_c + a 2nd Bucket-1 fixture

**Files:** Modify `groundloop/fixeval/scorecard.py`; Create a Bucket-1 fixture `tests/fixtures/android_ivi/negatives/notdefect-1/`; Test: `tests/fixeval/test_fabrication.py`.

- [ ] **Step 1: Write the failing test** — create `tests/fixeval/test_fabrication.py`:
```python
from groundloop.eval.dataset import EvalOracle
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all


def _r(patch_emitted, applies, abstained):
    return FixRecord("c", "a", "r", [], "+x" if patch_emitted else "", [], patch_emitted, applies,
                     abstained, None if patch_emitted else "x", 0, 0.0)


def test_bucket1_fabrication_penalized():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_fix_all([_r(True, True, False)], oracle_by_case={"c": oo}, c_values=(1.0,))
    a = card["arms"]["a"]
    assert a["fabrication_rate"]["value"] == 1.0 and a["phi_c"]["1.0"] == -1.0


def test_bucket1_abstain_rewarded():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_fix_all([_r(False, False, True)], oracle_by_case={"c": oo}, c_values=(1.0,))
    a = card["arms"]["a"]
    assert a["fabrication_rate"]["value"] == 0.0 and a["phi_c"]["1.0"] == 1.0
```

- [ ] **Step 2: Run — expect FAIL** (`fabrication_rate`/`phi_c` keys missing).

- [ ] **Step 3: Implement** — extend `grade_fix_all(records, *, oracle_by_case, ks=(1,3,5), c_values=(0.5,1.0,2.0))`: import `phi_c` from `groundloop.eval.metrics`; per arm build phi records `{answered:=r.patch_emitted, answerable:=o.is_answerable, correct:=(r.patch_applies and file_recall@1>0)}`; add `"phi_c": {str(c): phi_c(phi_recs, c=c) for c in c_values}`; and `fabrication_rate` = over Bucket-1 (`not o.is_answerable`) cases, the fraction that emitted a clean-applying patch — `_wrap(sum(r.patch_emitted and r.patch_applies for bucket1) / n_bucket1, n_bucket1)`. Also create the 2nd Bucket-1 fixture `notdefect-1` (a `not_a_defect` case: `_oracle/oracle.json` with `owning_repo="__NOT_A_DEFECT__"`, `is_answerable=false`, `negative_class="not_a_defect"`, `expected_files=[]`; opaque oracle-blind ticket) so fabrication has ≥2 Bucket-1 cases across the fixture set.

- [ ] **Step 4: Run — expect PASS** (+ existing scorecard tests green). Ruff.

- [ ] **Step 5: Commit** `feat(fixeval): fabrication_rate + whole-loop phi_c (Bucket-1 refusal grading) + not_a_defect fixture`.

---

### Task 10: `report.py` board + `gloop fixeval` + `gloop compare`

**Files:** Create `groundloop/fixeval/report.py`, `groundloop/fixeval/compare.py`; Modify `groundloop/cli/__init__.py`; Test: `tests/fixeval/test_compare.py`, `tests/fixeval/test_cli_fixeval.py`.

- [ ] **Step 1: Write failing tests**

`tests/fixeval/test_compare.py`:
```python
from groundloop.fixeval.compare import compare


def test_newly_solved_and_broken():
    base = {"c1": True, "c2": False, "c3": None}
    head = {"c1": False, "c2": True, "c3": True}
    d = compare(base, head)
    assert d["newly_solved"] == ["c2"] and d["newly_broken"] == ["c1"]   # None never counts
```

`tests/fixeval/test_cli_fixeval.py`:
```python
import json
import shutil
from pathlib import Path

from groundloop.cli import main
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"


def test_fixeval_cli_writes_scorecard(tmp_path, monkeypatch):
    ds = tmp_path / "ds"; ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    # force the hermetic canned model into the fixeval composition (monkeypatch the GatewayModel factory
    # the CLI uses — the implementer wires _run_fixeval to accept an injected model for tests, mirroring
    # how test_cli_eval builds arms; if the CLI hardcodes GatewayModel, add a KLOOP_* guard so a missing
    # gateway falls back to CannedModel with a default golden diff for the smoke test).
    out = tmp_path / "fix-scorecard.json"
    rc = main(["fixeval", "--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
               "--index-db", db, "--out", str(out), "--repos", str(FIX / "repos")])
    assert rc == 0
    card = json.loads(out.read_text())
    assert "arms" in card and out.with_suffix(".md").is_file()
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement**
  1. `groundloop/fixeval/compare.py`:
```python
"""Δ optimization surface (ported from bfl/eval/compare.py) — None never counts as solved/broken."""
from __future__ import annotations


def compare(base: dict, head: dict) -> dict:
    keys = sorted(set(base) | set(head))
    return {
        "newly_solved": [k for k in keys if base.get(k) is False and head.get(k) is True],
        "newly_broken": [k for k in keys if base.get(k) is True and head.get(k) is False],
    }
```
  2. `groundloop/fixeval/report.py` — `render_fix_markdown(card)` mirroring `eval/report.py`: a per-arm table (arm | n | file_recall@1 | api_pass | apply_rate | resolved(adv) | fabrication | $/solved) + a header noting `resolved_rate` is advisory over `n_gradeable`/`n_excluded`.
  3. `groundloop/cli/__init__.py` — add `_run_fixeval` + a `fixeval` subparser (`--dataset --catalog --index-db --out --repos [--tau-margin --tau-score]`) mirroring `_run_eval`: build `AtlasIndex(index-db)`, `GitFixtureEstate(--repos, dataset/_work)`, `build_arms`, run `FixEvalRunner` with the model engine, `grade_fix_all` (oracle read here only via `load_eval_oracle`), write `fix-scorecard.json` + `.md`, print a per-arm board line. For the hermetic smoke path, select `CannedModel` when `KLOOP_PRODUCE_API_KEY` is unset (a bundled default golden diff), else `GatewayModel` (Task 11). Add a `gloop compare --base <scorecard.json> --head <scorecard.json>` subcommand that reads two boards' per-arm resolved bits and prints `compare(...)`.

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit** `feat(fixeval): gloop fixeval + compare + markdown board`.

---

### Task 11 (GATED): `GatewayModel` — real deepseek propose-patch

**Files:** Create `groundloop/adapters/model/__init__.py` (empty), `groundloop/adapters/model/gateway.py`; Test: `tests/e2e/test_fixeval_live.py`.

- [ ] **Step 1: Write the gated test** — create `tests/e2e/test_fixeval_live.py` (skipif, mirroring `tests/e2e/test_judge_arm_live.py`):
```python
import os
import pytest

_GATE = bool(os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_PRODUCE_API_KEY not set — live GatewayModel skipped")
def test_gateway_model_proposes_a_diff():
    from groundloop.adapters.model.gateway import GatewayModel
    from groundloop.fixeval.patch import extract_unified_diff
    m = GatewayModel(os.environ["KLOOP_PRODUCE_BASE_URL"], os.environ["KLOOP_PRODUCE_API_KEY"],
                     os.environ.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"))
    text = m.complete("Reply with a unified diff (```diff) that adds a line `int x=1;` to file a.c.")
    assert isinstance(text, str)
    assert m.calls == 1 and m.cost_usd >= 0.0
```

- [ ] **Step 2: Run — confirm SKIP** (gate off): `.venv/bin/python -m pytest tests/e2e/test_fixeval_live.py -q` → skipped.

- [ ] **Step 3: Implement** `groundloop/adapters/model/gateway.py` — clone `GatewayJudge` (`groundloop/adapters/index/atlas_judge.py`): a `Model`-port impl `GatewayModel(base_url, api_key, model, timeout=60)` with `complete(prompt) -> str` (POST `/chat/completions`, temperature 0, return `choices[0].message.content`), tracking cumulative `.cost_usd` (via `eval/cost.cost_of` over usage tokens), `.input_tokens`/`.output_tokens`/`.calls`, and a graceful `except → ""` fallback. Keep it OUT of `adapters/mock/`. Then wire it into `_run_fixeval` (Task 10) behind the `KLOOP_PRODUCE_API_KEY` branch.

- [ ] **Step 4: Run.** `.venv/bin/python -m pytest -q` (full; the live test skips) + ruff.

- [ ] **Step 5: Commit** `feat(fixeval): GatewayModel live propose-patch (Type-2 gated)`.

---

## Out of scope (gated follow-ons, NOT in this plan)
- **Real `GitArchiveEstate`** over corpora at pinned SHAs — needs `corpora/corpus.toml` (absent) + a miner-emitted `base_sha=fix^` (miner records `merge_commit_sha` only; add an oracle-side `base_sha` key in a future SP1b patch) + multi-GB AAOS trees.
- **Test-execution `resolved`** (Tier-3) — AAOS repos lack runnable suites (hour-long Soong/Cuttlefish); the spec defers it. This plan ships `resolved_rate` as the localization∧required-api authority proxy, advisory over the grounded-gradeable subset.
- **`skills` as a measured arm** — that is SP3.

## Self-Review (against the spec + workflow verdicts)

**Spec coverage (§2):** fix engine (Agentless-style `ModelPatchEngine`, T5) · eval surface `gloop fixeval`/`compare` (T10) · headline `file_recall`+`patch_applies`+`required_api` + `resolved_rate` advisory (T8) · whole-loop `fabrication_rate` (T9) · gated live model (T11).

**Frozen-core (verdict CONFIRMED):** no `core/` edit — `FixEvalRunner` drives ports directly (T6), abstain = `Patch(diff="")`, grade extras ride oracle-side (`EvalOracle.required_apis`, T7). Verified against `core/workflow.py`/`ports.py`/`types.py`.

**Hermetic (verdict PARTIAL — the named gates are honored):** `git apply --check` over a synthesized fixture repo (T2/T3, git-only); localize via a separate `build_fix_atlas_fixture` (T4); `decide()` runs BEFORE `propose` (T6) so fabrication can't degenerate; `CannedModel` drives the whole loop; the **3-surface path agreement** is guarded (T4 `test_fixture_consistency`) with a `norm_path` helper (T1). Live model + real materializer + test-execution `resolved` are gated/deferred (T11 + Out-of-scope).

**Risk mitigations baked in:** path-drift guard (T4); basename/`norm_path` matching not brittle exact-path (T1/T8); `--whitespace=nowarn` + LF golden diff (T2); no nested `.git` in fixtures (T3 synthesizes at materialize); oracle-blind read-spy on the new runner (T6); ≥2 Bucket-1 fixtures for fabrication (T9); `resolved_rate` excludes non-grounded-gradeable cases (T8).

**Type consistency:** `FixRecord` fields (T6) consumed by `grade_fix_all` (T8/T9); `norm_path`/`touched_files`/`references_api`/`patch_applies` (T1/T2) used by T4/T6/T8; `GitFixtureEstate` (T3) used by T6/T10; `EvalOracle.required_apis` (T7) read by T8. The fixture repo-relative path is a single value sourced from the gpuimage-352 oracle `expected_files[0]` across T3/T4/T6/T8.
