# `--localize atlas_rerank` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--localize atlas_rerank` arm — the FTS5 `AtlasIndex.retrieve` recall pool reordered by the LLM
file-judge (composed via the existing `pool_index` seam on `RerankLocalizeIndex`, **no embedder**) — and make it
the **Provisional-Core production default**, with a fail-safe degrade to today's `atlas` behavior.

**Architecture:** Pure composition at the root (`cli/__init__.py`) + one default flip; no new module, no `core/`
or atlas-schema edit. `RerankLocalizeIndex` already supports a `pool_index` (used by `cascade_judge`) and a
`judge=None` fail-safe (returns the pool order) — this arm reuses both with a plain `AtlasIndex` as the pool.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check
groundloop tests` (line 110). Spec: `docs/superpowers/specs/2026-07-19-atlas-rerank-localize-design.md`.

**Hard constraints:** never edit `groundloop/core/`; never alter the atlas SQLite schema; `rerank`/`cascade_judge`
behavior unchanged; suite green + ruff clean per commit; the import-boundary contract stays green (labs arms load
via function-local imports only).

---

### Task 1: Wire the `atlas_rerank` arm (reachable, opt-in)

**Files:**
- Modify: `groundloop/cli/__init__.py` (the `--localize` argparse choices + the localize-dispatch branch in the
  `run` handler)
- Read first (verify, likely no change): `groundloop/adapters/index/labs/rerank_localize.py`
  (`_pool_index_hits`, `retrieve`, the `judge=None` fail-safe)
- Test: `tests/test_atlas_rerank_localize.py` (new)

- [ ] **Step 1: Verify the `pool_index` contract accepts a plain `AtlasIndex`.**

Read `groundloop/adapters/index/labs/rerank_localize.py` — confirm `_pool_index_hits(repo, query, query_str)`
calls `self._pool_index.retrieve(repo, query)` and consumes a `list[str]` of bare file paths (the same contract
`cascade_judge` relies on), and that when `self._pool_index is not None` the `_gen_hits`/`embedder` path is never
reached. Confirm `AtlasIndex.retrieve(repo, query) -> list[str]` matches. **If the contract already fits (expected),
no change to `rerank_localize.py`.** If `_pool_index_hits` assumes cascade-specific behavior, note it — but do not
change `rerank_localize.py` unless a test proves it necessary.

- [ ] **Step 2: Read the existing `cascade_judge` and `rerank` dispatch branches** in `groundloop/cli/__init__.py`
(the localize-dispatch section, ~L1429-1475, and `_build_rerank_localize` ~L1223). Note exactly how
`cascade_judge` builds its `pool_index` and calls `_build_rerank_localize(..., pool_index=...)`, and how the arm
is wrapped in `SplitIndex`. `atlas_rerank` mirrors this with `AtlasIndex(index_db)` as the pool and `embedder=None`.

- [ ] **Step 3: Write the failing hermetic test** at `tests/test_atlas_rerank_localize.py`.

Use the existing atlas fixture (`atlas_harness` / prebuilt fixture atlas.db in `tests/conftest.py` — match how
`tests/` builds a `RerankLocalizeIndex`/pool test elsewhere; reuse the `StubFileJudge` from
`groundloop.adapters.index.labs.rerank_localize`). Two hermetic assertions in this task:

```python
def test_atlas_rerank_pool_is_fts5_and_judge_reorders(atlas_harness):
    """atlas_rerank's candidate pool == the plain FTS5 AtlasIndex.retrieve set; the StubFileJudge only reorders it."""
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex, StubFileJudge
    from groundloop.core.types import RepoRef

    db = atlas_harness.db_path            # adapt to the fixture's actual attribute
    repo = RepoRef(atlas_harness.repo_name)
    query = atlas_harness.localize_query  # a query that returns >1 FTS5 hit; adapt to the fixture

    atlas = AtlasIndex(db)
    pool = atlas.retrieve(repo, query)
    assert len(pool) >= 2, "fixture must yield a multi-file FTS5 pool for a meaningful reorder"

    reversed_order = list(reversed(pool))
    idx = RerankLocalizeIndex(atlas, store=atlas_harness.store, embedder=None,
                              judge=StubFileJudge(order=reversed_order), pool_index=atlas)
    got = idx.retrieve(repo, query)
    assert set(got) == set(pool), "judge must only REORDER real FTS5 pool files (grounded, no fabrication)"
    assert got == reversed_order, "the StubFileJudge's order must drive the result"


