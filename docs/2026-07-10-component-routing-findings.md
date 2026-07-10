# Component-Routing Match — Proxy Mechanism Check (2026-07-10)

The component-routing arm (spec `docs/superpowers/specs/2026-07-10-component-routing-match-design.md`, plan
`docs/superpowers/plans/2026-07-10-component-routing-match.md`) is **built, reviewed (READY TO MERGE), and
mechanism-checked** on the proxy. This is a **mechanism** validation — the real efficacy number is production's.

## Why this arm exists (production feedback)

On the real 19-repo GEI atlas, ticket-text matching collapses to **recall@1 = 0.10** (size bias: huge AOSP
repos win rank-1 on any full-system logcat). Production measured that an empirical **JIRA component→repo
affinity prior** lifts recall@1 **0.10 → 0.50** and recall@3 to **0.90** at zero token cost — the dominant
Stage-1 signal for the functional-bug class. This supersedes the functional next-steps of the 2026-07-09 v2
findings for that class. (Reconciles the earlier "component unusable" call: that was true for *naive* skills
lookup — repo-name keys vs functional-area component values, 0/10; an **empirical** map bridges the vocabulary.)

## What was built (on the proxy; production runs the real evals)

A frozen-safe, loop-blind, zero-token, **scale-invariant** additive re-ranker:
- `ComponentAffinity` — raw `component→repo` co-occurrence counts + `affinity(component, exclude=…)` for
  **leave-one-out** (subtract one unit before normalizing).
- `gloop mine-affinity` — offline miner: tallies (loop-visible `ticket.component`, offline oracle `owning_repo`)
  over answerable cases, skipping negatives.
- `ComponentExtractor` / `ComponentPriorIndex` — carry the component through the frozen `Signals` seam
  (`COMPONENT_MARK` token), **strip it before the base index** (no double-count), add `weight·affinity(comp)`.
- `gloop funceval --affinity … --loo` (component eval arm; LOO is grader-side) and `gloop run --match-arm
  {flood,routing,component}`.

## The two leak questions (grounding over narrative)

1. **Loop leak** — the runtime (`gloop run --match-arm component`, and the `ComponentPriorIndex`/extractor/
   `ComponentAffinity` modules) reads **only `Ticket.component`**, never the oracle. Enforced by a source-scan
   red-test (`tests/index/test_component_antileak.py`). ✓
2. **Train/test leak** — the affinity table is learned from the oracle, so its eval uses **leave-one-out**
   (rebuild-excluding-this-case). The owner read lives only in the offline `_component_records` LOO branch
   (grader-side, like `grade_all`), never the production runtime. ✓

## Proxy A/B (mechanism, not efficacy)

Substrate: the 212-case functional proxy (`functional-clean`) stamped with coarse **many-to-one** synthetic
components (a component maps to several repos — never a 1:1 owner alias): `Navigation`→{organicmaps, osmand},
`Media`→{antennapod, newpipe, oboe, media3}, `Camera`→{cameraview, android-gpuimage-plus},
`Diagnostics`→{dlt-daemon}, plus **17.5% blank** components. `gloop mine-affinity` → 175 (component,owner)
pairs. Base = `AtlasIndex` (FTS); the component arm = base + prior.

