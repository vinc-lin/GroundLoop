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

## 4. ⚠ CRITICAL calibration — `_COMPONENT_WEIGHT` (do this first, or the number lies)

`ComponentPriorIndex` combines scores **additively**: `final = base_score + weight · affinity(component)[repo]`.
The base (`AtlasIndex`) score is an **integer distinct-token count**, and the affinity weight is in `[0, 1]`, so
the combination is **scale-sensitive**. On the proxy the base scores are low (functional tickets have few code
tokens), so the shipped seed `_COMPONENT_WEIGHT = 1.0` (`groundloop/adapters/index/component_prior.py`) was
enough for the prior to dominate. **On the size-biased production base this is almost certainly too small** — a
noise repo (Telecomm/NetworkStack) can match 8–10 common tokens while the true owner matches 2, so a `weight·1.0`
boost cannot overturn it and the `component` arm would falsely regress toward `flood`'s 0.10. Your own
experiment showed the prior *should* dominate (recall@3 = 0.90), so:

**Calibrate the weight on a held-out split before trusting the 406 number.** Two options:
- **Quick:** raise `_COMPONENT_WEIGHT` until the prior dominates the size-biased base (likely ~10–50 on the raw
  token-count scale), tuned on a calib split, then frozen.
- **Robust (recommended, small code change):** normalize the base score to `[0, 1]` (or RRF-fuse the base rank
  with the affinity rank, à la `FaultRoutingIndex`) so the prior dominates **regardless** of base scale and
  `weight ≈ 1` just works. This removes the magic-number fragility entirely. (Offered as a pre-production
  hardening — see the handoff note.)

Sanity check: if `component` recall@1 ≈ `flood` recall@1 on production, the weight is too small (the prior isn't
firing), NOT evidence that the prior doesn't work.

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
