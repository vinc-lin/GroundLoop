# Self-Scoring Pipeline — Design (2026-07-11)

**Status:** design approved (brainstorming), ready for an implementation plan.
**Origin:** the first end-to-end production run (`docs/2026-07-11-functional-10case-e2e-findings.md`) — two of
its three headline findings were **measurement failures, not efficacy failures**: localize was misread as
0/10 (the retrieve output was discarded, so a fabricated fix path was read as a "localization"), and Match
was hand-tallied into an 8-vs-7 count discrepancy. Fix was ungradeable (empty worktrees → fabrication).

## Goal

Make `gloop run` — the real 8-stage loop that production runs — **self-scoring**: it persists a durable,
gradeable record per case, and an offline `gloop grade-run` turns those records + the hidden oracle into a
trustworthy **per-stage scorecard** (match / localize / fix), with automatic counts and honest abstention
where a stage cannot be graded. The next production run yields a per-stage scorecard automatically instead of
hand-tallied prose.

## Non-goals

- **No new matching/localize/fix *efficacy* work.** This is pure measurability. Closing the match misses
  (CarPlay tiebreak, label≠owner override) and the localize coverage/pool-recall gaps are separate, gated
  tracks (see the findings doc). YAGNI: we do not tune any ranker here.
- **No `core/` change.** `run_ticket` / `RunRecord` (`groundloop/core/workflow.py`) and all of
  `groundloop/core/` are reused **frozen**. The `RunRecord` already carries `ranked`, `locations`, and
  `patch` — everything needed is already returned by the loop; today's `gloop run` simply prints one line and
  throws it away (`cli/__init__.py:1214`).
- **No production data on the dev box.** The GEI/10-case/406 oracles are production-only. Everything here is
  built + hermetically tested on the dev box and cross-checked on the OSS proxy; production supplies the real
  `--repos` mirror and runs the real scorecard.

## Grounding principle (unchanged)

The loop never sees the oracle; **grading is a separate offline pass.** We keep that seam exactly: the run
pass reads only loop-visible fields (via `eval.dataset.discover`, which never touches `_oracle/`); the grade
pass is the **sole** oracle reader (via `eval.dataset.load_eval_oracle`, offline-only, like `grade_fix_all`).

---

## Architecture

Five new units, all at the composition root or offline. Zero `core/` edits.

| Unit | File | Responsibility | Depends on |
|---|---|---|---|
| `RunRecordIO` | `groundloop/run/record.py` | (de)serialize the frozen `RunRecord` + a `MaterializeOutcome` sidecar ↔ `<out>/runs/<case>.json` | `core.workflow.RunRecord`, `core.types` |
| `RecordingEstate` | `groundloop/adapters/estate.py` (add) | a `RepoEstate` wrapper that delegates to a real estate and records `MaterializeOutcome` (repo, path, present, n_files) per `materialize` call | `core.ports.RepoEstate` |
| `run_dataset` | `groundloop/run/batch.py` | iterate `discover(DS)`, compose the arm-aware adapters, call frozen `run_ticket`, write one record per case | `eval.dataset.discover`, `core.workflow.run_ticket`, `RunRecordIO`, `RecordingEstate` |
| `grade_run` | `groundloop/run/grade_run.py` | offline per-stage grader over run-records + hidden oracle → `RunScorecard` | `eval.dataset.load_eval_oracle`, `eval.metrics`, `eval.scorecard`, `fixeval.scorecard`, `fixeval.patch` |
| CLI wiring | `groundloop/cli/__init__.py` | batch mode on `gloop run` (`--dataset/--out/--repos/--fixer` beside the existing `--case`); new `gloop grade-run` | the above |

### Data flow

