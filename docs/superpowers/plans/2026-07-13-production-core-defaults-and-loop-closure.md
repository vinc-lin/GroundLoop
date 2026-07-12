# Production-Core defaults + loop closure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote Bug Plan Mode (`PlanningFixEngine`) to the default `gloop run` fixer under a new
Provisional-Core tier; close the feedback loop's dev-box edges (instrument the run-record + a regression
comparator); and shrink the Production run surface (dev-gate the silent-degrade fixtures, harden `--repos`).

**Architecture:** All changes at the composition root (`groundloop/cli/__init__.py`) and in
`groundloop/{run,adapters,fix}/` + docs. **NEVER edit `groundloop/core/`; NEVER alter the SQLite schema.**
Sidecar-decorator pattern (mirroring `RecordingEstate`) captures data the frozen `core.RunRecord` drops.
Spec: `docs/superpowers/specs/2026-07-13-production-core-defaults-and-loop-closure-design.md`.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests: `.venv/bin/python -m pytest -q`. Lint:
`.venv/bin/ruff check groundloop tests` (line 110). All work on branch
`prod-core-defaults-loop-closure`. Commit trailer:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Commit only when suite green + ruff
clean.

---

## Phase 1 — Workstream 1: Bug Plan Mode → Provisional-Core default

### Task 1: Relocate the plan/patch primitives out of `fixeval/` into a Core-neutral `groundloop/fix/`

