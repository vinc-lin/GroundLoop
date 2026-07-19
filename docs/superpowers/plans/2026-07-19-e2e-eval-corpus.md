# Realistic End-to-End Eval Corpus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Build the hermetic machinery for a realistic, full-end-to-end `[proxy]` eval corpus — a crash-log +
merged-fix issue filter, a committed case manifest, and an honest end-to-end funnel report — and trim the
over-built eval to what's used. The live corpus build + first funnel read are **gated Type-2** (need `gh` +
gateway + an atlas), run by the user; **this plan's merge gate is the hermetic, fixture-tested machinery.**

**Architecture:** Extend the existing labs packages (`mine`/`fixeval`/`grade`/`eval`/`synth`) — no new subsystem,
no `core/` or atlas-schema edit. All new code is labs (reached via the sanctioned lazy seam). Every task is
TDD-hermetic (no network / no real LLM).

**Tech Stack:** Python 3.12, `.venv`. Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check
groundloop tests` (line 110). Spec: `docs/superpowers/specs/2026-07-19-e2e-eval-corpus-design.md`.

**Hard constraints:** never edit `groundloop/core/`; never alter the atlas schema; suite green + ruff clean per
commit; the import-boundary contract stays green; secret hygiene (the committed manifest holds only public
issue/PR/SHA refs — no keys/LAN IPs/`.env`).

---

### Task 1: Crash-log + merged-fix admission filter (the representative-shape gate)

**Files:**
- Read first: `groundloop/mine/signal.py` (`split_issue_body`/`classify`), `groundloop/mine/filters.py`
  (`is_minable`/`production_files`), `groundloop/mine/harvest.py` (issue→merged-closer), `groundloop/mine/gh_miner.py`
  (the `mine()` admit path).
- Modify: `groundloop/mine/signal.py` (+ a crash-signature predicate), `groundloop/mine/gh_miner.py` (admit gate),
  `groundloop/cli/__init__.py` (the `mine` subparser flags).
- Test: `tests/mine/test_crash_filter.py` (new).

- [ ] **Step 1: Read** the four `mine/` files above. Note the real signature of `classify`/`split_issue_body`,
  what a harvested `Candidate` carries (does it expose the merged PR + its touched files?), and where `mine()`
  decides to admit/emit a case. Adapt all names below to what you find.

- [ ] **Step 2: Write the failing test** `tests/mine/test_crash_filter.py`:

```python
from groundloop.mine.signal import has_crash_signature  # adapt name to what you implement

_STACK = """Fatal Exception: java.lang.IllegalStateException: bad state
    at com.example.player.Decoder.init(Decoder.java:88)
    at com.example.player.Player.start(Player.java:42)"""
_NATIVE = "#00 pc 0001a2b4  /system/lib64/libplayer.so (Decoder::feed(char const*)+44)"
_LOGCAT = "E AudioTrack: AudioFlinger could not create track, status: -12"
_PROSE = "The settings screen should remember my sort order between launches. It doesn't."

def test_crash_signatures_detected():
    assert has_crash_signature(_STACK)
    assert has_crash_signature(_NATIVE)
    assert has_crash_signature(_LOGCAT)

def test_prose_rejected():
    assert not has_crash_signature(_PROSE)
    assert not has_crash_signature("")
```

- [ ] **Step 3: Run → FAIL** (`ImportError`/undefined): `.venv/bin/python -m pytest tests/mine/test_crash_filter.py -q`.

- [ ] **Step 4: Implement `has_crash_signature(body: str) -> bool`** in `mine/signal.py` — a regex OR over: a
  Java stack frame (`^\s*at\s+[\w.$]+\([\w.]+:\d+\)` multiline), a native backtrace frame (`#\d+\s+pc\s+[0-9a-f]+`),
  an exception/error header (`\b\w+(Exception|Error):`), and a logcat priority line (`^[VDIWEF]\s+\w+:`). Reuse
  `mine/android_ivi` regex idioms if present. Run Step 2 → PASS.

