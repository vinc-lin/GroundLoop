# Production-Core defaults + loop closure — design (2026-07-13)

**Status:** design, 2026-07-13. Approved decisions (this session, via the understand-phase fan-out
`wf_1b44f32a-c52` + a 3-way decision gate): (1) **Provisional-Core on safety** for Bug Plan Mode;
(2) **Data plane + reporting** for the feedback loop (dev-box slice; live JIRA/Gerrit + human overlay stay
production-gated); (3) **Dev-gate + harden guard** for the risky run options. Follows the 2026-07-12 re-point
(`a7bcd5c`) that already pointed `gloop run` defaults at the Core arms.

## Goal

Three coupled changes to the Production surface, all at the composition root (`cli/__init__.py`) and in
`groundloop/{run,adapters,fix}/` — **never `core/`, never the SQLite schema**:

1. **Promote Bug Plan Mode** (`PlanningFixEngine`) to the default `gloop run` fixer, honestly recorded under a
   new **Provisional-Core** governance tier (default-on on the *safety* argument; *effectiveness* still
   production-gated).
2. **Close the feedback loop's dev-box edges** — instrument the run-record (extractor signals, fixer cost,
   run provenance) and add a run-card regression comparator + richer per-case card rows, so the loop is
   observable and feedback-ready and can *produce* the deferred production effectiveness read.
3. **Shrink the Production run surface** — dev-gate the silent-degrade fixtures (`--index`, `--fixer canned`,
   `--case`) and harden the `--repos` guard, so a production operator cannot mis-set a degraded run.

