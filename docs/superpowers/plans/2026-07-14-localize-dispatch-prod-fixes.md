# Localize Dispatch — Production Fixes (Bugs 1/2/3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the three code-verified bugs behind the `[production]` `--localize dispatch` `file@1 = 0/10`: (1) the discriminator never routes functional tickets to semantic under `--match-arm component`; (2) the localize query wastes the extracted code tokens; (3) grading path-prefix mismatch marks rank-1 hits as misses.

**Architecture:** All fixes are composition-root / grading-only — **no `core/` or schema edits.** Bug 1 refines `is_functional_localize` to key on *stack-frame evidence* (`methods`/native `symbols`) instead of anchor-emptiness. Bug 2 makes `LocalizeDispatchIndex`'s crash branch query from the stashed `signals` code tokens. Bug 3 adds a grading-only `canonical_path` (package-qualified suffix) so differing source roots still match.

**Tech Stack:** Python 3.12, pytest, ruff (line 110), `/mnt/x/code/GroundLoop/.venv`. Branch `localize-dispatch-prod-fixes` off master (`9710536`).

**Context — the RCA is verified in code:** `ComponentExtractor.extract` (`component_signals.py:31-36`) never sets `PROSE_MARK` and fills `classes` from logcat; `AndroidSignalExtractor` fills `methods` ONLY from `_FRAME` (`at pkg.Class.method(`) and native `symbols` from `_NATIVE`; `core/workflow.py:33` retrieves with `ticket.summary` only; `norm_path` (`fix/patch.py:74`) + exact `recall_at_k` (`eval/metrics.py:11`) don't reconcile module prefixes.

---

## Task 1: Bug 1 (frame-evidence discriminator) + Bug 2 (crash-branch code query)

**Files:**
- Modify: `groundloop/domains/android_ivi/functional_signals.py` (refine `is_functional_localize`; add `code_query`)
- Modify: `groundloop/adapters/index/localize_dispatch.py` (`retrieve` crash branch uses `code_query`)
- Modify: `tests/test_localize_dispatch.py` (add new tests; **fix the 2 existing routing tests broken by the discriminator change**)

- [ ] **Step 1: Write/adjust the failing tests.** In `tests/test_localize_dispatch.py`:

(a) Add discriminator tests for the new behavior (append near the other `is_functional_localize` tests):

```python
def test_is_functional_localize_classes_only_no_frame_is_true():
    # production shape: logcat mentions FQ classes (no stack frame) -> functional -> semantic
    sig = Signals(classes=("com.x.Foo", "com.y.Bar"), packages=("com.x", "com.y"))
    assert is_functional_localize(sig) is True


def test_is_functional_localize_stack_frame_method_is_false():
    assert is_functional_localize(Signals(classes=("com.x.Foo",), methods=("bar",))) is False


def test_is_functional_localize_prose_mark_with_other_symbols_is_true():
    sig = Signals(symbols=(PROSE_MARK + "wrong label", "extra"))
    assert is_functional_localize(sig) is True
```

(b) **Fix the two existing routing tests** that assumed `classes` ⇒ crash (now `classes`-only ⇒ functional). Change their crash-case signals from `Signals(classes=("com.x.Foo",))` to `Signals(methods=("bar",))`:

- In `test_retrieve_routes_crash_to_fts5_after_rank`: `d.rank_repos(Signals(methods=("bar",)), [RepoRef("r")])`
- In `test_rank_repos_refreshes_stash_across_tickets_on_one_instance`: first (crash) rank → `Signals(methods=("bar",))`.

(c) Add the Bug 2 query test (append; needs a query-echoing fake):

```python
class _EchoRetriever:
    def retrieve(self, repo, query):
        return [f"q={query}"]


def test_crash_branch_queries_extracted_code_tokens_not_summary():
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    d = LocalizeDispatchIndex(_FakeMatch(), _EchoRetriever(), _EchoRetriever())
    d.rank_repos(Signals(classes=("com.x.Foo",), methods=("bar",), packages=("com.x",)), [RepoRef("r")])
    hits = d.retrieve(RepoRef("r"), "the wifi name is wrong")   # summary passed by run_ticket
    q = hits[0][2:]
    assert "com.x.Foo" in q and "bar" in q and "the wifi name is wrong" not in q  # code tokens, not prose


def test_functional_branch_keeps_prose_summary_query():
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    d = LocalizeDispatchIndex(_FakeMatch(), _EchoRetriever(), _EchoRetriever())
    d.rank_repos(Signals(classes=("com.x.Foo",)), [RepoRef("r")])   # no frame -> functional
    assert d.retrieve(RepoRef("r"), "wrong label") == ["q=wrong label"]   # prose summary for bge-m3
```