def test_atlas_rerank_without_judge_equals_atlas(atlas_harness):
    """Fail-safe floor: judge=None -> atlas_rerank output is identical to plain --localize atlas retrieve."""
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex
    from groundloop.core.types import RepoRef

    db = atlas_harness.db_path
    repo = RepoRef(atlas_harness.repo_name)
    query = atlas_harness.localize_query

    atlas = AtlasIndex(db)
    expected = atlas.retrieve(repo, query)
    idx = RerankLocalizeIndex(atlas, store=atlas_harness.store, embedder=None, judge=None, pool_index=atlas)
    assert idx.retrieve(repo, query) == expected, "no-judge atlas_rerank must equal plain atlas retrieve"
```

**NOTE for the implementer:** the fixture attribute names above (`atlas_harness.db_path`, `.store`, `.repo_name`,
`.localize_query`) are illustrative — read `tests/conftest.py` and an existing rerank/pool test (e.g. any test
touching `RerankLocalizeIndex` or `cascade`) and use the REAL fixture surface. The two behaviors under test are
fixed: (a) pool == FTS5 set and judge reorders a grounded subset; (b) `judge=None` == plain `atlas`.

- [ ] **Step 4: Run the test, verify it fails** (the arm isn't wired / import path as expected).

Run: `.venv/bin/python -m pytest tests/test_atlas_rerank_localize.py -q`
Expected: FAIL (or the RerankLocalizeIndex construction reveals the real signature to adapt to — fix the test to
the real signature first, then it should fail only on the missing `atlas_rerank` wiring if any, or PASS at the
class level and drive Step 5 for the CLI wiring).

- [ ] **Step 5: Add the `atlas_rerank` CLI wiring** in `groundloop/cli/__init__.py`:
  1. Add `"atlas_rerank"` to the `--localize` `choices=[...]` list.
  2. In the localize-dispatch branch, add an `atlas_rerank` case that mirrors `cascade_judge` but with a plain
     FTS5 pool and no embedder — build `AtlasIndex(index_db)` as `pool_index`, call
     `_build_rerank_localize(match_index, args, None, pool_index=<AtlasIndex>)`, wrap in `SplitIndex` exactly like
     the sibling arms. Do NOT add an embedder fail-fast for this branch (the pool needs none).
  Keep the labs imports function-local (the sanctioned seam), matching the neighbouring arms.

- [ ] **Step 6: Run the test, verify it passes.**

Run: `.venv/bin/python -m pytest tests/test_atlas_rerank_localize.py -q`
Expected: PASS.

- [ ] **Step 7: Full suite + ruff + boundary check.**

Run: `.venv/bin/python -m pytest -q` (expect all green) · `.venv/bin/ruff check groundloop tests` (clean) ·
`.venv/bin/python -m pytest tests/architecture/test_import_boundary.py -q` (green — no eager labs import added).
Confirm `git diff --stat -- groundloop/core groundloop/engines/atlas/store.py` is empty.

- [ ] **Step 8: Commit.**

```bash
git add groundloop/cli/__init__.py tests/test_atlas_rerank_localize.py
git commit -m "feat(localize): add --localize atlas_rerank (FTS5 pool + LLM judge, no embedder)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Make `atlas_rerank` the Provisional-Core production default

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_resolve_arms` localize default)
- Modify: `tests/run/test_core_defaults_unchanged.py` (and any other test asserting the localize default)
- Test: same file(s)

- [ ] **Step 1: Grep for every place the localize default is asserted or assumed.**

Run: `grep -rn "localize" tests/run/test_core_defaults_unchanged.py` and
`grep -rn "\"atlas\"\|'atlas'" tests/ groundloop/cli/__init__.py | grep -i localize`
List the files that hard-code `atlas` as the localize default. Expected primary: `test_core_defaults_unchanged.py`.

- [ ] **Step 2: Update the failing test first** — change the expected localize default from `atlas` to
`atlas_rerank` in `tests/run/test_core_defaults_unchanged.py` (both profiles if the test checks both). Run it to
confirm it now FAILS against the un-flipped code:

Run: `.venv/bin/python -m pytest tests/run/test_core_defaults_unchanged.py -q`
Expected: FAIL (code still resolves `atlas`).

- [ ] **Step 3: Flip the default** in `groundloop/cli/__init__.py` `_resolve_arms` — the localize default
`"atlas"` → `"atlas_rerank"` (both profiles, per the spec: production default). Leave `--localize atlas` as the
explicit opt-out. Do not touch the match (`component`) or fixer (`plan`) defaults.

- [ ] **Step 4: Run the test, verify it passes.**

Run: `.venv/bin/python -m pytest tests/run/test_core_defaults_unchanged.py -q`
Expected: PASS.

- [ ] **Step 5: Add a default-behaviour guard** — a small test asserting that a default `gloop run` localize
selection resolves to `atlas_rerank` AND that this default does NOT introduce a fail-close without an embedder
(the whole point vs `rerank`). If an existing test exercises `_resolve_arms`/the run wiring, extend it; otherwise
add a focused unit test near `test_core_defaults_unchanged.py`:

```python
def test_default_localize_is_atlas_rerank_and_needs_no_embedder():
    from groundloop.cli import _resolve_arms   # adapt import to the real symbol
    match_arm, localize = _resolve_arms(match_arm=None, localize=None, labs=False)  # adapt signature
    assert localize == "atlas_rerank"
    # atlas_rerank must not be gated on an embedder (unlike rerank); assert no embedder branch fires for it.
