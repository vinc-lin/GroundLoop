# Plan-Format Fix Stage — Phase 3 Live A/B Findings (2026-07-07)

The plan-format fix stage (`PlanningFixEngine`, `gloop fixeval --fixer plan`) shipped hermetically
(STATUS.md → "Plan-format fix stage — MERGED"), but its **live A/B was pending**. This is that run:
a clean, self-contained Phase 3 on a correct-match slice, answering the two questions the plan format
was built to settle — does `--fixer plan` beat `--fixer direct`, and does knowledge injection help
*under* the plan?

## Setup

- **Slice (56 cases):** all **44 positives** from the two native repos the matcher gets right —
  **oboe (25) + dlt-daemon (19)** — plus **12 negatives**. Native repos with unique `.so` match
  strongly, so localize runs on the correct repo (avoiding the antennapod size-bias mispredict → zeros
  of the claim-KB preview §3). Reused the `dataset-neg-synth-sub` synth cases.
- **Infra:** `atlas-9.db`, deepseek gateway, `--repos` **ext4-staged** (`corpora-fast`; the Finding-10
  materialization fix — ~seconds/case vs the v9fs minutes/case). `--max-replan 1`, 1800 s timeout/arm.
- **Four arms:** `direct/none` (engine baseline), `plan/none`, `plan/kb` (raw 12 Skills),
  `plan/placebo` (length-matched control). Two `gloop compare`s (the `e5caaa0` all-arms fix).
- **Signal arm:** `membership+logs`. `membership+text` carries no plan metrics (Δ=None) — do not read it.
- Reproducer: `phase3_plan_run.sh`; log `/home/vinc/gl-eval/phase3-plan.log`.

## Results (`membership+logs`, the signal arm)

| arm | `plan_target_recall@1` | `@5` | `plan_groundedness` | `file_recall@1` | `patch_apply_rate` | `fabrication_rate` |
|---|---|---|---|---|---|---|
| **direct / none** | — *(no plan)* | — | — | 0.189 | **1.00** | 0.0 |
| **plan / none** | **0.482** | **0.681** | **0.555** | 0.189 | 0.00 | 0.0 |
| **plan / placebo** (control) | 0.355 | 0.355 | 0.358 | 0.125 | 1.00 | 0.0 |
| **plan / kb** (raw 12 Skills) | 0.215 | 0.229 | 0.429 | 0.049 | 1.00 | 0.0 |

`resolved_rate_strict` = **n/a** every arm (synth cases carry no `required_apis` → resolution
ungradeable — the known §6 gap). `file_recall@1` is **fixer-invariant per case** (localize precedes
fix); its aggregate wobble (0.05–0.19) reflects which cases completed each live run, not a fixer effect,
so `plan_target_recall@1` is the reliable arm-sensitive metric.

## Q1 — Engine A/B (direct vs plan): a *structural* tie, no hard-metric verdict

`gloop compare --base direct --head plan` → **REJECT** on every axis, but read *why*:

- **`file_recall@1`: Δ = 0.0** (0.189 = 0.189). Localize runs **before** the fixer, so it is
  fixer-invariant — the plan format cannot move it, by design. A tie here is expected, not a failure.
- **Grounded axis uncomparable by construction.** `direct` emits no plan, so `plan_target_recall@1`
  base = None → Δ = None. This is not a null result; the two fixers simply don't share the grounded
  metric. The plan arm *does* produce it: `target_recall@1` **0.48**, `@5` **0.68**, groundedness
  **0.56** — a grounded, gradeable, archived repair-plan artifact that `direct` structurally lacks.
- **`patch_apply_rate`: 1.00 → 0.00.** The plan arm's *executed patches did not apply* on this synth
  slice (matching the claim-KB §7 observation: plans emit reasonable targets but the concrete patch
  doesn't apply cleanly). The plan format's value here is **front-loaded in the plan**, not the patch.
- **`fabrication_rate`: 0.0 both.** Neither fabricates; the plan gate's honesty mechanism holds.

**Verdict:** on this slice the engine A/B is **inconclusive for the hard resolution metric** — resolution
is ungradeable (no `required_apis`), `file_recall@1` is fixer-invariant, and the plan-specific grounded
metrics have no `direct` counterpart. What Phase 3 *does* establish is that `--fixer plan` produces the
intended grounded intermediate artifact (recall\@1 0.48 / \@5 0.68, groundedness 0.56, zero fabrication)
where `direct` produces nothing gradeable. **Whether the plan converts to more *resolved* bugs needs a
slice carrying `required_apis`** (the §6 dependency) — the plan's weak executed-patch apply rate (0.0)
means the win, if any, must come through resolution, which this slice can't score.

## Q2 — KB-under-plan (plan/placebo vs plan/kb): the raw KB significantly HURTS

`gloop compare --base plan/placebo --head plan/kb` → **REJECT**:
`plan_target_recall@1` **0.355 → 0.215, Δ = −0.14**; `@5` **0.355 → 0.229, Δ = −0.13**
(+0.07 groundedness doesn't rescue the recall loss). Combined with `plan/none`, the ordering is:

> **plan / none 0.48  >  plan / placebo 0.36  >  plan / kb 0.22**  (on `plan_target_recall@1`)

**No-injection beats the placebo beats the raw 12 Skills** — an *independent, fresh-run* reproduction of
the claim-KB §8 verdict. Injecting the 12 messy Skills wholesale (~17.9k chars of playbook) degrades the
planner most; a length-matched placebo is less harmful than real-but-unvalidated content, and injecting
**nothing** is best. This re-confirms the distill-first / per-claim-gated / distrust-unverified design on
a different run from §8.

## Bottom line

- **Engine A/B:** structural tie on the only gradeable shared metric (`file_recall@1`, fixer-invariant);
  the plan fixer uniquely emits a grounded, gradeable, zero-fabrication repair plan (recall\@1 0.48 /
  \@5 0.68) that `direct` lacks, but its executed patches don't apply on synth and resolution is
  ungradeable — so **a hard efficacy verdict on plan-vs-direct still needs a `required_apis`-bearing
  slice** (§6 gap in `docs/2026-07-07-claim-kb-preview-findings.md`).
- **KB-under-plan:** raw KB **hurts** (Δ −0.14); `plan/none 0.48 > placebo 0.36 > kb 0.22` reproduces §8
  — knowledge injection does not help the planner, and the messy Skills injected wholesale hurt it.
- **Honesty holds:** fabrication 0.0 across all four arms.

The two live A/Bs the plan-format track owed (engine + KB-under-plan) are now run and documented; the one
remaining open question — plan-vs-direct on *resolution* — is blocked on synth cases with `required_apis`,
not on the plan format itself.