Numbers below are the **scale-invariant (RRF) `ComponentPriorIndex`** — the base contributes a rank-based
`1/(K+rank)` term, not its raw score, so a size-biased base's magnitude can't swamp the prior (the shipped
hardening; the earlier additive-on-raw-score form gave a higher *proxy* recall@1 of 0.58 only because the proxy
base isn't size-biased — it would collapse on production).

| arm | recall@1 | recall@3 | coverage | sel-acc | Φ₁ |
|---|---|---|---|---|---|
| flood (base) | 0.32 | 0.58 | 0.30 | 1.00 | +0.30 |
| **component** (full) | **0.49** | **0.92** | 0.83 | 0.51 | +0.01 |
| component (LOO) | 0.49 | 0.92 | 0.83 | 0.51 | +0.01 |

**Findings:**
1. **The re-ranker works AND reproduces the production shape.** The prior lifts the base to **recall@1 0.49 /
   recall@3 0.92** (flood 0.32/0.58) — the same shape as your measured production `comp+fusion` (~**0.50 / 0.90**):
   the prior narrows the field to the top-3 (recall@3 0.92), and within-component disambiguation is the remaining
   gap (recall@1). That the *scale-invariant* version lands on the production shape — where the additive-raw
   version (0.58/0.83) did not — is evidence the RRF fusion is faithful to how the real size-biased system
   behaves. (Still a *mechanism* number: the synthetic component correlates with the owner by construction;
   real efficacy is production's 0.10 → 0.50/0.90.)
2. **LOO is correct and calibrated.** Full == LOO here **because every synthetic (component,owner) pair is
   well-populated** — subtracting one case out of 22 (Diagnostics→dlt-daemon) leaves the normalized weight
   unchanged (21/21 = 22/22 = 1.0). This is the *right* behavior: LOO must **not** over-correct a well-supported
   prior. Its train/test-leak guard only bites **rare** pairs — which the unit test
   `tests/funceval/test_component_arm.py::test_loo_is_load_bearing` proves it does (a sole-contributor's boost
   vanishes under LOO, `r_loo < r_full`). On production's real long-tail components, LOO diverges from the full
   table and guards the 406-case number from memorization.
3. **Abstention needs recalibration (follow-up, not a blocker).** Φ₁ ≈ 0 / sel-acc 0.51 at coverage 0.83: the arm
   confidently answers the component's *majority* owner even when it can't disambiguate within the component, so
   the selective view is poor. The recall@1/@3 targets (the primary metric) don't depend on this; recalibrate the
   component arm's `(tau_margin, tau_score)` for the RRF+affinity margin scale if the selective/abstention
   metrics are needed. Lifting within-component recall@1 itself needs a **non-size-biased base** (e.g. the bge-m3
   functional text arm) — the Step-4 territory the production plan already flags.

## What the proxy proves vs. what production measures

- **Proxy proves:** the miner → affinity → extractor → strip-before-base → prior → LOO chain runs end-to-end on
  212 cases; the prior lifts the base; LOO is load-bearing on rare pairs and correctly-negligible on populated
  ones; runtime is loop-blind.
- **Production measures (you):** the real `component_affinity.json` over the full oracle; `gloop funceval
  --affinity … --loo` recall@1/@3 on the 406-case oracle (target: the 0.50/0.90 spot check, generalized under
  honest LOO); then the gated follow-ups (index `XCUSBMediaService` to unlock the crash track; CarPlay
  Core-vs-Integration disambiguation only if the 406 shows it's a broad problem).

## Engineering result

- **11 commits** + a follow-up **scale-invariance hardening** (RRF base term, `abfbabb`), full hermetic suite
  **552 passed / 7 skipped**, ruff clean.
- **Frozen/gated zero-diff** across the whole branch: no `groundloop/core/`, no `engines/atlas/store.py` schema,
  no `adapters/index/atlas.py` `rank_repos`, no `owner_tokens.py`, no `repo_routing.py`, no `mine/`.
- Subagent-driven, two-stage review per batch + a final holistic review (verdict READY TO MERGE). The reviews
  caught **three arithmetic/argument slips in the plan's own test fixtures** (a LOO count, a base-score
  ranking, and a `--case` flag) — corrected minimally, implementation untouched.

## Bottom line

An empirical JIRA-component→repo affinity prior, applied as a loop-blind, **scale-invariant** (RRF) re-ranker
with honest leave-one-out, is built and mechanism-validated: it lifts the FTS base to **recall@1 0.49 /
recall@3 0.92** on the proxy — the same shape as the production `comp+fusion` (**0.50 / 0.90**) — and its LOO
guard is proven load-bearing on rare pairs. This is the code for the lever production measured at **0.10 →
0.50** — ready to run the real affinity build + 406-case LOO eval on the GEI corpus.