**Why:** `adapters/fix/planning.py` (Production-Core once it's the run default) imports `RepairPlan`,
`check_plan_in_world`, `parse_plan`, `plan_groundedness` from `groundloop.fixeval.plan` and
`extract_unified_diff`, `touched_files` from `groundloop.fixeval.patch` — i.e. Core importing Dev-Labs-Infra
(`fixeval/`), which violates the `capabilities.md` separation. Move the pure primitives to a neutral home;
leave shims so the eval stack is untouched.

**Files:**
- Create: `groundloop/fix/__init__.py` (empty), `groundloop/fix/plan.py`, `groundloop/fix/patch.py`
- Modify: `groundloop/fixeval/plan.py` → shim, `groundloop/fixeval/patch.py` → shim,
  `groundloop/adapters/fix/planning.py:10-11` (imports)
- Test: `tests/fix/test_plan_relocation.py` (new)

- [ ] **Step 1: Write the failing test** — `tests/fix/__init__.py` (empty) + `tests/fix/test_plan_relocation.py`:

```python
def test_plan_primitives_import_from_fix_package():
    # the new Core-neutral home exists and exports the primitives
    from groundloop.fix.plan import RepairPlan, PlanTarget, parse_plan, check_plan_in_world, plan_groundedness
    from groundloop.fix.patch import extract_unified_diff, touched_files, norm_path
    p = parse_plan('{"root_cause":"x","targets":[{"file":"a.py","symbol":"f","why":"y"}],'
                   '"required_apis":[],"strategy":"s","citations":["a.py"],"risks":[],'
                   '"confidence":0.9,"abstain":false}')
    assert p is not None and p.targets[0].file == "a.py"

def test_planning_engine_does_not_import_fixeval():
    # Production-Core adapter must not depend on the Dev-Labs fixeval package
    import inspect, groundloop.adapters.fix.planning as m
    assert "groundloop.fixeval" not in inspect.getsource(m)

def test_fixeval_shim_still_exports():
    # backward-compat shim keeps the eval stack + its tests working
    from groundloop.fixeval.plan import RepairPlan, check_plan_in_world, plan_to_dict  # noqa
    from groundloop.fixeval.patch import norm_path, patch_applies  # noqa
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m pytest tests/fix/test_plan_relocation.py -q`
  Expected: FAIL (`ModuleNotFoundError: groundloop.fix`).

- [ ] **Step 3: Implement** —
  1. `git mv groundloop/fixeval/plan.py groundloop/fix/plan.py` and
     `git mv groundloop/fixeval/patch.py groundloop/fix/patch.py`; add empty `groundloop/fix/__init__.py`.
  2. In `groundloop/fix/plan.py`, change `from groundloop.fixeval.patch import norm_path` →
     `from groundloop.fix.patch import norm_path`. Verify `groundloop/fix/patch.py` imports only stdlib
     (it holds `norm_path`, `extract_unified_diff`, `touched_files`, `patch_applies`) — if it imports any
     `groundloop.fixeval.*`, relocate that dependency too or it is a red flag to surface.
  3. Recreate `groundloop/fixeval/plan.py` as a shim:
     ```python
     """Back-compat shim — the plan primitives moved to groundloop.fix.plan (Core-neutral). Kept so the
     Dev-Labs fixeval stack + its tests import unchanged. See the 2026-07-13 loop-closure plan."""
     from groundloop.fix.plan import *  # noqa: F401,F403
     from groundloop.fix.plan import (PlanTarget, RepairPlan, PlanCheck, parse_plan, plan_to_dict,  # noqa: F401
                                      check_plan_in_world, plan_groundedness)
     ```
     and `groundloop/fixeval/patch.py` as the analogous shim re-exporting from `groundloop.fix.patch`
     (`norm_path`, `extract_unified_diff`, `touched_files`, `patch_applies`, and any other public names —
     grep `from groundloop.fixeval.patch import` across the repo first and re-export every imported name).
  4. In `groundloop/adapters/fix/planning.py:10-11`, repoint the two imports to
     `from groundloop.fix.patch import extract_unified_diff, touched_files` and
     `from groundloop.fix.plan import (RepairPlan, check_plan_in_world, parse_plan, plan_groundedness)`.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/fix/ tests/fixeval/ -q` → PASS.
  Then the full suite `.venv/bin/python -m pytest -q` → green (nothing else regressed by the move).

- [ ] **Step 5: Commit** —
```bash
git add groundloop/fix groundloop/fixeval/plan.py groundloop/fixeval/patch.py groundloop/adapters/fix/planning.py tests/fix
git commit -m "refactor(fix): relocate plan/patch primitives to groundloop.fix (decouple Core from fixeval)"
```

---

### Task 2: End-to-end anti-leak — re-gate the *executed diff* in `PlanningFixEngine`

**Why:** the in-world gate validates the PLAN, not the emitted diff (`planning.py:62-71` returns
`touched_files(diff)` unchecked). As a Production default it must not emit a diff touching files outside the
localize candidate set. Re-check the executed diff's touched files ⊆ candidates; any out-of-scope file →
abstain (empty `Patch`), consistent with plan-level behavior + `tests/test_invariants.py`.

**Files:**
- Modify: `groundloop/adapters/fix/planning.py:30-45,62-71`
- Test: `tests/fix/test_planning_diff_regate.py` (new) + one assertion in `tests/test_invariants.py`

- [ ] **Step 1: Write the failing test** — `tests/fix/test_planning_diff_regate.py`. Use a scripted model
  (a tiny stub with `.complete()` returning first a valid grounded plan citing an in-scope file, then a
  unified diff that edits an OUT-OF-SCOPE file). Assert `propose(...)` returns an **empty** `Patch`
  (`patch.diff == ""`), i.e. it abstained rather than emit an out-of-scope diff. A second test: model returns
  a diff touching only in-scope files → non-empty `Patch`.

```python
class _ScriptedModel:
    def __init__(self, replies): self._r = list(replies); self.i = 0
    def complete(self, prompt):
        r = self._r[self.i]; self.i = min(self.i + 1, len(self._r) - 1); return r
```
  Build a worktree dir with `in_scope.py` present; `locations=["in_scope.py"]`; plan cites `in_scope.py`;
  execute-reply is a diff with `+++ b/secrets/other.py`. Expect abstain.

- [ ] **Step 2: Run to verify it fails** —
  `.venv/bin/python -m pytest tests/fix/test_planning_diff_regate.py -q` → FAIL (patch is non-empty; the
  out-of-scope diff is returned).

- [ ] **Step 3: Implement** — in `propose_with_plan` (after `_execute`), re-gate: compute the executed
  patch's `touched_files`, normalize (reuse `norm_path` from `groundloop.fix.patch`), and require every one
  to be in the candidate set (`{norm_path(l) for l in locs}`). If any is out of scope, return
  `plan, Patch(diff="", files=()), {**meta, "abstain_reason": "diff_out_of_scope"}` instead of the executed
  patch. Keep the existing plan-gate path unchanged.

```python
        patch = self._execute(worktree, ticket, plan)
        cand = {norm_path(l) for l in locs}
        if any(norm_path(f) not in cand for f in patch.files):   # anti-leak: executed diff must stay in scope
            return plan, Patch(diff="", files=()), {**meta, "abstain_reason": "diff_out_of_scope"}
        return plan, patch, meta
```
  (add `from groundloop.fix.patch import norm_path` to the imports).

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/fix/ tests/test_invariants.py -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/adapters/fix/planning.py tests/fix/test_planning_diff_regate.py tests/test_invariants.py
git commit -m "feat(fix): re-gate PlanningFixEngine executed diff against candidate scope (end-to-end anti-leak)"
```

---

### Task 3: Wire `plan` into `gloop run` and make it the default fixer

**Why:** `PlanningFixEngine` is reachable only from `fixeval` today; the production run command can't select
it. Make `plan` a `run --fixer` choice + the default, extend the fail-closed guard, thread `--max-replan`,
and have `_build_run_fixer` return the model handle (Task 5 needs it for cost).

**Files:** Modify `groundloop/cli/__init__.py` (`:994` argparse, `:1211-1224` `_build_run_fixer`, `:1290`
guard, `:1304` call site, add `--max-replan`). Test: `tests/run/test_run_fixer_plan.py` (new).

- [ ] **Step 1: Write the failing test** — `tests/run/test_run_fixer_plan.py`:
```python
def test_build_run_fixer_plan_returns_planning_engine(monkeypatch):
    monkeypatch.setenv("KLOOP_PRODUCE_API_KEY", "x")
    from groundloop.cli import _build_run_fixer
    from groundloop.adapters.fix.planning import PlanningFixEngine
    fixer, model = _build_run_fixer("plan", max_replan=2)
    assert isinstance(fixer, PlanningFixEngine) and fixer.max_replan == 2
    assert model is not None                          # the GatewayModel handle for cost capture (Task 5)

def test_build_run_fixer_canned_returns_none_model():
    from groundloop.cli import _build_run_fixer
    fixer, model = _build_run_fixer("canned")
    assert model is None                              # canned has no cost meter

def test_run_fixer_default_is_plan():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(["run", "--dataset", "d", "--catalog", "c", "--work", "w",
                                    "--changes", "ch", "--index-db", "a.db", "--out", "o", "--repos", "r"])
    assert ns.fixer == "plan"
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m pytest tests/run/test_run_fixer_plan.py -q`
  → FAIL (`_build_run_fixer` returns a single value / no `plan` branch; default is `model`).

- [ ] **Step 3: Implement** —
  1. `:994` — `r.add_argument("--fixer", choices=["canned", "model", "plan"], default="plan", help="batch fix
     engine: plan (grounded plan→gate→abstain PlanningFixEngine — the production default; abstains rather
     than fabricate) | model (single-shot ModelPatchEngine opt-out) | canned (dev-only hermetic stub)")`.
  2. After the `--fixer` line add `r.add_argument("--max-replan", type=int, default=1, help="plan fixer: max
     re-plan attempts before abstaining (default 1)")`.
  3. `_build_run_fixer` — change signature to `_build_run_fixer(kind: str, max_replan: int = 1)` and return a
     `(fixer, cost_model)` tuple:
     ```python
     def _build_run_fixer(kind: str, max_replan: int = 1):
         """Returns (FixEngine, cost_model|None). cost_model is the GatewayModel whose .cost_usd the batch
         driver snapshots per case (Task 5); None for the canned stub. `main` fail-closes on a missing key
         BEFORE this for kind in {model, plan}, so no silent degrade-to-stub here."""
         from groundloop.adapters.fix.canned import CannedFixEngine
         from groundloop.adapters.mock.model import CannedModel
         if kind in ("model", "plan"):
             from groundloop.adapters.model.gateway import GatewayModel
             from groundloop.config.settings import Settings
             s = Settings.load()
             gm = GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
             if kind == "plan":
                 from groundloop.adapters.fix.planning import PlanningFixEngine
                 return PlanningFixEngine(gm, max_replan=max_replan), gm
             from groundloop.adapters.fix.model_patch import ModelPatchEngine
             return ModelPatchEngine(gm), gm
         return CannedFixEngine(CannedModel({"default": "patch"})), None
     ```
  4. `:1290` guard — `if args.fixer in ("model", "plan"):` (so the key + `--repos` checks fire for plan too);
     update the two error strings to name `--fixer model/plan`.
  5. `:1302-1306` call site — `fixer, cost_model = _build_run_fixer(args.fixer, args.max_replan)` and pass
     `fixer=fixer` (Task 5 threads `cost_model` into `run_dataset`).

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/ tests/test_cli.py -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/cli/__init__.py tests/run/test_run_fixer_plan.py
git commit -m "feat(run): wire PlanningFixEngine into gloop run as the default --fixer plan (guarded)"
```

---

## Phase 2 — Workstream 2: Close the loop (data plane + reporting)

### Task 4: `RecordingExtractor` sidecar (captures `signals`)

**Why:** `run_ticket` computes `signals = extractor.extract(logs, ticket)` then discards them; a match-miss
RCA needs them. Mirror `RecordingEstate`: a `SignalExtractor` decorator that stores the last signals.

**Files:** Create `groundloop/adapters/extractor_recording.py`. Test:
`tests/run/test_recording_extractor.py` (new).

- [ ] **Step 1: Write the failing test** —
```python
def test_recording_extractor_captures_last_signals():
    from groundloop.adapters.extractor_recording import RecordingExtractor
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
    from groundloop.core.types import Ticket
    rex = RecordingExtractor(AndroidSignalExtractor())
    t = Ticket(id="T-1", summary="NullPointerException in FooActivity", description="", logs=())
    sig = rex.extract(t.logs, t)
    assert rex.last_signals is sig                       # the exact object the loop saw
    assert hasattr(sig, "tokens") or sig is not None     # delegated to the real extractor
```

- [ ] **Step 2: Run to verify it fails** — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** —
```python
"""A SignalExtractor decorator that records the last Signals the loop computed, so the batch driver can
persist them into the oracle-free run-record (the frozen core.RunRecord drops signals). Pure adapter."""
from __future__ import annotations

from groundloop.core.types import Signals, Ticket


class RecordingExtractor:
    def __init__(self, inner):
        self.inner = inner
        self.last_signals: Signals | None = None

    def extract(self, logs, ticket: Ticket) -> Signals:
        sig = self.inner.extract(logs, ticket)
        self.last_signals = sig
        return sig
```
  (Confirm the `Signals` type import path against `core/types.py`; adjust if named differently.)

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/test_recording_extractor.py -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/adapters/extractor_recording.py tests/run/test_recording_extractor.py
git commit -m "feat(run): RecordingExtractor sidecar to capture loop signals (core untouched)"
```

---

### Task 5: Persist `signals` + `cost` + `fixer` into the run-record

**Why:** the persisted blob drops signals/cost and doesn't record which fixer ran. Extend
`RunRecordIO.write`/`RunDoc` (in `run/`, NOT frozen) + `run_dataset` + the cli call site to capture them via
the RecordingExtractor (Task 4) and the `GatewayModel` cost meter (Task 3).

**Files:** Modify `groundloop/run/record.py` (blob + `RunDoc`), `groundloop/run/batch.py`
(`run_dataset` signature + capture), `groundloop/cli/__init__.py:1302-1306` (thread `extractor_rec` +
`cost_model` + `fixer` kind). Test: `tests/run/test_batch.py` (extend).

- [ ] **Step 1: Write the failing test** — extend `tests/run/test_batch.py`: run `run_dataset` over a hermetic
  case with a `RecordingExtractor`-wrapped extractor and a fake cost model exposing `.cost_usd`,
  `.input_tokens`, `.output_tokens`, `.calls`; read back `RunRecordIO.read(...)` and assert the `RunDoc` now
  carries `signals` (a dict/list, non-null), `cost_usd`, `tokens`, `model_calls`, and `fixer` ("canned" for
  the hermetic run). For the canned path (no cost model) `cost_usd == 0.0` but the keys are present.

- [ ] **Step 2: Run to verify it fails** — FAIL (`RunDoc` has no `signals`/`cost_usd`/`fixer`).

- [ ] **Step 3: Implement** —
  1. `run/record.py`: add `signals: dict`, `cost_usd: float`, `tokens: dict`, `model_calls: int`,
     `fixer: str` to `RunDoc` and to the `blob`. `write(...)` gains keyword params
     `signals=None, cost=None, fixer=""`: serialize `signals` via a small `_signals_to_dict(sig)` helper
     (dump the extractor's public fields — e.g. `tokens`, `exceptions`, `modules`, `so_names`; use
     `dataclasses.asdict` if `Signals` is a dataclass, else `vars()`), and `cost` as
     `{"cost_usd": ..., "input_tokens": ..., "output_tokens": ..., "calls": ...}` (all 0 when `cost is None`).
     `read(...)` restores them with `.get(...)` defaults so OLD run-records still load (back-compat).
  2. `run/batch.py`: `run_dataset(..., extractor_rec=None, cost_model=None, fixer="")`. Inside the loop, after
     `run_ticket`, read `sig = getattr(extractor_rec, "last_signals", None)`; snapshot cost deltas from
     `cost_model` (record cumulative before/after each case: `c0 = cost_model.cost_usd if cost_model else 0.0`
     before, delta after) → pass `signals=sig, cost={...delta...}, fixer=fixer` to `RunRecordIO.write`.
  3. `cli/__init__.py`: wrap `extractor = RecordingExtractor(extractor)` just before the batch block; pass
     `extractor_rec=extractor, cost_model=cost_model, fixer=args.fixer` into `run_dataset`. (Keep the
     component/routing extractor swap BEFORE the RecordingExtractor wrap so it wraps the final extractor.)

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/ -q` → PASS (existing `test_batch` +
  `test_cli_selfscore` still green with the new optional fields).

- [ ] **Step 5: Commit** —
```bash
git add groundloop/run/record.py groundloop/run/batch.py groundloop/cli/__init__.py tests/run/test_batch.py
git commit -m "feat(run): persist signals + fix cost + fixer kind into the run-record (sidecar capture)"
```

---

### Task 6: Provenance `manifest.json` per batch

**Why:** run-records have no timestamp/atlas-identity/model-pins/affinity-version → no release attribution,
and no honest record that the ChangeSink is a mock. Write one manifest per `--out` batch.

**Files:** Create `groundloop/run/manifest.py`. Modify `groundloop/run/batch.py` (write it) +
`groundloop/cli/__init__.py` (pass the config). Test: `tests/run/test_manifest.py` (new).

- [ ] **Step 1: Write the failing test** — assert `write_manifest(out, cfg)` writes `<out>/manifest.json` with
  keys `timestamp`, `atlas_db`, `atlas_identity` (size+mtime string or SHA), `match_arm`, `fixer`,
  `affinity` (path + hash or ""), `model_pins` (`{"produce": ..., "embed": ...}`), `change_sink` == "mock",
  and `n_cases`. Timestamp is ISO-8601.

- [ ] **Step 2: Run to verify it fails** — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — `run/manifest.py` `write_manifest(out: str, *, atlas_db, match_arm, fixer,
  affinity, produce_model, embed_model, n_cases, change_sink="mock")`: compute `atlas_identity` from
  `os.stat(atlas_db)` (`f"{st.st_size}:{int(st.st_mtime)}"`, guard for `--index` runs where atlas_db is
  None → `""`), `affinity` hash via a cheap `hashlib.sha1` of the file bytes (or "" when absent),
  `timestamp = datetime.now().isoformat(timespec="seconds")`. In `batch.py`, call it at the end of
  `run_dataset` (thread the config through). In `cli`, pass `atlas_db=args.index_db`, `match_arm`,
  `fixer=args.fixer`, `affinity=affinity_path` (hoist the resolved affinity path so it's in scope),
  `produce_model=Settings.load().produce_main_model`, `embed_model` from settings/env.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/test_manifest.py tests/run/test_batch.py -q`
  → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/run/manifest.py groundloop/run/batch.py groundloop/cli/__init__.py tests/run/test_manifest.py
git commit -m "feat(run): write a provenance manifest.json per batch (atlas/model/affinity pins, change_sink=mock)"
```

---

### Task 7: Richer per-case grade-run card rows

**Why:** `_case_row` emits only 5 keys; the §15 canonical-record schema promises predicted/oracle repo +
signals + cost. Surface them now that they're persisted.

**Files:** Modify `groundloop/run/grade_run.py:55-65` (`_case_row`) + the row dict in `grade_run(...)` (so
`_case_row` can see `doc`/`oracle`). Test: `tests/run/test_grade_run_rows.py` (new) or extend
`test_cli_selfscore.py`.

- [ ] **Step 1: Write the failing test** — grade a fixture run dir and assert each `card["cases"][i]` now has
  `predicted_repo`, `oracle_repo`, `signals`, `cost_usd`, `fixer` in addition to the existing 5 keys.

- [ ] **Step 2: Run to verify it fails** — FAIL (rows have only the 5 original keys).

- [ ] **Step 3: Implement** — in `_case_row(row)` add:
  `"predicted_repo": row["doc"].chosen, "oracle_repo": row["owner"],
  "signals": getattr(row["doc"], "signals", None), "cost_usd": getattr(row["doc"], "cost_usd", 0.0),
  "fixer": getattr(row["doc"], "fixer", "")`. (`row["doc"]` and `row["owner"]` are already in the row dict
  built in `grade_run`; no new plumbing.) Use `getattr(..., default)` so old run-records without the fields
  still grade.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/ -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/run/grade_run.py tests/run/test_grade_run_rows.py
git commit -m "feat(grade-run): richer per-case rows (predicted/oracle repo, signals, cost, fixer)"
```

---

### Task 8: `grade-run --compare` regression comparator

**Why:** the grade-run card dead-ends — nothing diffs two production cards for regression. Add a `--compare`
flag that appends a regression section (least-surface: no new subcommand).

**Files:** Create `groundloop/run/compare.py` (`compare_cards(cur, prev) -> dict`). Modify
`groundloop/cli/__init__.py:1010-1014` (add `--compare`) + `:1227-1242` (`_run_grade_run` calls
`compare_cards` and prints/persists the section). Test: `tests/run/test_run_compare.py` (new).

- [ ] **Step 1: Write the failing test** — `compare_cards(cur, prev)` on two hand-built card dicts returns
  `{"match": {"recall@1": {"cur":..,"prev":..,"delta":..}}, "localize": {...}, "fix": {...},
  "regressions": [case_ids...], "verdict": "improved"|"flat"|"regressed"}`. Assert deltas + that a case that
  went `as_run@1 1→0` appears in `regressions` + verdict is `"regressed"` when a stage delta < 0.

- [ ] **Step 2: Run to verify it fails** — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — `run/compare.py`:
  - per-stage deltas: `match.recall@1`, `localize.as_run.file@5`, `fix.n_gradeable`/`resolved_rate_strict`,
    and a cost delta (sum of `cases[*].cost_usd`).
  - `regressions`: case_ids whose `as_run@1` or `fix` worsened vs the same case_id in `prev["cases"]`
    (index prev cases by id).
  - `verdict`: `"regressed"` if any tracked stage delta < 0 (beyond a tiny epsilon), else `"improved"` if any
    > 0, else `"flat"`.
  In cli: `grun.add_argument("--compare", default=None, help="a previous grade-run card.json — append a
  regression section")`. In `_run_grade_run`, after writing the card: if `args.compare`, load it, compute
  `comp = compare_cards(card, prev)`, write it to `<out>` sibling `*.compare.json`, and print the verdict +
  regressed case_ids.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/test_run_compare.py -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/run/compare.py groundloop/cli/__init__.py tests/run/test_run_compare.py
git commit -m "feat(grade-run): --compare a prior card for a per-stage regression verdict"
```

---

### Task 9: Promotion-eligibility flag (reporting only)

**Why:** close GAP 8's reporting edge — when a `[production]` number clears a capability's bar, grade-run
should *say so* (a human enacts). This is where Bug Plan Mode's Provisional-Core obligation surfaces.

**Files:** Create `groundloop/run/promotion.py` (`promotion_notes(card) -> list[str]`). Modify
`_run_grade_run` to print the notes. Test: `tests/run/test_promotion_notes.py` (new).

- [ ] **Step 1: Write the failing test** — `promotion_notes(card)` on a card whose `overall.fix` has
  `resolved_rate_strict={"value":0.4,"n":10}` and `fixer=="plan"` returns a note naming `PlanningFixEngine`,
  the tier `Provisional-Core`, the value, and the action `confirm Core / revert`. A card with `n==0` or
  `value is None` returns `[]` (nothing to say).

- [ ] **Step 2: Run to verify it fails** — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — a small rules table keyed by fixer/arm: if the run used the `plan` fixer
  (`card["cases"]` share `fixer=="plan"`) and `overall.fix.resolved_rate_strict.n > 0`, emit
  `f"PROMOTION-ELIGIBLE: PlanningFixEngine (Provisional-Core) resolved_rate="
  f"{v:.2f} over {n} [production] cases — confirm Core in capabilities.md, or revert to --fixer model."`
  Keep it data-driven + additive so more rules can be added. Print each note in `_run_grade_run`.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/ -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/run/promotion.py groundloop/cli/__init__.py tests/run/test_promotion_notes.py
git commit -m "feat(grade-run): promotion-eligibility notes (surfaces the Provisional-Core obligation)"
```

---

## Phase 3 — Workstream 3: Shrink the Production run surface

### Task 10: Dev-gate `--index`, `--fixer canned`, `--case` + autouse conftest fixture

**Why:** these silently degrade a production run; gate them behind `KLOOP_DEV=1` / `--dev` so a prod operator
can't mis-select them. The Type-1 suite is dev, so an autouse fixture sets the gate.

**Files:** Modify `groundloop/cli/__init__.py` (add hidden `--dev`; gate checks at the top of the `run`
branch), `tests/conftest.py` (autouse fixture). Test: `tests/run/test_dev_gate.py` (new).

- [ ] **Step 1: Write the failing test** — `tests/run/test_dev_gate.py` (this test must NOT inherit the
  autouse dev fixture — put it in its own file and have the fixture opt-out via a marker, or
  `monkeypatch.delenv("KLOOP_DEV", raising=False)` + don't pass `--dev`):
```python
def test_index_rejected_without_dev(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_DEV", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset","d","--catalog","c","--work","w","--changes","ch",
               "--index","tok.json","--out","o","--repos","r"])
    assert rc == 2 and "dev-only" in capsys.readouterr().out.lower()

def test_index_allowed_with_dev_env(monkeypatch):
    monkeypatch.setenv("KLOOP_DEV","1")
    # ... reaches past the gate (may fail later for other reasons; assert it is NOT the gate rc/message)

def test_canned_and_case_rejected_without_dev(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_DEV", raising=False)
    # --fixer canned  -> rc 2 "dev"; --case X -> rc 2 "dev"
```

- [ ] **Step 2: Run to verify it fails** — FAIL (no gate; `--index`/`--fixer canned`/`--case` run).

- [ ] **Step 3: Implement** —
  1. Add `r.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)` to the run parser.
  2. At the top of the `if args.cmd == "run":` block: `dev = args.dev or os.environ.get("KLOOP_DEV","").strip()`.
     Then, before the index/estate wiring, reject when `not dev`:
     - `if args.index and not dev:` → print "gloop run --index is dev-only (M0 TokenIndex; production uses
       --index-db). Set KLOOP_DEV=1 for hermetic runs." ; `return 2`.
     - `if args.fixer == "canned" and not dev:` → print "gloop run --fixer canned is a dev-only hermetic
       stub. Set KLOOP_DEV=1 (or use --fixer plan/model)." ; `return 2`.
     - `if args.case and not dev:` → print "gloop run --case is a dev-only single-case demo (ignores
       --fixer/--repos); production uses batch --out. Set KLOOP_DEV=1." ; `return 2`.
  3. `tests/conftest.py`: add an autouse fixture that sets `KLOOP_DEV=1` for the hermetic suite:
     ```python
     @pytest.fixture(autouse=True)
     def _hermetic_dev_mode(monkeypatch):
         """Type-1 suite is dev by definition — arm the dev gate so CLI paths using the fixture doubles
         (--fixer canned / --case / --index) stay reachable. Production (gate off) is asserted in
         tests/run/test_dev_gate.py, which opts out."""
         monkeypatch.setenv("KLOOP_DEV", "1")
     ```
     Ensure `test_dev_gate.py` opts out (it deletes the env per-test via `monkeypatch.delenv`, which overrides
     the autouse set within the same test).

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/test_dev_gate.py -q` → PASS, then the
  FULL suite `.venv/bin/python -m pytest -q` → green (the autouse fixture keeps every existing CLI test
  passing).

- [ ] **Step 5: Commit** —
```bash
git add groundloop/cli/__init__.py tests/conftest.py tests/run/test_dev_gate.py
git commit -m "feat(run): dev-gate --index/--fixer canned/--case behind KLOOP_DEV (shrink prod surface)"
```

---

### Task 11: Harden the `--repos` guard (verify snapshots exist)

**Why:** the guard is presence-only — a wrong-but-nonempty `--repos` passes yet yields empty worktrees,
re-opening fabrication. Verify snapshots actually exist.

**Files:** Modify `groundloop/cli/__init__.py:1296-1299` (the `--repos` check). Test: extend
`tests/run/test_dev_gate.py` or a new `tests/run/test_repos_guard.py`.

- [ ] **Step 1: Write the failing test** — with `--fixer plan` + a valid key: a `--repos` pointing at a
  missing dir OR an empty dir OR a dir with no catalog-repo subdirs → `main(...)` returns `2` with a message
  mentioning "snapshots"; a `--repos` dir containing a subdir for a catalog repo → passes the guard (fails
  later for unrelated reasons, not the guard).

- [ ] **Step 2: Run to verify it fails** — FAIL (an empty/snapshot-less dir passes the presence-only guard).

- [ ] **Step 3: Implement** — replace `if not args.repos:` with a helper
  `_repos_has_snapshots(repos, catalog_path) -> bool`: the dir exists, is non-empty, and contains ≥1 subdir
  whose name matches a repo in the catalog (`load` the catalog names from `args.catalog`; match against
  immediate subdir names). On failure print "gloop run --fixer model/plan: --repos <path> has no snapshots for
  the catalog repos — a real fixer over empty worktrees fabricates paths. Point --repos at an
  owner-snapshots dir." ; `return 2`. Keep the empty-string case (`not args.repos`) in the same guard.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/run/ -q` → PASS.