The three reinforce each other: Bug Plan Mode abstains instead of fabricating (fewer bad runs → #3);
instrumenting the loop (#2) is the prerequisite for the production read that resolves Bug Plan Mode's
Provisional-Core status (#1).

## Why these are safe/honest (the governing findings)

- **Bug Plan Mode is fail-safe, not proven-effective.** The gate scope-checks every target *before any disk
  read* (`fixeval/plan.py:136`) and returns an empty `Patch` (honest abstain) on gate failure
  (`adapters/fix/planning.py:44`); measured `fabrication_rate = 0.0`, with a recorded case of it abstaining
  where the direct fixer fabricated. But `resolved_rate` (the effectiveness metric) was **never gradeable**
  (ungradeable 2026-07-07; 0-floor 2026-07-13) — so there is **no** measured resolution lift over
  `ModelPatchEngine`. Making it the default is a charter-aligned *safety* upgrade, not a validated
  *effectiveness* one. (`[[kb-reverdict]]`, `docs/results-log.md`.)
- **The loop closes only to the grade-run card, then breaks.** Nothing consumes the card; the run-record
  drops `signals`, `cost` (hardcoded `0.0`), and all provenance. These are dev-box-fixable via sidecars/
  manifest without touching frozen `core/`. Live JIRA/Gerrit (`bound=True` is a `core/workflow.py:41`
  literal) and the human accept/reject overlay are production-gated and **out of scope here**.
- **Silent degrades a prod operator can hit:** `--index` (M0 `TokenIndex` → flood, no warning),
  `--fixer canned` (emits literal `"patch"`, unguarded), `--case` (ignores `--fixer`/`--repos`), and the
  `--repos` guard is presence-only (a wrong-but-nonempty path yields empty worktrees → re-opens fabrication).

---

## Workstream 1 — Bug Plan Mode as the Provisional-Core default fixer

### 1a. The Provisional-Core governance tier (new, in `capabilities.md`)

**Definition.** A capability made the Production **default** *before* a `[production]` effectiveness read
exists, admissible **only** when its failure mode is fail-safe.

**Admission criteria (all required):**
1. **Fail-safe mechanism** — the worst case is an *honest abstain* (empty/absent output), never a wrong or
   fabricated output. A capability whose failure is a confident-but-wrong result (e.g., an unvalidated
   aggressive re-ranker that could mis-route) is **not** eligible — it stays Candidate.
2. **Charter-aligned justification** — a first-principles safety argument tied to "grounding over narrative"
   **and/or** positive `[proxy]` evidence.
3. **A named, scheduled production read** that will resolve it.

**Obligations (what keeps it from being a loophole):**
- Recorded default-on but with **"effectiveness: production-gated"** stated explicitly.
- **Resolves on the next instrumented `[production]` run:** grade-run measures the deferred metric →
  promote to Core (bar met) or revert to Candidate / the prior default (bar missed).
- **Bounded / fail-closed on governance debt:** it does not sit in Provisional-Core indefinitely; if the
  production read has not happened by the next production cycle it reverts to the prior safe default.
- **Reversible opt-out:** the prior default (`--fixer model`) stays selectable.

Bug Plan Mode qualifies (abstains; 0 fabrication; charter-aligned; production read scheduled via Workstream 2).

### 1b. Wire `PlanningFixEngine` into `gloop run` and default to it

Three edit points in `cli/__init__.py` (verified locations):
- **`:994` argparse** — `run --fixer` becomes `choices=["canned","model","plan"], default="plan"`; help notes
  `plan` = grounded plan→gate→abstain (the production default), `model` = single-shot opt-out,
  `canned` = dev-only (Workstream 3).
- **`:1211` `_build_run_fixer`** — add a `kind == "plan"` branch returning
  `PlanningFixEngine(GatewayModel(...), max_replan=<from flag>)`. Change its signature to
  `_build_run_fixer(kind, max_replan=1)` and thread a new run `--max-replan` flag (default 1, matching
  `fixeval`, `:1109`). **Also return the `GatewayModel` handle** (or `None` for canned) so the batch driver
  can read cumulative cost — see Workstream 2.
- **`:1290` fail-closed guard** — `if args.fixer in ("model","plan"):` so the `KLOOP_PRODUCE_API_KEY` and
  `--repos` checks fire for the plan arm too (a real fixer over empty worktrees / no model fabricates; and the
  plan gate needs a real checked-out worktree to emit anything).

Record the fixer `kind` in the persisted run-record + the run manifest (Workstream 2) so a card knows which
fixer ran.

### 1c. Decouple Production-Core from the Dev-Labs `fixeval/` stack

Making `PlanningFixEngine` Core means it must not import from `groundloop.fixeval.*` (Dev-Labs-Infra).
Relocate the **plan primitives** — `PlanTarget`, `RepairPlan`, `parse_plan`, `plan_to_dict`, `PlanCheck`,
`check_plan_in_world`, `plan_groundedness`, and the `norm_path` helper they depend on — from
`fixeval/plan.py` (+ the one helper in `fixeval/patch.py`) into a Core-appropriate home
**`groundloop/fix/plan.py`** (a new `groundloop/fix/` package). Update importers:
`adapters/fix/planning.py:11` → the new home. Leave a thin compat shim in `fixeval/plan.py`
(`from groundloop.fix.plan import *  # noqa`) so `fixeval/runner.py:38` and the two tests
(`tests/fixeval/test_plan.py`, `tests/fixeval/test_plan_gate.py`) keep working unchanged. `fixeval/patch.py`
keeps re-exporting `norm_path` for its other callers.

### 1d. End-to-end anti-leak: re-gate the executed diff

Today the gate validates the *plan*, not the executed diff (`adapters/fix/planning.py` `_execute` returns
`touched_files(diff)` unchecked). For a Production default, add a post-execute scope re-check: the executed
diff's touched files must be ⊆ the localize candidate set; any out-of-scope file → treat as gate failure →
**abstain** (empty `Patch`), same as plan-level. This makes the anti-leak guarantee end-to-end and is asserted
by a new `tests/test_invariants.py` case.

---

## Workstream 2 — Close the feedback loop's data plane + reporting edge (dev-box)

Frozen `core/` is untouched; everything lands in `groundloop/run/` (the persisted blob + batch driver, which
are **not** frozen) and small sidecar decorators at the composition root.

### 2a. Instrument the run-record (sidecars + manifest)

- **Signals (sidecar `RecordingExtractor`).** New decorator over the domain `SignalExtractor` port that stores
  `last_signals` from each `.extract()`. The composition root wraps the injected extractor; `run/batch.py`
  reads `.last_signals` after each `run_ticket` call and writes a `signals` field into the persisted blob
  (`run/record.py`). This gives a match-miss RCA the "why" it lacks today.
- **Cost (no decorator — `GatewayModel` already self-tracks).** `GatewayModel` exposes `.cost_usd`,
  `.input_tokens`, `.output_tokens`, `.calls`. `_build_run_fixer` returns the model handle; `run/batch.py`
  snapshots the cumulative deltas per case and writes `cost_usd` / `tokens` / `model_calls` into the record.
  This finally lets production-guide §7's cost-per-solved gate be evaluated on a real run.
- **Provenance manifest.** `run/batch.py` writes one `<out>/manifest.json` per batch capturing the config that
  produced it: `timestamp` (from `datetime.now`, injected/normal Python — fine here), `atlas_db` path +
  a cheap identity (size+mtime or a stored build SHA if present), `match_arm`, `fixer` kind, `affinity`
  artifact path + hash, model pins (`produce_main_model`, embed model), and **`change_sink: "mock"`** so a
  `[production]`-tagged card can never be misread as a real JIRA↔commit bind. Per-record `timestamp` too.

**Deferred with the real sink (production-gated, NOT here):** an honest `bind_ok` (vs the `core` hardcoded
`bound=True`) — meaningful only once a real Gerrit `ChangeSink` can actually fail; a `RecordingChangeSink`
sidecar pairs with that adapter, not with the always-succeeding mock.

### 2b. Reporting edge

- **Richer per-case card rows.** `run/grade_run.py:_case_row` today emits only
  `{case_id, rank, as_run@1, isolated@1, fix}`. Add `predicted_repo`, `oracle_repo`, `signals` (now
  persisted), `cost_usd`, and the `fixer` kind — matching the §15 canonical-record schema the production-guide
  already advertises as auto-emitted.
- **Run-card regression comparator** — a **`--compare <prev-card.json>` flag on the existing `gloop grade-run`
  subcommand** (no new subcommand, to honor Workstream 3's reduce-surface ethos). grade-run produces the
  current card as normal, then — if `--compare` is given — diffs current-vs-prev and appends a regression
  section: per-stage deltas (match recall@1, localize file@5, fix resolved/ungradeable counts, cost/solved) +
  a per-case regression list (cases that regressed on match / localize / fix vs the prior card) + a compact
  verdict (improved / flat / regressed per stage). This is the missing analog to `fixeval/compare.py` (which
  only diffs fix-scorecards).
- **Promotion-eligibility flag (reporting only — never auto-enacts).** When a `[production]` card number
  clears a capability's stated bar, grade-run emits a suggestion line (capability, current tier, the number,
  the bar) that a human enacts by editing `capabilities.md` + flipping the default. This is where **Bug Plan
  Mode's Provisional-Core obligation surfaces**: on the first instrumented production run,
  `resolved_rate = X over N` prints `PlanningFixEngine: confirm Core / revert`.

### 2c. Explicitly out of scope (production-gated, separate track)

Live JIRA `IssueSource` (fetch + write-back), live Gerrit `ChangeSink` (real change + verifiable
JIRA↔commit bind), the human accept/correct/reject overlay for oracle-less live tickets, and the
auto-re-mine of the affinity table from production misses. These need real systems/tickets and stay in the
production-side backlog (`production-guide.md` §9–18, already `[to build]`).

---

## Workstream 3 — Prune / dev-gate risky options + harden the `--repos` guard

### 3a. The dev gate

Introduce a single gate: **`KLOOP_DEV=1`** (env) **or** a hidden `--dev` flag on `gloop run`. When the gate is
**off** (production), the following are rejected with a clear `exit 2` message instead of silently degrading:
- `--index <path>` (M0 `TokenIndex`) → "dev-only; production uses `--index-db`." (It also silently forces
  flood today.)
- `--fixer canned` → "hermetic Type-1 fixer; set `KLOOP_DEV=1` for hermetic runs."
- `--case <id>` (single-case demo; ignores `--fixer`/`--repos`) → "dev-only demo; production uses batch
  `--out`."

When the gate is **on**, all three behave exactly as today (zero behavior change for dev/Type-1).

### 3b. Harden the `--repos` guard

Replace the presence-only check (`if not args.repos`) with one that verifies snapshots actually exist: the
`--repos` root must exist and contain a snapshot directory for the catalog's repos (at minimum non-empty and
containing ≥1 catalog repo subdir; ideally all). On failure → `exit 2` ("`--repos <path>` has no snapshots
for the catalog repos; a real fixer over empty worktrees fabricates paths"). Closes the fail-open gap that
defeats the anti-fabrication intent of the existing guard.

### 3c. Hermetic-test compatibility

The dev-gated paths are exercised by ~8 Type-1 files (`tests/conftest.py`, `test_cli.py`,
`run/test_batch.py`, `run/test_cli_selfscore.py`, `test_invariants.py`, `test_fix.py`, `test_index.py`,
`funceval/test_component_arm.py`, plus the `e2e` slices). Add an **autouse `conftest.py` fixture that sets
`KLOOP_DEV=1`** for the Type-1 suite (the hermetic suite *is* dev by definition), so all existing tests keep
passing. New Type-3-style tests assert the *production* (gate-off) rejections explicitly.

---

## Data flow (after)

`gloop run --fixer plan --repos <snaps> --index-db <atlas> [--affinity <art>]`
→ fail-closed guards (key + real snapshots) → `run_ticket` (8 stages, plan→gate→abstain fixer)
→ `RecordingEstate` + `RecordingExtractor` + `GatewayModel` cost → `run/batch.py` writes per-case record
(`signals`, `cost_usd`, `fixer`, `match_arm`) + `<out>/manifest.json` (provenance, `change_sink=mock`)
→ `gloop grade-run` (richer card: predicted/oracle/signals/cost) → `gloop grade-run --compare <prev>`
(regression verdict) + promotion-eligibility flag → human promotes/reverts.

## Testing (hermetic, Type-1)

- **W1:** composition-root test that `gloop run --fixer plan` builds `PlanningFixEngine`; the plan default
  fires the fail-closed guards; the plan-primitive relocation leaves `fixeval` tests green (shim); a
  `test_invariants.py` case for the post-execute out-of-scope diff → abstain.
- **W2:** `RecordingExtractor` captures `last_signals`; batch writes `signals`/`cost_usd`/`model_calls` into
  the record (canned model → cost 0 but keys present); manifest has the provenance keys incl.
  `change_sink=mock`; richer `_case_row` keys; comparator on two fixture cards → correct per-stage deltas +
  regression list; promotion-eligibility flag fires when a fixture number clears a bar.
- **W3:** each of `--index` / `--fixer canned` / `--case` errors `exit 2` with `KLOOP_DEV` unset and works
  with it set; hardened `--repos` guard rejects a missing/empty/snapshot-less path and accepts a real one;
  the autouse dev fixture keeps the existing suite green.

## Non-goals

Live JIRA/Gerrit adapters; the human accept/reject overlay; auto-enacting capability promotions;
auto-re-mining the affinity table; changing the match-stage default (`component` stays Core; routing/
functional remain Candidates); any `core/` or SQLite-schema edit; a real `[production]` run (that is the
follow-on that *resolves* Bug Plan Mode's Provisional-Core status, run when production data is reachable).

## Risks

- **Plan fixer may resolve fewer real bugs than direct** (no `resolved_rate` data either way; synth
  `apply_rate` regressed 1.0→0.0 as a substrate artifact). Mitigated by Provisional-Core labeling + the
  scheduled production read + `--fixer model` opt-out.
- **Cost/usage depends on the gateway returning a `usage` block** — `GatewayModel` already handles a missing
  one (tokens 0); we capture `.calls` regardless, so cost is best-effort but call-count is always honest.
- **Dev-gate could break a test path we missed** — mitigated by the autouse fixture + a full suite run before
  any commit.
- **Provisional-Core as a precedent** — mitigated by the strict fail-safe-only admission criterion and the
  bounded/reverts-on-debt obligation; it is a named exception, not a relaxation of the real-data rule for
  effectiveness claims.

## Docs to update (in the plan)

`capabilities.md` (Provisional-Core tier + move `PlanningFixEngine` there + new sidecars/comparator/dev-gate
entries), `workflows.md` (Production checklist: `--fixer plan` default, dev-gate, manifest+comparator SOP
steps; per-stage map), `production-guide.md` (§7 cost now captured, §15 card fields, §17 provenance manifest,
§18 comparator — mark closed edges `[in place]`), `roadmap.md` (Provisional-Core promotion + the deferred
production read), `results-log.md` + `STATUS.md` (the change), `CLAUDE.md` (new `--fixer plan` default +
`KLOOP_DEV` gate note).
