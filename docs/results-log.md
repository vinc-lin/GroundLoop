# GroundLoop — Results Log

Chronological GroundLoop results. Each number is tagged `[proxy]` (mechanism, dev box) or `[production]`
(efficacy, GEI) — see `environments.md`. Full detail for any entry lives in git history at the cited path.

| date | track | env | headline |
|---|---|---|---|
| 2026-07-11 | functional 10-case e2e (GEI) | `[production]` | match recall@1 **7/10**, localize **7/10** file@5, fix ungradeable (empty worktree) |
| 2026-07-10 | functional-bug matching arm | `[proxy]` | functional/dispatch recall@1 **0.68** vs flood 0.32; dispatch **0.94** on crash (no regression) |
| 2026-07-10 | component-routing match | `[proxy→production]` | flood 0.32 → component **0.49/0.92** `[proxy]`; **0.10 → 0.50/0.90** `[production]` |
| 2026-07-09 | android log-match v2 | `[proxy]` | attribution recall@1 flood 0.48 → faultslice 0.86 → routing **0.94**; frame@1 0.88; decoy-robust |
| 2026-07-07 | plan-format fix stage (Phase 3) | `[proxy]` | plan emits grounded plan recall@1 0.48/@5 0.68; raw KB **hurts** (Δ−0.14); fabrication 0.0 |
| 2026-07-07 | claim-centric KB (Phase D) | `[proxy]` | retain-loop validated **0/60** claims; no-injection 0.51 > placebo 0.37 > raw Skills 0.22 |
| 2026-07-06 | first cross-stage evaluation | `[proxy]` | match recall@1 **0.60** synth / 0.02–0.23 real; localize 0.85@1 (oracle repo); fix/KB gated |

---

## 2026-07-11 · functional 10-case e2e (GEI) · `[production]`

First full 8-stage `gloop run` over the 10 functional GEI cases (19-repo atlas, 126,919 units; affinity from
1,169 JIRA↔Gerrit pairs). All 10 ran every stage to a bound change, 0 crashes.
- Match recall@1 **7/10 `[production]`** (per-case table; run summary read 8/10 — reconcile against raw scorecard).
- Localize **7/10 file@5 `[production]`**, **1/10 file@1 `[production]`** (measured on oracle repo; hybrid retrieve + qwen rerank works).
- Fix **0/10 `[production]`** — **ungraded, not a fix failure**: empty worktree (no corpus checkout for any owner), so `ModelPatchEngine` fabricates paths.
- Takeaway: the mined affinity prior generalizes to unseen tickets; misses are label≠owner (13363) + CarPlay Core-vs-Integration near-tie, both needing signal beyond the `component` field. Highest-value unblock = check out the 4 owner repos so fix is gradeable.
- detail: `docs/2026-07-11-functional-10case-e2e-findings.md`

## 2026-07-10 · functional-bug matching arm · `[proxy]`

5-arm A/B (`functional`/`dispatch` vs v2 crash arms) over a 212-case no-crash functional dataset + the 196
crash cases, on the 9-repo `atlas-9.db`.
- Functional attribution recall@1 **0.68 `[proxy]`** (Φ₁ +0.39) vs flood **0.32 `[proxy]`** — text-primary (ticket title+desc → bge-m3 repo-text profile) more than doubles it; v2 crash arms correctly abstain (0.01, coverage 0.00) on no-crash tickets.
- `dispatch` (per-case router) = **0.94 `[proxy]`** on crash == routing 0.94 — no regression — and 0.68 on functional: one arm, both classes.
- Caveat: 100% answerable, so honest-refusal negatives untested here; proxy is optimistic — real recall is production's number. Component routing dropped (JIRA `component` deemed unusable).
- detail: `docs/2026-07-10-functional-bug-match-findings.md`

## 2026-07-10 · component-routing match · `[proxy→production]`

An empirical JIRA-component→repo affinity prior as a loop-blind, scale-invariant (RRF) re-ranker with honest
leave-one-out; built + mechanism-checked on the proxy, efficacy owned by production.
- Proxy: flood 0.32 → component **recall@1 0.49 / recall@3 0.92 `[proxy]`** on the 212-case functional proxy.
- Production: ticket-text collapses to **recall@1 0.10 `[production]`** (size bias); the affinity prior lifts it to **0.50 / 0.90 `[production]`** — the dominant Stage-1 lever, at zero token cost.
- Takeaway: the RRF version lands on the production shape where the additive-raw form (0.58/0.83 `[proxy]`) would not; LOO proven load-bearing on rare pairs. Follow-up: abstention recalibration (Φ₁≈0); within-component recall@1 needs a non-size-biased base.
- detail: `docs/2026-07-10-component-routing-findings.md`