- [ ] **Step 5: Commit** —
```bash
git add groundloop/cli/__init__.py tests/run/test_repos_guard.py
git commit -m "fix(run): harden --repos guard to verify catalog snapshots exist (close fail-open gap)"
```

---

## Phase 4 — Docs & governance

### Task 12: Update the docs (Provisional-Core tier + everything shipped)

**Why:** the governance model, workflows, production-guide, roadmap, results-log, STATUS, and CLAUDE.md must
reflect the new default + tier + closed edges. No code; docs only. (Not a subagent TDD task — the orchestrator
does this directly or dispatches a docs subagent; verify by re-reading.)

**Files:** `docs/capabilities.md`, `docs/workflows.md`, `docs/production-guide.md`, `docs/roadmap.md`,
`docs/results-log.md`, `docs/STATUS.md`, `CLAUDE.md`.

- [ ] **Step 1: `capabilities.md`** — add the **Provisional-Core** tier (definition + the fail-safe-only
  admission criteria + the bounded/reverts-on-debt obligation, per the spec §1a). Move `PlanningFixEngine`
  from Candidate → Provisional-Core with the honest label ("default-on on the safety argument; effectiveness
  production-gated; resolves on the next instrumented [production] resolved_rate read"). Add the new Core
  members: `RecordingExtractor`, the run `manifest.json` provenance, `grade-run --compare`, the
  promotion-eligibility notes, the dev gate, the hardened `--repos` guard, and `groundloop/fix/`
  (relocated primitives). Note the run default is now `--fixer plan`.
- [ ] **Step 2: `workflows.md`** — Production checklist: default fixer `plan`; `KLOOP_DEV` gate; the
  `manifest.json` + `grade-run --compare` steps in the deploy→run→grade→feedback SOP. Update the per-stage
  feature map (fix stage default = PlanningFixEngine/Provisional-Core).
- [ ] **Step 3: `production-guide.md`** — mark closed edges `[in place]`: §7 cost now captured per case; §15
  card now emits predicted/oracle/signals/cost; §17 provenance `manifest.json` exists; §18 regression
  comparator exists. Keep live JIRA/Gerrit + human overlay `[to build]`.
- [ ] **Step 4: `roadmap.md` + `results-log.md` + `STATUS.md`** — record the change: Bug Plan Mode
  Provisional-Core default + the deferred production read; the loop-closure data-plane/reporting slice; the
  surface pruning. `results-log.md`: a 2026-07-13 `[proxy]`/design entry (no new efficacy numbers — this is
  plumbing + governance, the [production] read is the follow-on).
- [ ] **Step 5: `CLAUDE.md`** — note the `gloop run` default is now `--fixer plan` (Provisional-Core) and the
  `KLOOP_DEV=1` dev gate for the fixture paths.
- [ ] **Step 6: Commit** —
```bash
git add docs CLAUDE.md
git commit -m "docs: Provisional-Core tier + Bug Plan Mode default + loop-closure/surface-pruning updates"
```

---

## Final acceptance (after all tasks)

1. Full suite green + ruff clean: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`.
2. `gloop run` default is `--fixer plan`; `PlanningFixEngine` is built via `_build_run_fixer("plan")`;
   `adapters/fix/planning.py` imports NO `groundloop.fixeval.*`.
3. A hermetic batch run-record carries `signals`/`cost_usd`/`fixer`; `<out>/manifest.json` has the provenance
   pins + `change_sink=mock`.
4. `grade-run` cards carry predicted/oracle/signals/cost rows; `--compare` yields a regression verdict; a
   plan-fixer card with gradeable resolution prints the promotion-eligibility note.
5. With `KLOOP_DEV` unset, `--index`/`--fixer canned`/`--case` each `exit 2`; the `--repos` guard rejects a
   snapshot-less dir. With `KLOOP_DEV=1` (Type-1) everything still runs.
6. Docs (capabilities/workflows/production-guide/roadmap/results-log/STATUS/CLAUDE) reflect Provisional-Core +
   the closed edges.

Then `superpowers:finishing-a-development-branch` (final review + merge to master).