- [ ] **Step 2: Run to verify the new/changed tests fail** (routing tests fail on old code; query tests fail on old retrieve).

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q`
Expected: several FAIL (discriminator + query behavior not yet changed).

- [ ] **Step 3a: Refine `is_functional_localize`** in `groundloop/domains/android_ivi/functional_signals.py` — replace the body:

```python
def is_functional_localize(signals) -> bool:
    """Localize-side discriminator: True (=> semantic/bge-m3 retriever) iff the ticket is prose-marked
    OR carries NO crash-frame evidence. Crash evidence = a parsed Java stack frame (signals.methods —
    populated ONLY by the `at pkg.Class.method(` frame regex) or a native backtrace frame (a non-PROSE
    signals.symbols entry). A functional ticket's logcat can mention FQ class names (fills
    classes/packages) yet have NO stack frame → routes to semantic. MATCH-ARM-INDEPENDENT. Keys on
    stack-frame evidence, NOT anchor-emptiness: the old no-anchor test made this a no-op in production,
    where functional tickets carry logcat class mentions (RCA 2026-07-14). Residual: a lone non-crash
    `at X.Y(` handler line misroutes to FTS5 — upgrade to a fault_record marker if production shows it."""
    if signals.symbols and signals.symbols[0].startswith(PROSE_MARK):
        return True
    real_symbols = tuple(s for s in signals.symbols if not s.startswith(PROSE_MARK))
    return not (signals.methods or real_symbols)
```

- [ ] **Step 3b: Add `code_query`** in the same file (after `is_functional_localize`):

```python
def code_query(signals) -> str:
    """FTS5 localize query built from the extracted CODE tokens (classes/methods/packages/symbols/
    libraries), dropping the reserved PROSE_MARK / COMPONENT_MARK marker tokens. '' if none. The crash
    localize branch uses this instead of the prose summary (which has no code tokens to match symbols)."""
    from groundloop.domains.android_ivi.component_signals import COMPONENT_MARK
    reserved = (PROSE_MARK, COMPONENT_MARK)
    seen: dict[str, None] = {}
    for group in (signals.classes, signals.methods, signals.packages, signals.symbols, signals.libraries):
        for t in group:
            if t and not t.startswith(reserved):
                seen.setdefault(t, None)
    return " ".join(seen)
```

- [ ] **Step 3c: Use `code_query` in the crash branch** of `groundloop/adapters/index/localize_dispatch.py`. Update imports and `retrieve`:

```python
from groundloop.domains.android_ivi.functional_signals import code_query, is_functional_localize
```

```python
    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        sig = self._last_signals
        if sig is not None and is_functional_localize(sig):
            return self._functional.retrieve(repo, query)          # semantic: prose summary (bge-m3)
        fts_query = code_query(sig) if sig is not None else ""
        return self._crash.retrieve(repo, fts_query or query)      # FTS5: extracted code tokens (fallback summary)