```
# Run pass — oracle-blind, produces the durable artifact
gloop run --dataset DS --catalog C --index-db ATLAS [--match-arm component --affinity A] \
          [--repos SRC] [--fixer canned|model] --out RUNDIR
    for case in discover(DS):                       # never reads _oracle/
        rec = run_ticket(...)                       # frozen loop, all 8 stages, arm-aware
        RunRecordIO.write(RUNDIR/runs/<case>.json, rec, materialize_outcome)

# Grade pass — the ONLY oracle read, offline
gloop grade-run --runs RUNDIR --dataset DS [--index-db ATLAS] --out card.json
    for rec, oracle in [(load, load_eval_oracle(case)) ...]:
        match{recall@1/@3/@5, rank}
        localize{as_run file@k on chosen, isolated file@k on oracle-repo}
        fix{applies/resolved_strict/fabrication  |  UNGRADEABLE(no_source)}
    → aggregate + by_bug_kind + automatic counts → card.json + markdown per-case table
```

`ranked`, `locations`, `patch` are all in the persisted record → **match, as-run-localize, and fix grade
offline with no re-execution.** The single re-execution is the *isolated* localize diagnostic (retrieve on
the oracle repo); hence `grade-run` optionally takes `--index-db`.

---

## Component specifications

### 1. The run-record (`groundloop/run/record.py`)

Serialized JSON at `<out>/runs/<case>.json`:

```json
{
  "ticket_id": "GEI-13196",
  "match_arm": "component",
  "ranked": [{"repo": "engineering", "score": 0.42, "evidence": ["..."]}],
  "chosen": "engineering",
  "locations": ["ScreenshotUtils.kt", "..."],
  "patch": {"diff": "...", "files": ["system/core/init/init.cpp"]},
  "change_id": "gl-abc123",
  "bound": true,
  "events": ["intake","extract","match","materialize","localize","fix","submit","bind"],
  "materialize": {"repo": "engineering", "path": "/.../engineering", "present": false, "n_files": 0}
}
```

- `RunRecordIO.write(path, rec: RunRecord, materialize: MaterializeOutcome)` and
  `RunRecordIO.read(path) -> RunRecordDoc`. Pure (de)serialization of the frozen `RunRecord` fields plus the
  `materialize` sidecar and `match_arm` (recorded by the CLI, which knows the arm).
- **No oracle fields.** The record is loop-only and safe to keep beside the run.
- `MaterializeOutcome` is a small local dataclass in `record.py` (`repo: str, path: str, present: bool,
  n_files: int`).

### 2. `RecordingEstate` (`groundloop/adapters/estate.py`, added)

