# Scale the Authored Corpus + Optimize the Workflow via Existing Arms — Design

> **Date:** 2026-07-20 · **Status:** design deliverable → plan(s) next. A two-phase program.
> **Provenance:** the first live end-to-end run on the 3 authored Tier-B cases (this session) exposed two
> mechanism gaps — **match flood size-bias** (newpipe→organicmaps, rank 4) and **localize queries `ticket.summary`,
> not the crash tokens** (file@1 0/3) — plus fix abstaining (0/3). We have Candidate arms built for exactly these
> (`routing`/`dispatch`, `tokens`/`cascade`/`cascade_judge`, `model`) that were never end-to-end-validated on
> realistic crash cases. **First principle — grounding over narrative:** the substrate is `[authored]` (designed,
> not observed), so this is **arm-selection + mechanism-debugging**, not effectiveness validation; wins stay
> `[authored]`, never `[production]`, never in `results-log.md`; improvements must fix the *general mechanism*,
> never overfit the specific cases.

## 1. Goal

Optimize the runtime funnel (match → localize → fix) as far as it will go on a realistic substrate, by **using and
improving the existing unvalidated Candidate arms** — iterating to a real plateau. Grow the authored corpus to
**~24 cases** first (the measuring stick; n=3 overfits instantly). `groundloop/core/` stays **frozen** — all work
is at the arm / composition-root layer.

## 2. Phase A — grow the authored corpus 3 → ~24

**2a. Harden the validator first** (at 24 cases hand-verification is infeasible; the mechanical gate must be
trustworthy). Add to `groundloop/mine/authored.py::validate_authored_case`:
- **`git apply --check`**: the `fix.diff` must apply **byte-clean** against `repo_root/<owning_repo>` at the pinned
  `owning_repo_sha` (catches the hunk-offset class of defect the 3-case cleanup found by hand).
- **non-comment API line**: the required_api must appear on an added (`+`) line that is **not** a pure comment
  (reuse `fixeval`'s `references_api_code` idea; language-aware enough for C/C++/Java `//`,`/* */`,`#`).
Both hermetic-tested (extend the fixture repo to a tiny git repo so `git apply --check` runs).

**2b. Author ~24 grounded cases** across the **9 atlas-indexed repos** (oboe, newpipe, dlt-daemon, media3,
cameraview, antennapod, android-gpuimage-plus, organicmaps, osmand — **NOT libxcam**, unindexed) × diverse crash
shapes (native `.so` backtrace, Java stacktrace, JNI boundary, ANR, C SIGSEGV/assert, OOM). Reuse the
author→adversarially-verify Workflow (author grounded in real source → validator `[]` → independent adversarial
verify). Every case: real file+symbol, real-shaped leak-safe crash log naming the symbol, a real/plausible
`fix.diff` that applies clean, full oracle (+ `owning_repo_sha`), `bug_kind=crash`. Committed under
`groundloop/mine/data/authored/` (the 3 existing cases stay). `[authored]` README updated with the count + shape mix.

## 3. Phase B — iterate the arms against the ~24, to plateau

**Setup:** stage the 12G atlas on `/dev/shm` (24G free) so the *repeated* measurement runs are fast (this is the
justified-ext4-staging case — many runs over the full corpus, unlike a one-off).

**The loop** (each iteration): `gloop run` (production defaults or the arm under test) over the ~24 → `gloop grade-run`
→ read the funnel (match recall@1/@5, localize file@1 as-run + isolated, fix resolved_strict) → attack the
highest mechanism-gap lever → land the arm swap/improvement (subagent-driven + review) → re-measure → **keep only
if it fixes the mechanism** (moves the metric for the *right reason*, across repos/shapes, not 1-2 cases), **revert
overfit** → next lever → repeat until no lever meaningfully moves the funnel.

**Lever priority (from the run's findings):**
1. **Localize — `--localize tokens`/`SignalQueryIndex`** (query = extracted crash tokens, the direct fix for
   file@1 0/3). If it moves file@1 but is short, improve the token→query construction (which signal fields, how
   ranked) and/or fall through to `cascade`/`cascade_judge` (crash-token + literal-anchor tiers). This is the
   clearest, highest-value mechanism gap.
2. **Match — `--match-arm routing`/`dispatch`** (`FaultRoutingIndex` fault-routes crash signals via the prod
   routing table + fault-scoped FTS + RRF — built for crash logs, never end-to-end-validated). Attack the flood
   size-bias (newpipe rank 4). Improve the fault extraction / routing for the shapes that still miss.
3. **Fix — `--fixer model` vs `plan`** (least likely to move; abstain may be correct). Try `model`; if it
   fabricates (fabrication_rate>0) revert — a fabricating fix is worse than an abstaining one.

**Report** the funnel after each cycle (`[authored]`), showing it move or plateau.

## 4. Guardrails (first-principle)

- **Mechanism, not overfit:** an improvement is kept only if it fixes a general mechanism (e.g. "feed crash tokens
  to localize"), reproducible across repos/shapes. Anything that only helps specific cases is reverted, and logged
  as such.
- **`[authored]` forever:** every funnel number is `[authored]` (mechanics), never `[production]`, never written to
  `results-log.md`. The real statistical/effectiveness validation still needs mined-real or GEI data.
- **`core/` frozen:** no `run_ticket`/ports/schema edit; optimization is arm selection (composition root) + arm
  internals only.
- **Plateau is honest:** "no further meaningful improvement" means the *mechanism* is sound and further gains would
  overfit ~24 cases — at which point the honest next step is more cases / production, not more tuning. State it
  plainly when reached.

## 5. Non-goals

- Not effectiveness validation, not a `[production]` claim, not new arms from scratch (use+improve existing ones).
- Not editing `core/`. Not blending authored numbers into the mined `[proxy]` corpus or `results-log.md`.
- Not chasing fix resolution as a target (it's measured; abstain-not-fabricate is the floor).

## 6. Module touch-map

| Change | Target |
|---|---|
| Validator hardening (git-apply-check + non-comment api) + tests | `groundloop/mine/authored.py`, `tests/mine/test_authored.py`, fixture git repo |
| ~21 new authored cases + README count | `groundloop/mine/data/authored/**` |
| Arm improvements (Phase B) | `adapters/index/labs/{signal_query,fault_routing,functional_text,cascade_localize,...}.py`, composition root `cli/__init__.py`, `adapters/fix/*` — per lever |
| Zero-diff | `groundloop/core/**`, atlas schema |

## 7. Open questions for the plan(s)

- Exact per-repo case/shape allocation (~24 across 9 repos × 6 shapes) — the Phase-A plan fixes it.
- Whether a localize improvement needs the crash tokens routed through the arm's `note_signals` seam (SignalQuery
  already does) or a deeper query-construction change — Phase B decides per measurement.
- Measurement cadence: baseline + one measured run per landed lever; the gated runs are `[authored]`, user-visible.