- [ ] **Step 5: Add the admission gate** to `mine()` behind two flags: admit a case only when
  `require_crash_log` ⇒ `has_crash_signature(issue_body)` AND `require_merged_fix` ⇒ the candidate has a merged-PR
  closer whose `production_files(...)` is non-empty. Add `--require-crash-log` / `--require-merged-fix`
  (`store_true`) to the `mine` subparser and thread them into `mine(...)`. Keep default behavior (both False)
  byte-identical.

- [ ] **Step 6: Add an admit-gate unit test** to `tests/mine/test_crash_filter.py` exercising the gate at the
  function level (construct a fake candidate with/without a crash body and with/without a merged-fix; assert
  admit/reject) — adapt to the real `mine()`/candidate shape you read in Step 1. If `mine()` is too network-coupled
  to unit-test directly, factor the pure admit decision into a helper `admit_e2e(candidate, *, require_crash_log,
  require_merged_fix) -> bool` and test THAT.

- [ ] **Step 7: Verify + commit.** `.venv/bin/python -m pytest -q` (green) · `ruff check groundloop tests` ·
  `pytest tests/architecture/test_import_boundary.py -q` · `git diff --stat -- groundloop/core groundloop/engines/atlas/store.py` empty.
```bash
git add groundloop/mine/signal.py groundloop/mine/gh_miner.py groundloop/cli/__init__.py tests/mine/test_crash_filter.py
git commit -m "feat(mine): crash-log + merged-fix admission gate for the e2e corpus

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The committed case manifest (schema · writer · loader)

**Files:**
- Read first: `groundloop/mine/emit.py` (`MinedCase`/`emit_case` — the fields a mined case already carries).
- Create: `groundloop/mine/manifest.py`, `groundloop/mine/data/e2e_manifest.toml` (committed placeholder).
- Modify: `groundloop/mine/gh_miner.py` (emit the manifest when the e2e flags are set).
- Test: `tests/mine/test_manifest.py` (new).

- [ ] **Step 1: Read `emit.py`** to see which of the manifest fields a mined case already has (owning_repo,
  expected_files, required_apis, issue/pr refs, SHAs) so the writer maps from the real case object.

- [ ] **Step 2: Write the failing test** `tests/mine/test_manifest.py`:

```python
from groundloop.mine.manifest import E2ECase, write_manifest, load_manifest

_CASE = E2ECase(repo="oboe", issue_number=1417, issue_url="https://github.com/google/oboe/issues/1417",
                pr_number=1420, pr_url="https://github.com/google/oboe/pull/1420",
                base_sha="a"*40, fix_sha="b"*40, owning_repo="oboe",
                expected_files=("src/flowgraph/FlowGraphNode.cpp",), required_apis=("pullData",))

def test_manifest_roundtrip(tmp_path):
    p = tmp_path / "m.toml"
    write_manifest([_CASE], p)
    got = load_manifest(p)
    assert got == [_CASE]

def test_manifest_has_no_bulky_data(tmp_path):
    p = tmp_path / "m.toml"
    write_manifest([_CASE], p)
    text = p.read_text()
    assert "logs" not in text and "diff" not in text and "fix_patch" not in text  # recipe+oracle only
```

- [ ] **Step 3: Run → FAIL.** `.venv/bin/python -m pytest tests/mine/test_manifest.py -q`.

- [ ] **Step 4: Implement `mine/manifest.py`** — a frozen `E2ECase` dataclass with exactly the 10 fields above
  (`expected_files`/`required_apis` as tuples), `write_manifest(cases, path)` (deterministic TOML, sorted by
  repo+issue_number — no `Date.now`), and `load_manifest(path) -> list[E2ECase]`. No bulky fields (no diff/logs).
  Run Step 2 → PASS. Create `groundloop/mine/data/e2e_manifest.toml` as a committed placeholder with a header
  comment (`# populated by: gloop mine --require-crash-log --require-merged-fix ...`) and zero cases.

- [ ] **Step 5: Wire emit** — when `mine()` runs with the e2e flags (Task 1), also collect each admitted case's
  provenance into an `E2ECase` and `write_manifest(...)` to the run's output dir. Reuse the existing case fields;
  don't refetch. (No network in tests — this path is only exercised live; the unit test covers the writer/loader.)