```

Adapt the import/signature to the real `_resolve_arms`. Run it green.

- [ ] **Step 6: Full suite + ruff.**

Run: `.venv/bin/python -m pytest -q` (all green — watch for any OTHER test that assumed `atlas` default and fix
it to expect `atlas_rerank`) · `.venv/bin/ruff check groundloop tests`. Confirm core/schema zero-diff.

- [ ] **Step 7: Commit.**

```bash
git add groundloop/cli/__init__.py tests/run/test_core_defaults_unchanged.py tests/  # + any other updated test
git commit -m "feat(localize): make atlas_rerank the Provisional-Core production default (was atlas)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Docs — governance, defaults, the resolver, the module map

**Files:**
- Modify: `docs/capabilities.md`, `CLAUDE.md`, `docs/module-map.md`, `docs/STATUS.md`

- [ ] **Step 1: `docs/capabilities.md`** — add `--localize atlas_rerank` as a **Provisional-Core** capability
(the existing tier). Record: it's the production default; the fail-safe floor (no judge creds ⇒ degrades to
`atlas`, byte-equivalent); the new failure mode (judge may misrank vs the FTS5 floor); the **resolver** = the
`[proxy]` isolated `file@1` A/B (`atlas` vs `atlas_rerank` vs `cascade_judge`) → Core-or-revert; and the cost
note (~$0.0014/case with creds). Reconcile the localize-default row (was `atlas`).

- [ ] **Step 2: `CLAUDE.md`** — in the `gloop run` defaults bullet, change the localize default from `atlas`
→ `atlas_rerank` (Provisional-Core), noting it degrades to `atlas` without judge creds and `--localize atlas` is
the opt-out. Add `atlas_rerank` to the `--localize {...}` reachable list if that list is enumerated there.

- [ ] **Step 3: `docs/module-map.md`** — in §2 ⑤ localize, add `atlas_rerank` to the opt-in rerankers list AND
mark it the **default** (moving the "default" note from `atlas`): "`--localize atlas_rerank` (default,
Provisional-Core) — FTS5 pool + LLM judge, no embedder, degrades to `atlas` without creds". Keep `atlas` listed
as the fail-safe floor / opt-out. Update the §2 ⑤ maturity line to reflect the new default.

- [ ] **Step 4: `docs/STATUS.md`** — add a dated `### ✅` entry under `## Done`: the `atlas_rerank` arm +
Provisional-Core default flip, the fail-safe argument, and the **open resolver** (the `[proxy]` file@1 A/B is the
next step, gated). Refresh the header date to 2026-07-19 if not already, and update the `## Next steps` to name
the `atlas_rerank` `[proxy]` A/B as the resolver.

- [ ] **Step 5: Verify docs render + no stale claims.**

Run: `grep -rn "localize.*atlas\b" CLAUDE.md docs/capabilities.md docs/module-map.md | grep -i default` —
confirm the current-state default references now say `atlas_rerank` (leave historical/dated mentions alone).
Full suite still green (docs-only, but confirm nothing imports these): `.venv/bin/python -m pytest -q`.

- [ ] **Step 6: Commit.**

```bash
git add docs/capabilities.md CLAUDE.md docs/module-map.md docs/STATUS.md
git commit -m "docs(localize): record atlas_rerank Provisional-Core default + the [proxy] A/B resolver

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:** §3 mechanism → Task 1; §4 fail-safe → Task 1 Step 3 (the `judge=None==atlas` test); §5
  default/governance → Task 2 + Task 3 Step 1-2; §6 resolver → Task 3 (documented, no code, per spec — not a
  merge gate); §7 testing → Task 1 Step 3 + Task 2 Step 5; §8 invariants → enforced by the boundary check +
  core/schema zero-diff checks in each task; §9 touch-map → matches Tasks 1-3.
- **No new eval tooling** (spec §8 YAGNI) — the resolver reuses the existing harness; the plan only documents it.
- **Type consistency:** the arm is `atlas_rerank` throughout; the pool is a plain `AtlasIndex`; the fail-safe is
  `judge=None → pool order`; the default flips in `_resolve_arms`. Fixture attribute names in Task 1 Step 3 are
  explicitly flagged as illustrative-adapt-to-real.
- **Merge gate = hermetic suite green + ruff + boundary + core/schema zero-diff.** The `[proxy]`/`[production]`
  reads are gated follow-ups, not merge gates (they can't run hermetically).
