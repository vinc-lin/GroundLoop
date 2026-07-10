# Production Migration Runbook — Component-Routing Match (2026-07-10)

How to take the component-routing match arm (and the crash/functional eval split) from the proxy to the real
GEI production environment. The **code is on `master`** (merges `7012ee4` component-routing, `239ad9a`
combine-oracle); production deploys that. This runbook consolidates the production-side steps that were built on
the proxy but must be *measured* on production (the GEI corpus is production-only).

## 0. Environment assumptions

- The real **19-repo atlas** is built and reachable (`KLOOP_ATLAS_DB`).
- The **JIRA↔Gerrit oracle** carries, per case: loop-visible `ticket.json.component` (functional-area name), and
  offline `_oracle/oracle.json.owning_repo`. (The proxy had empty components; production populates them.)
- Datasets exist for the functional cases and (once Step 3 lands) the crash cases.
- **The component arm is FTS-only — it needs NO embed/LLM gateway.** Only `KLOOP_ATLAS_DB` (the `AtlasIndex`
  base) + the affinity JSON. (The bge-m3 gateway is only for the `functional`/`semantic` text arms.)

## 1. Build the real affinity table (offline, zero-cost)

```bash
gloop mine-affinity --dataset <FULL_ORACLE_DATASET> --out component_affinity.json
```
Tallies `(ticket.component → owning_repo)` over answerable cases (skips negatives). These are **population
statistics**, not per-ticket memory. Run over the **full** historical oracle — the eval's leave-one-out
(step 3) removes each scored case's own contribution, so building over the full corpus is correct and does not
leak.

## 2. Assemble the combined 406-case oracle

```bash
gloop combine-oracle --sources <CRASH_DATASET> <FUNCTIONAL_DATASET> --out combined-406
```
Copies (never mutates the sources), unions the catalogs, and stamps `bug_kind` (crash if `fault_frame` present
else functional). One dataset → one eval run that reports both classes separately.

## 3. Run the real eval under leave-one-out (THE number)

```bash
gloop funceval --dataset combined-406 --profile-db <PROF_OR_ANY> --index-db $KLOOP_ATLAS_DB \
  --arms flood,component --affinity component_affinity.json --loo --out card-406.json
```
Read `card-406.json → attribution.arms.component.by_bug_kind.{crash,functional}` for per-class recall@1/@3,
coverage, Φ_c. **Target:** the `component` arm reproduces the 10-case spot check (recall@1 ≈ 0.50, recall@3 ≈
0.90) on the functional subset, generalized under honest LOO. `--loo` is mandatory for a trustworthy number.
(`--profile-db` is unused by `flood`/`component`; pass any existing path.)

## 4. Weight calibration — RESOLVED by the scale-robust hardening (no per-deployment tuning needed)

`ComponentPriorIndex` is now **scale-invariant** (shipped 2026-07-10): the base (`AtlasIndex`) contributes a
**rank-based RRF term** `1/(K + rank)` (≤ 1/60 ≈ 0.017), NOT its raw score, so a size-biased base's raw
magnitude **cannot swamp the prior**. The affinity prior dominates the coarse ranking; the base rank only
tie-breaks. The seed `_COMPONENT_WEIGHT = 1.0` (`groundloop/adapters/index/component_prior.py`) is now robust
for essentially any weight ≳ 0.05 — **no per-deployment recalibration is required.** (This replaces the earlier
additive-on-raw-score form, where a noise repo matching 8–10 common tokens could swamp a `weight·1.0` affinity
boost.)

The proxy A/B after the hardening lands on **flood 0.32 → component recall@1 0.49 / recall@3 0.92** — the same
*shape* as your measured production `comp+fusion` (recall@1 ~0.50 / recall@3 ~0.90): the prior narrows to the
top-3, and within-component disambiguation is the remaining gap.

**One real follow-up (not a blocker for the recall number):** the arm's **abstention/`tau` is not yet
calibrated** for this RRF+affinity score scale — it currently over-answers the component's majority owner
confidently (proxy Φ₁ ≈ 0). If you need the selective/abstention metrics (not just recall@1/@3), recalibrate the
component arm's `(tau_margin, tau_score)` on a calib split. The recall@1/@3 numbers (the primary target) do not
depend on this.

Sanity check: `component` recall@3 should be well above `flood` recall@3 (the prior narrows the field); if it
isn't, the affinity table or the `Ticket.component` field is empty/mis-joined, not a weight problem.

## 5. Leak-safety (already enforced in code)

- **Runtime is loop-blind:** the deployed `gloop run --match-arm component` reads only `Ticket.component` + the
  full affinity table (no LOO, no oracle) — correct for production (use all history at inference).
- **Eval avoids train/test leak:** `--loo` (grader-side, subtracts the case's own contribution). Never report
  the 406 number without `--loo`.

## 6. Gated follow-ups (from the plan §3)

- **Step 3 — unlock the crash track:** index `XCUSBMediaService` (cloned, not yet indexed) + the other missing
  repos; add to `atlas.toml` + the catalogs; re-query the 43 crash candidates → build the crash dataset; then
  `gloop faulteval`/`funceval` can score the `routing` crash arm on *real* crashes (currently blocked by index
  coverage, not by the matcher).
- **Step 4 — CarPlay Core-vs-Integration** disambiguation: 2 cases; do **only if** the 406 run shows CarPlay
  ambiguity is a broad problem. Cheapest first: keyword heuristics (`reconnect`/`重连` → Integration;
  `session`/`Siri` → Core) → embed vs the two repos' business descriptions → LLM re-rank.

## 7. Proxy-vs-production reminder

Every proxy number in `docs/2026-07-10-*-findings.md` is a **mechanism/regression** check, not efficacy. The
proxy validated: the pipelines run end-to-end, the re-ranker lifts the base, LOO is load-bearing, no crash
regression, frozen surfaces untouched. **Production is the only efficacy scoreboard** — and my functional-text
proxy 0.68 vs the real 0.10 is the standing reminder to trust production, not the proxy.