```

- [ ] **Step 4: Run tests + full suite + ruff.**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: all green (existing + new). Note: some `tests/run/*` grade tests exercise dispatch indirectly — confirm they stay green.

- [ ] **Step 5: Commit.**

```bash
git add groundloop/domains/android_ivi/functional_signals.py groundloop/adapters/index/localize_dispatch.py tests/test_localize_dispatch.py
git commit -m "fix(localize): frame-evidence discriminator (Bug 1) + crash branch queries extracted code tokens (Bug 2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Bug 3 — grading path canonicalization

**Files:**
- Modify: `groundloop/fix/patch.py` (add `canonical_path`)
- Modify: `groundloop/run/grade_run.py` (apply `canonical_path` in localize recall — both isolated and as-run)
- Test: `tests/run/test_grade_run_canonical_path.py`

- [ ] **Step 1: Write the failing test.** Create `tests/run/test_grade_run_canonical_path.py`:

```python
from groundloop.fix.patch import canonical_path
from groundloop.eval.metrics import recall_at_k


def test_canonical_path_reconciles_source_roots():
    atlas = "app/src/main/java/com/ecarx/connectivityservice/vehicle/DefaultNameProcessor.java"
    oracle = "src/java/com/ecarx/connectivityservice/vehicle/DefaultNameProcessor.java"
    assert canonical_path(atlas) == canonical_path(oracle)
    assert canonical_path(atlas) == "com/ecarx/connectivityservice/vehicle/DefaultNameProcessor.java"


def test_canonical_path_distinct_files_do_not_collide():
    a = canonical_path("app/src/main/java/com/x/foo/Util.java")
    b = canonical_path("app/src/main/java/com/x/bar/Util.java")
    assert a != b   # full package path kept -> same basename in different packages stays distinct


def test_canonical_path_kotlin_and_plain_fallback():
    assert canonical_path("m/src/main/kotlin/com/x/A.kt") == "com/x/A.kt"
    assert canonical_path("library/src/main/jni/foo.cpp").endswith("foo.cpp")  # non-jvm: still normalized


def test_recall_matches_after_canonicalization():
    retrieved = ["app/src/main/java/com/ecarx/x/DefaultNameProcessor.java"]
    expected = ["src/java/com/ecarx/x/DefaultNameProcessor.java"]
    r = recall_at_k([canonical_path(x) for x in retrieved], {canonical_path(e) for e in expected}, 1)
    assert r == 1.0
```

- [ ] **Step 2: Run to verify it fails.**

Run: `.venv/bin/python -m pytest tests/run/test_grade_run_canonical_path.py -q`
Expected: FAIL — `ImportError: cannot import name 'canonical_path'`.

- [ ] **Step 3a: Add `canonical_path`** in `groundloop/fix/patch.py` (right after `norm_path`):

```python
def canonical_path(p: str) -> str:
    """Grading-only: reduce a repo-relative path to its package-qualified suffix so the same file
    matches across differing source roots (atlas 'app/src/main/java/…' vs oracle 'src/java/…'). Strips
    through the source-root marker; keeps the FULL package path so distinct same-basename files in
    different packages do NOT collide. NOT used in the loop — scoring only."""
    p = norm_path(p)
    for marker in ("/src/main/java/", "/src/main/kotlin/", "/src/java/", "/src/kotlin/",
                   "/java/", "/kotlin/", "/src/main/", "/src/"):
        i = p.find(marker)
        if i != -1:
            return p[i + len(marker):]
    for pref in ("src/main/java/", "src/main/kotlin/", "src/java/", "src/kotlin/",
                 "java/", "kotlin/", "src/main/", "src/"):
        if p.startswith(pref):
            return p[len(pref):]
    return p
```

- [ ] **Step 3b: Apply in grade_run localize recall.** In `groundloop/run/grade_run.py`, in BOTH `_localize_as_run` and `_localize_isolated` (and `_case_row` if it computes file recall), canonicalize retrieved AND expected before `recall_at_k`. Read those functions first; replace the existing `norm_path`-based `recall_at_k(...)` calls so both the ranked list and the gold set use `canonical_path`. Import it: `from groundloop.fix.patch import canonical_path, norm_path`. Concretely, each `recall_at_k([norm_path(x) for x in r["retrieved"]], <gold>, k)` becomes `recall_at_k([canonical_path(x) for x in r["retrieved"]], {canonical_path(e) for e in <gold_source>}, k)` where `<gold_source>` is the case's `expected` files (`r["expected"]`). Keep `_localize_as_run` and `_localize_isolated` consistent.

- [ ] **Step 4: Run new test + grade regressions + full suite + ruff.**

Run: `.venv/bin/python -m pytest tests/run/test_grade_run_canonical_path.py tests/run/test_grade_run_diag.py tests/run/test_grade_run_dispatch.py tests/run/test_grade_run_rows.py -q && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: all green. If a pre-existing grade test asserts an exact `file@k` that canonicalization legitimately changes, update the expectation and note it.

- [ ] **Step 5: Commit.**

```bash
git add groundloop/fix/patch.py groundloop/run/grade_run.py tests/run/test_grade_run_canonical_path.py
git commit -m "fix(grade): canonical_path reconciles source-root prefixes in localize scoring (Bug 3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Validation on a representative (with-logcat) proxy

Not a TDD code task — a measurement. Operator/agent runs on the dev box (ext4, `.env` sourced, `KLOOP_DEV=1`).

- [ ] **Step 1: Build a representative functional dataset** — functional cases whose tickets carry a **logcat with FQ class mentions but NO stack frame** (the production shape Bug 1 targets; the prose-only `ui_text` set could not). Use the synth `audio` class (its `_AUDIO_LOG_T` has `.so` + class text, no `at X.Y(` frame → `methods` empty → routes functional) and/or `ui_text`; **avoid `carplay`** (its log has an `at {fq}.{method}(` line → `methods` populated → routes crash). Build via `synth/functional.py:build_functional_case(..., klass="audio")` over mined positives whose owners are in `atlas-9.db`, into an ext4 dir.
- [ ] **Step 2: Confirm routing** — spot-check that `AndroidSignalExtractor().extract(logs, ticket)` on a few cases yields `methods == ()` and `is_functional_localize(...) is True` (so dispatch engages semantic). Report the fraction that route functional.
- [ ] **Step 3: A/B** — `gloop run … --match-arm flood --localize atlas` vs `--localize dispatch --fixer canned`, then `gloop grade-run --index-db atlas-9.db` on each; compare functional isolated `file@1`/`file@5` (now with canonical-path grading). Also run a crash-heavy slice to confirm the Bug 2 crash-query change helps (or at least doesn't regress) crash localize.
- [ ] **Step 4: Report** the numbers; do NOT tag `[production]` (GEI is production-only — the user re-runs that). Record `[proxy]` in `results-log.md`. If dispatch now lifts functional `file@1`, note it; the `[production]` GEI re-run is the resolver.

---

## Self-Review (author)
- Bug 1 → Task 1 Step 3a (+ tests, incl. the 2 broken existing tests fixed). Bug 2 → Task 1 Steps 3b/3c (+ tests). Bug 3 → Task 2. Validation → Task 3.
- Cross-impact flagged: the discriminator change flips `classes`-only routing, so `test_retrieve_routes_crash_to_fts5_after_rank` and `test_rank_repos_refreshes_stash_across_tickets_on_one_instance` are updated to use `methods` for the crash case.
- No `core/`/schema edits. `canonical_path` is grading-only (not in the loop's retrieve/dedup).