- [ ] **Step 6: Verify + commit.** Full suite green · ruff · boundary · core/schema zero-diff.
```bash
git add groundloop/mine/manifest.py groundloop/mine/data/e2e_manifest.toml groundloop/mine/gh_miner.py tests/mine/test_manifest.py
git commit -m "feat(mine): committed e2e case manifest (schema, writer, loader)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The end-to-end funnel report

**Files:**
- Read first: `groundloop/fixeval/scorecard.py` (`grade_fix_all` return shape) + `groundloop/fixeval/report.py`
  (`render_fix_markdown` — the existing renderer to match style).
- Create: the funnel renderer (add to `groundloop/fixeval/report.py`).
- Test: `tests/fixeval/test_funnel.py` (new).

- [ ] **Step 1: Read** `grade_fix_all`'s output dict + the per-case rows it exposes (match recall@1, file_recall@k,
  patch_apply, resolved_rate_strict, required_api_pass) and `render_fix_markdown`'s shape. The funnel REUSES these
  numbers — do not recompute metrics.

- [ ] **Step 2: Write the failing test** `tests/fixeval/test_funnel.py`:

```python
from groundloop.fixeval.report import render_e2e_funnel  # new

_SCORE = {  # adapt keys to grade_fix_all's REAL shape read in Step 1
    "n": 3,
    "match_recall_at_1": 0.667,
    "file_recall_at_1": 0.333, "file_recall_at_5": 0.667,
    "patch_apply_rate": 0.5, "resolved_rate_strict": 0.333, "required_api_pass_rate": 0.333,
}
_ROWS = [{"case_id": "oboe-1417", "match_hit": True, "file_at_5": True, "resolved": True}]  # adapt

def test_funnel_reports_each_stage_and_mock_bind():
    md = render_e2e_funnel(_SCORE, _ROWS)
    assert "match" in md.lower() and "0.667" in md          # match stage
    assert "localize" in md.lower() and "file@5" in md       # localize stage
    assert "resolved" in md.lower()                          # fix stage
    assert "mock" in md.lower()                              # submit/bind honestly mock
    assert "bound" not in md.lower()                         # never scored as bound
    assert "oboe-1417" in md                                 # per-case row

def test_funnel_empty_is_safe():
    md = render_e2e_funnel({"n": 0}, [])
    assert isinstance(md, str) and "0" in md
```

- [ ] **Step 3: Run → FAIL.**

- [ ] **Step 4: Implement `render_e2e_funnel(scorecard, per_case) -> str`** in `fixeval/report.py` — a markdown
  funnel: a header table `stage | metric | value` with rows match(recall@1) → localize(file@1/@5) →
  fix(patch_applies / resolved_strict / required_api_pass), then a literal
  `**submit / bind:** mock — not scored (live Gerrit/JIRA out of scope)` line, then a per-case table
  (case_id | match | localize@5 | resolved). Read values straight from the dict (adapt to the real keys). Handle
  `n==0`. Run Step 2 → PASS.

- [ ] **Step 5: Verify + commit.** Full suite green · ruff · core/schema zero-diff.
```bash
git add groundloop/fixeval/report.py tests/fixeval/test_funnel.py
git commit -m "feat(fixeval): honest end-to-end funnel report (submit/bind reported as mock)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Trim the genuinely-dead metrics

**Files:**
- Modify: `groundloop/eval/metrics.py`, `groundloop/synth/functional.py`, and their tests.

- [ ] **Step 1: Confirm they are dead** (verify before deleting):
  `grep -rn "ndcg_at_k\|success_at_k\|build_functional_negatives" groundloop | grep -v "def \|_test\|tests/"` and
  `grep -rn "from groundloop.eval.metrics import\|metrics.mrr\|metrics.ndcg" groundloop`. Expected: the only
  non-def references are in `tests/`. If the standalone `mrr()` (NOT the inline scorecard MRR) is imported by any
  non-test module, LEAVE it; delete only what is truly caller-free. Record what you found.