A `RepoEstate` decorator: `__init__(self, inner: RepoEstate)`; `catalog()` delegates; `materialize(repo)`
delegates to `inner.materialize(repo)`, then records a `MaterializeOutcome` (path exists? count files, capped
so a huge checkout doesn't stat-walk forever — e.g. "≥1" is enough; `present = n_files > 0`). Exposes
`last_outcome()` / an outcome map so `run_dataset` can attach the outcome for `chosen` to the record. Pure
adapter; implements the existing port; no `core/` edit.

### 3. `run_dataset` (`groundloop/run/batch.py`)

`run_dataset(dataset, catalog, *, index, extractor, fixer, changes_path, work, repos=None, match_arm,
out) -> int`:
- `cases = discover(dataset)` (never reads `_oracle/`).
- Compose the estate: `RecordingEstate(GitFixtureEstate(catalog, repos))` when `repos` is set, else
  `RecordingEstate(MockEstate(catalog, work))`.
- For each case: `rec = run_ticket(case.id, issues=MockJira(dataset), extractor=extractor, estate=estate,
  index=index, fixer=fixer, changes=MockGerrit(changes_path, issues))`; write
  `RUNDIR/runs/<case>.json` with `rec` + the recorded outcome for `rec.chosen`.
- Deterministic, sequential (like fixeval). Prints a per-case progress line + a final `runs written: N`.

### 4. Checkout + fixer knobs (composition root, `cli/__init__.py`)

- `--repos <SRC>`: dir of owner-repo snapshots at pinned SHAs (proxy: `corpora-local`; production: the 19-repo
  mirror). Reuses `GitFixtureEstate` (`estate.py:25`), which git-inits plain-dir snapshots. `materialize`
  returns a real worktree for `ModelPatchEngine` to read.
- `--fixer {canned,model}`: `canned` = `CannedFixEngine(CannedModel(...))` (today's hermetic default);
  `model` = the real `ModelPatchEngine` (what the 10-case run used). Composition-root swap; mirrors fixeval.
- **Honest-abstain:** missing `<SRC>/<chosen>` → empty worktree → `MaterializeOutcome.present=false` → grader
  marks that case's fix `UNGRADEABLE(no_source)`. Partial coverage grades the covered owners, abstains on the
  rest.

### 5. `grade_run` + `RunScorecard` (`groundloop/run/grade_run.py`)

`grade_run(runs_dir, dataset, *, index_db=None) -> dict` (the scorecard). Per case, read the record + a single
`load_eval_oracle(case)`:

- **Match** — `ranked` names vs `oracle.owning_repo`: compute `recall@1/@3/@5` directly via
  `eval.metrics.recall_at_k(ranked_names, {owning_repo}, k)` and `repo_rank` = index of `owning_repo` in
  `ranked_names` (0 if absent), matching the existing thin `grade()`. (`eval.scorecard.score_match` expects a
  `MatchRecord`; we reuse its `by_bug_kind` aggregate *shape*, not its per-record entry point.)
- **Localize as-run** — `file@k` of persisted `locations` (retrieve ran on `chosen`) vs
  `oracle.expected_files`. Reuse `fixeval.scorecard._file_recall` / `eval.metrics.recall_at_k`. Honest
  end-to-end number (≈0 when match missed).
- **Localize isolated** (diagnostic, only if `index_db` given) — grader calls
  `AtlasIndex(index_db).retrieve(RepoRef(oracle.owning_repo), query)` → `file@k` on the *oracle* repo = the
  match-independent ceiling (the "7/10 not 0/10" correction). Emits `null` + a note if `index_db` is omitted.
  Grade-only: computed in the offline pass, feeds the scorecard, never the loop.
- **Fix** — abstain gate first: if `materialize.present == False` **or** no `patch.files` path exists under
  the owner checkout → `UNGRADEABLE(no_source)` (do not score; do not read the patched path as a
  localization). Else grade via `fixeval`: adapt the run-record into the record shape `fixeval.scorecard`
  expects (`touched_files = patch.files`; `patch_applies = fixeval.patch.patch_applies(patch.diff,
  worktree_path)`), then reuse `_file_recall` / `resolved_rate_strict` / `fabrication_rate` (or `grade_fix_all`
  over the adapted list). The worktree path comes from the record's `materialize.path`.
- **Aggregate** — per-stage aggregates + a `by_bug_kind` split (reuse the eval/fixeval `by_bug_kind`
  grouping). The fix block reports `n_gradeable` / `n_ungradeable(no_source)` explicitly, so "fix 0/10" can
  never again silently be a worktree artifact.
- **Render** — `card.json` + a generated per-case markdown table in the shape of the findings doc
  (`Case | component | owner | match(rank) | localize as-run/isolated | fix status`). The findings doc becomes
  a build artifact, not hand-tallied prose. Reuse the `eval.report` / `fixeval.report` renderer shapes.

---

## Reuse map (verbatim, not reimplemented)

- `core.workflow.run_ticket` / `RunRecord` — frozen; the record already carries the gradeable fields.
- `eval.dataset.discover` (loop, never `_oracle/`) + `load_eval_oracle` (grader, offline-only) — the leak seam.
- `eval.metrics.recall_at_k`; `eval.scorecard.score_match` + `by_bug_kind` grouping; `eval.report` shape.
- `fixeval.scorecard.grade_fix_all` / `_file_recall`; `fixeval.patch.patch_applies`; `fixeval.report` shape.
- `adapters/estate.GitFixtureEstate` + `MockEstate`; the arm builders already in the `gloop run` handler
  (`AtlasIndex` / `FaultRoutingIndex` / `ComponentPriorIndex`, `AndroidSignalExtractor` / `ComponentExtractor`).

---

## Anti-leak invariants (red-tested, mirroring `tests/test_invariants.py`)

1. **Loop oracle-blind** — `run_dataset` iterates `discover()`; `run_ticket` is frozen and takes no oracle. A
   red-test asserts no `_oracle/` path is read during the run pass.
2. **Record carries no oracle** — schema red-test: `owning_repo` / `expected_files` / `required_apis` never
   appear in any `runs/*.json`.
3. **Grader is the sole oracle reader** — `grade_run` is the only new caller of `load_eval_oracle`; offline,
   post-hoc. Same seam as `grade_all` / `grade_fix_all`.
4. **Isolated-localize is grade-only** — the oracle-repo retrieve lives inside `grade_run`, feeds the
   scorecard, never the loop.

## Testing

**Hermetic (Type-1, runs every change; `tests/conftest.py` fixtures):**
- `RunRecordIO` round-trip (`read(write(rec)) == rec`) + the no-oracle schema red-test.
- `run_dataset` over the fixture dataset + prebuilt atlas fixture → N records; the oracle-blind red-test (#1).
- `grade_run` on hand-built records + a fixture oracle: match `recall@k` correct; localize as-run `file@k`;
  **isolated `file@k` ≠ as-run when the fixture `chosen ≠ oracle`** (proves the diagnostic isolates match
  contamination — the core correction); fix `UNGRADEABLE(no_source)` when `present=false`, graded
  (applies/resolved/fabrication) when a fixture worktree is checked out.
- **Regression lock** (the exact 10-case bug): a `present=false` record with a fabricated patch path → fix
  `UNGRADEABLE`, the fabricated file *not* counted as localization.
- CLI smokes: `gloop run --dataset … --out …` writes records; `gloop grade-run --runs … --out …` writes a
  scorecard with the per-case table.
- **Auto-count assertion:** the scorecard's match tally == Σ per-case match hits (no manual count path exists).

**Proxy (Type-2, gated cross-check; off ext4, live bge-m3):**
- `gloop run --dataset functional-clean --index-db atlas-9.db --repos corpora-local --out run-proxy` →
  `gloop grade-run --runs run-proxy --dataset functional-clean --index-db atlas-9.db --out card.json`.
- Confirm the self-scored match numbers **agree with the funceval harness** (self-scoring == direct-driven
  eval), and that fix grades on the checked-out proxy owners. Proxy is a mechanism check; production is the
  efficacy scoreboard.

## Ships vs. production runbook

- **Ships (dev box):** all five units, the `--repos`/`--fixer` knobs, the full scorecard + generated table,
  the anti-leak red-tests, the proxy cross-check.
- **Production runbook** (add to `docs/production-migration.md`): point `gloop run --repos` at the real
  19-repo mirror at pinned SHAs → re-run the 10-case (and the 406) → `gloop grade-run` → the auto-generated
  per-stage scorecard replaces hand-tallying. `--fixer model` for the real fix stage.

## Frozen / gated surfaces — zero-diff guarantee

No edits to: `groundloop/core/` (incl. `workflow.py`/`run_ticket`/`RunRecord`), `engines/atlas/store.py`
schema, `adapters/index/atlas.py::rank_repos`, `domains/android_ivi/owner_tokens.py`,
`domains/android_ivi/repo_routing.py`, `mine/`. `grade/grader.py`'s existing `grade()` stays; the new
`grade_run` is additive (it may call the eval/fixeval scorecards directly rather than the thin `grade()`).

## Success criteria (acceptance)

1. `gloop run --dataset … --out RUNDIR` writes one oracle-free `runs/<case>.json` per case, carrying the
   persisted `locations` and `patch` — the localize output is never discarded again.
2. `gloop grade-run --runs RUNDIR --dataset … [--index-db …]` emits a per-stage scorecard: match
   `recall@1/@3/@5`, localize **as-run + isolated** `file@k`, fix `applies/resolved_strict/fabrication` with
   an explicit `n_ungradeable(no_source)`, plus a `by_bug_kind` split and a generated per-case table.
3. The two 10-case measurement failures are **structurally impossible**: counts are automatic (no 8-vs-7), and
   a fabricated patch on an empty worktree is `UNGRADEABLE`, never a "localization" (regression-locked).
4. On the proxy, self-scored match numbers agree with the funceval harness.
5. Full hermetic suite green + ruff clean; frozen/gated surfaces zero-diff.