## 2026-07-09 · android log-match v2 (fault-localization + attribution) · `[proxy]`

3-arm A/B (`flood` → `faultslice` → `routing`) on a real 196-case long-logcat faultlog dataset over
`atlas-9.db`; fully deterministic (no gateway, no LLM, no cost).
- Attribution recall@1 flood **0.48 `[proxy]`** → faultslice **0.86 `[proxy]`** → routing **0.94 `[proxy]`** (clean): isolating the fault site before matching nearly doubles it.
- Decoy-robust: under hard decoys flood drops **0.48 → 0.32 `[proxy]`**; faultslice/routing unchanged (0.86/0.94) — the design removes the failure mode.
- Fault localization frame@1 **0.88 `[proxy]`** / frame@5 0.95; log-quality audit clean (0/187 owner-leak in noise → attribution earned).
- Caveat: `no_fault=9` are all the oboe audio-underrun class (a silent-behavior bug, the deferred second problem); internal validity only — real AAOS logs are the external test.
- detail: `docs/2026-07-09-android-log-match-v2-findings.md`

## 2026-07-07 · plan-format fix stage — Phase 3 A/B · `[proxy]`

Live A/B on a 56-case correct-match slice (oboe+dlt-daemon natives, ext4-staged) answering the two questions
the plan format was built to settle.
- Engine A/B (direct vs plan): a **structural tie** on the only shared gradeable metric (`file_recall@1`, fixer-invariant); the plan arm uniquely emits a grounded, zero-fabrication repair plan (**recall@1 0.48 / @5 0.68, groundedness 0.56 `[proxy]`**). Hard resolution verdict blocked on synth cases with `required_apis`.
- KB-under-plan: raw 12-Skill KB **HURTS** — `plan_target_recall@1` **0.36 → 0.22, Δ −0.14 `[proxy]`**; ordering **plan/none 0.48 > placebo 0.36 > kb 0.22 `[proxy]`**. Fabrication 0.0 across all arms.
- Takeaway: an independent reproduction of the claim-KB §8 verdict — no-injection beats placebo beats raw Skills.
- detail: `docs/2026-07-07-plan-format-phase3-findings.md`

## 2026-07-07 · claim-centric KB — live preview + Phase D · `[proxy]`

Claim-centric distilled KB run live on the real substrate (atlas-9.db, deepseek gateway): `kb-extract` →
per-claim inject → archive → score → compare.
- Extraction + ground-check work: 12 Skills → **60 grounded claims `[proxy]`**, the deterministic gate correctly drops ~14 ungrounded proposals ("LLM proposes, gate disposes").
- Phase D (unbounded, two disjoint windows, oboe+dlt-daemon): retain-loop validated **0/60 claims `[proxy]`** (all `lofo_delta=0`, none load-bearing; 4 retired). With validated set empty, **no-injection 0.51 > placebo 0.37 > raw 12 Skills 0.22 `[proxy]`** (`plan_target_recall@1`) — the messy Skills injected wholesale hurt the planner most.
- Takeaway: distill-first / distrust-unverified design empirically vindicated. Also surfaced the portable ext4 fixeval-materialization fix (stage `--repos` off ext4). Caveat: small slice, no `required_apis` → resolution ungradeable.
- detail: `docs/2026-07-07-claim-kb-preview-findings.md`

## 2026-07-06 · first end-to-end cross-stage evaluation · `[proxy]`

First grounded whole-loop eval on the 9-repo fleet (`atlas-9.db`, 475k units) over `dataset-synth` (212) +
`dataset-full` (261 real mined logs); loop runs oracle-blind, grading offline.
- Stage-1 match recall@1 **0.60 `[proxy]`** synth (Φ₁ +0.31); on real mined logs the membership matcher collapses to **0.02 `[proxy]`**, semantic recovers to **0.23 `[proxy]`**. Match is the bottleneck; size-bias (small repos lose rank-1 to giants) is the dominant error.
- Localize strong but unscored by the harness: **file_recall 0.85@1 / 0.94@5 `[proxy]`** given the oracle repo; e2e drops to **0.53@1 `[proxy]`** almost entirely from match error (cascade).
- Fix engine real + wired (loop completes, change bound) but quality **GATED** (proxy `resolved_rate`, no test exec); KB fires on 55% with valid placebo but lift **GATED**; honest-refusal built but 0 negatives in the eval sets. Submit/bind are mocks.
- detail: `docs/2026-07-06-first-evaluation.md`