- [ ] **Step 2: Remove the confirmed-dead symbols** — `ndcg_at_k`, `success_at_k`, and the standalone `mrr()`
  from `eval/metrics.py` (only those with zero non-test callers); `build_functional_negatives` from
  `synth/functional.py`. Remove or trim the corresponding assertions in `tests/eval/test_metrics.py` and any
  `build_functional_negatives` test. Do NOT touch the inline MRR in `eval/scorecard.py`, and do NOT touch the
  abstention/negatives/phi_c honesty stack (that is quarantined via docs in Task 5, not deleted).

- [ ] **Step 3: Verify + commit.** `.venv/bin/python -m pytest -q` (green — the removed symbols' tests are gone) ·
  ruff · core/schema zero-diff.
```bash
git add groundloop/eval/metrics.py groundloop/synth/functional.py tests/
git commit -m "refactor(eval): retire dead metrics (ndcg/success_at_k/standalone mrr) + orphaned synth negatives

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Docs — the reality section + the initiative record

**Files:**
- Modify: `docs/evaluation.md`, `docs/capabilities.md`, `docs/STATUS.md`.

- [ ] **Step 1: `docs/evaluation.md`** — add a section "**What's actually exercised vs idle**" recording the
  audit's finding: reads use recall@k / file@k / patch_apply / resolved_strict / by_bug_kind; the honesty/
  selective/abstention/negatives stack + KB-as-eval are **built but not exercised by any effectiveness read**
  (quarantined, not deleted); and the substrate shift to the realistic end-to-end corpus (crash-log + merged-fix,
  committed manifest, honest funnel, submit/bind = mock). State plainly that fix is *measured, expected weak*.

- [ ] **Step 2: `docs/capabilities.md`** — note the e2e corpus machinery (mine crash-filter + manifest + funnel)
  as labs/eval-infra; record that the mine74 prose regime is superseded as the primary `[proxy]` localize
  substrate; note the retired dead metrics.

- [ ] **Step 3: `docs/STATUS.md`** — add a dated `### ... (2026-07-19) ✅` entry under `## Done`: the hermetic
  e2e-corpus machinery shipped (filter/manifest/funnel + trim), the first-principle framing (grounding over
  narrative; small-real over large-fake; submit/bind honestly mock), and the **OPEN gated-live follow-up**: run
  `gloop mine --require-crash-log --require-merged-fix` over the broadened repo set → commit the manifest → build
  the atlas → run the funnel read (`[proxy]`). Add that follow-up to `## Next steps`.

- [ ] **Step 4: Verify + commit.** `.venv/bin/python -m pytest -q` (green) · re-read edits for accuracy (no
  overclaim — no live read has run; this is machinery only).
```bash
git add docs/evaluation.md docs/capabilities.md docs/STATUS.md
git commit -m "docs: record the e2e-corpus machinery + the 'exercised vs idle' eval reality section

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:** §2 quality-bar/filter → Task 1; §3 manifest → Task 2; §5 funnel + mock bind → Task 3; §6
  trim (retire dead / quarantine) → Task 4 (code) + Task 5 (docs quarantine labels); §7 invariants → the
  per-task zero-diff + boundary checks; §8 non-goals honored (no closure, no negatives, no Tier A). The live
  corpus build + funnel read are explicitly gated follow-ups (spec §10), recorded in Task 5, not merge gates.
- **No new subsystem / no over-build:** every task extends an existing labs package with a thin predicate /
  dataclass / renderer, reusing `grade_fix_all` (matches the user's "simplify" intent).
- **Placeholder scan:** fixture names/keys in Tasks 1–3 are flagged "adapt to the real shape read in Step 1"; no
  TBDs.
- **Type consistency:** `has_crash_signature(str)->bool`, `E2ECase` (10 fields), `render_e2e_funnel(scorecard,
  per_case)->str` used consistently across their task + test.
- **Merge gate = hermetic suite green + ruff + boundary + core/schema zero-diff.** No task requires network or a
  real LLM.
