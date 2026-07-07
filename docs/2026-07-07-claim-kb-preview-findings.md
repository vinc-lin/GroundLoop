# Claim-Centric KB — Live Preview Findings (2026-07-07)

The claim-centric distilled KB (Phases A–C: `Claim` model + `kb-extract` + `--claims` arm + `kb-attribute`
retain-loop) is **built, reviewed, and merged to master** (`docs/superpowers/{specs,plans}/2026-07-07-
claim-centric-distilled-kb*.md`; 449 tests, `core/` + atlas schema zero-diff). Phase D — the *full* live
validation — is a gated runbook that has **not** run. This documents a **fast directional preview** run in
its place (~15 min, a 4–8-case slice), what it proved, and the operational fix that makes the real Phase D
practical.

## 1. What the preview PROVED — the pipeline runs live end-to-end ✅

The whole claim path executed on the real substrate (atlas-9.db, deepseek gateway, fleet repos):
`kb-extract` → `--claims candidate` injection into the plan prompt → `fired_claims` archive →
per-arm scorecards → grounded `gloop compare`. **Plumbing validated** — the design runs.

## 2. The headline result — extraction + ground-check work ✅

`gloop kb-extract` over the 12 authored Skills produced **60 grounded candidate claims** (30 `fix_step`,
15 `api_requirement`, 15 `localize_hint`), covering all 12 source Skills. The **deterministic ground-check
correctly dropped ~14 ungrounded proposals**, for exactly the right reasons:
- **templated placeholders** that resolve to nothing — `Java_<pkg>_<Class>_<method>`, `jniLibs/<abi>/`,
  `(Native Method)`;
- **framework APIs not indexed in the fleet atlas** — `MediaCodec.configure`, `SurfaceTexture.updateTexImage`,
  `StrictMode.ThreadPolicy.detectDiskReads`;
- **`localize_hint`s that cited nothing** (`no_grounding_refs`).

This is the **"LLM proposes, gate disposes" principle validated on real infrastructure** — the messy Skills
decompose into atomic claims, and only the grounded ones survive. It directly answers the user's original
motivation ("Skills are messy and only partly valid → distill per-claim").

## 3. The efficacy numbers were all zero — for three identifiable artifacts, NOT a KB failure

The A/B (`direct` vs `plan` vs `plan+claims`) on the tiny slice scored ~0 across the board and the grounded
verdict was **REJECT** (Δplan_target_recall@1 = None, Δresolved_strict = None). Per-case inspection made the
cause unambiguous — **three confounds, none of which is about claim quality**:

1. **Match mispredicted the slice's repo.** The 4 antennapod-owned synth cases were predicted as **media3 /
   organicmaps** — the known FTS **size-bias** (big repos win rank@1), now seen live. Wrong repo →
   localize can't find the expected files → `file_recall@1 = 0` → the entire downstream is 0.
2. **Only antennapod was staged on ext4** (see §5). So when match predicted media3/organicmaps, `materialize`
   found no snapshot → an empty work-tree → the plan arm **abstained wholesale** (`groundedness=0`,
   `abstained=True`, no patch). Correct behavior — it refused to fabricate against a nonexistent repo — but
   it means zero fix signal.
3. **The synth cases carry no `required_apis`.** `resolved` grades only over cases with BOTH `expected_files`
   AND `required_apis` (`n_gradeable = 0` here), so `resolved_rate`/`resolved_rate_strict` are `n/a`
   regardless of the fixer.

`kb-attribute` then errored — expected, since with every case abstaining there is nothing to attribute.

**A 4–8-case slice therefore cannot judge plan-vs-direct efficacy.** It is a *plumbing* validation, not an
efficacy verdict.

## 4. One real directional hint — honesty

Across the 2 negatives, **`direct` fabricated a patch on one (`fabrication_rate = 0.5`) while the `plan`
arm fabricated none (`0.0`)** — the plan gate abstained rather than patch what it couldn't ground. This is
confounded by the wholesale abstention in §3.2, so it is directional only, but it is the design's honesty
mechanism visibly working live.

## 5. THE operational finding (portable) — fixeval materialization must run off ext4

`GitFixtureEstate.materialize` (`groundloop/adapters/estate.py`) copies the **whole repo** from `--repos`
into the work-tree with `shutil.copytree` **plus `git init/add -A/commit`, once PER CASE, with no caching**
(it `rmtree`s and re-copies every call). On the **v9fs `/mnt/x` mount this dominates everything** —
minutes per case — which is why the full 278-case run took **hours** and every 6-minute-timeout preview run
died mid-copy (never reaching the model).

**Fix (measured):** stage `--repos` on **real ext4** first — `cp -a /mnt/x/code/corpora-local/<repo>
/home/vinc/gl-eval/corpora-fast/` (one slow v9fs read, paid once), then point `gloop fixeval --repos` at
the ext4 copy. Per-case materialization drops from minutes to **~seconds** (antennapod: 22 MB, copied in
35 s; the whole 6-case A/B then ran in ~15 min incl. extraction). This is the analogue of the "stage
atlas + dataset on ext4 for `gloop eval`" rule (`docs/type2-atlas-build-findings.md` Finding 8/10) — it now
also applies to **`--repos` for `gloop fixeval`**.

## 6. What the full Phase D efficacy verdict still needs (now practical)

The preview de-risked the run; a *meaningful* efficacy number needs:
- **All 9 repos staged on ext4** (§5) — turns the hours-long run into a fraction of the time.
- **A larger slice (~30–50+ cases across repos)** so matches actually land and grading has enough
  gradeable cases.
- **Awareness that the match size-bias contaminates any fix-eval** — antennapod/small-repo cases get
  mispredicted to media3/organicmaps, so fix-stage efficacy is best read on cases the matcher gets right
  (e.g. the native repos with unique `.so`, which match strongly), until the matcher's size-bias is
  addressed (coordinate on `rank_repos` — the SP1b dependency).
- Ideally, **synth cases populated with `required_apis`** so `resolved_rate`/`resolved_rate_strict` become
  gradeable for the claim arm.

## 7. Follow-up — a correct-match efficacy read (Phase D lite, ~7.5 min)

A reduced Phase D was run on a slice the matcher gets **right** (6 positives from the native repos **oboe +
dlt-daemon**, which match 42/45 and 26/26, + 2 negatives), with `--repos` staged on ext4 (Finding 10) — so
localize runs on the correct repo and the grounded metrics are real (not the antennapod mispredict → zeros of
§3). Reused the 60 candidate claims. It **completed in ~7.5 min** — each `plan` fixeval ~50 s thanks to ext4,
vs the 6-min timeouts on v9fs.

Grounded arm comparison (`membership+logs`, 6 gradeable positives):

| arm | `plan_target_recall@1` | `plan_groundedness` | `fabrication_rate` |
|---|---|---|---|
| plan / none (baseline) | 0.625 | 0.34 | 0.0 |
| plan / claims-candidate | 0.50 | 0.19 | 0.0 |
| plan / skills-placebo (control) | 0.50 | 0.12 | 0.0 |

**Finding: the raw candidate claims show no benefit and do not beat the placebo.** All three arms sit in the
same **0.5–0.625** band; on 6 cases the 0.625→0.50 gap is ~one case (noise), so this is not evidence claims
*hurt*, but there is **zero evidence the wholesale candidate dump helps**, and it clearly ties (does not
beat) the length-matched control (0.50 = 0.50 on recall; +0.07 on groundedness, also noise-level).
Fabrication was 0 across all arms. `apply_rate = 0` everywhere — plans were emitted with reasonable targets
(recall ~0.5–0.62) but the executed patches didn't apply, so `resolved_rate_strict` = n/a.

**This confirms the design rather than refuting it.** Injecting all 60 *unvalidated* candidate claims at
once buys nothing over a placebo — exactly what the distill-first, per-claim-gated architecture assumes. The
`candidate` tier is eval-only precisely because it must not be trusted wholesale; only claims that *earn* the
`validated` tier (per-claim LOFO-confirmed lift over placebo) are meant to reach production.

**The honest gap:** the retain-loop that would prune the 60 candidates to a validated subset —
`gloop kb-attribute` — **timed out** (240 s cap; each per-claim LOFO-confirm re-runs a fixeval, exceeding a
4-min slot). No tiers changed (all 60 stayed `candidate`). So the **validated-set-vs-placebo verdict (spec
§8) is still open** — it needs attribution run unbounded (~30–45 min), which the ext4 fix now makes
affordable.

**Tooling nit surfaced:** `gloop compare`'s printed verdict read the empty `membership+text` arm (no plan
metrics → Δ=None) instead of the signal-bearing `membership+logs`; the conclusion (no lift) held on both, but
`compare` should target the arm carrying the metrics.

## 8. The full Phase D verdict — unbounded two-window run (~2 h)

Re-ran the retain-loop unbounded on a correct-match slice (**oboe + dlt-daemon, 44 positives + 12
negatives**, ext4-staged), two **disjoint** windows so a claim must clear the per-claim gate twice to reach
`validated`. Wall time ~2 h (the two LOFO-confirm passes are the cost).

**No claim earned `validated`.** Every LOFO-confirmed claim across both windows had `lofo_delta = 0.0`
(removing it did not change the grounded metric → not individually load-bearing), so **none promoted**;
**4 claims were retired** (foreground-service, realtime-audio, native-null-deref fix/api claims) for failing
the W2 gate. Final store: **56 candidate, 4 retired, 0 applied/validated**.

Because the `validated` set is empty, `--claims validated` injects nothing — so that arm is the
plan-with-**no-claims** baseline. Reading D.6 (`membership+logs`, ~25 gradeable positives) with that in mind:

| arm | `plan_target_recall@1` | `plan_groundedness` |
|---|---|---|
| **no-claims** (validated set = ∅) | **0.51** | **0.60** |
| skills-placebo (control) | 0.37 | 0.43 |
| raw 12 Skills | 0.22 | 0.39 |

`gloop compare` (now reading the signal arm, fix `e5caaa0`) rules **validated-vs-placebo ACCEPT** (+0.14
recall, +0.17 groundedness) and **validated-vs-raw-Skills ACCEPT** (+0.30, +0.21). **The honest reading:**
*injecting nothing beats the placebo, which beats the raw Skills* — knowledge injection does not help, and
the **messy raw 12-Skill dump hurts the planner most** (0.22 vs 0.51 no-injection; 17,860 chars of playbook
vs 0).

**§8 answer:** run correctly over two windows, the per-claim retain-loop **admitted none of the 60 candidate
claims** (none load-bearing) and retired 4 — the safest KB here is the empty one, and the messy Skills,
injected wholesale, **actively degrade** the plan. A direct empirical vindication of the design's thesis:
*unverified knowledge is not trusted, and the messy Skills injected wholesale hurt.* **Caveats:** small slice
(2 native repos; no `required_apis` → resolution ungradeable, `plan_target_recall@1` is the signal);
`lofo_delta = 0.0` across all shortlisted claims means single-claim ablation didn't move the coarse per-case
metric at this scale — consistent with "no claim helps," but a larger/gradeable slice could still surface a
load-bearing claim this one couldn't.

## Bottom line

The claim-centric KB **works as a live system** — Skills decompose into 60 grounded claims, the gate rejects
hallucinated refs, and the full inject→archive→score→compare loop runs. A first **directional efficacy read
(§7)** shows the **raw candidate claims do NOT beat placebo** on a correct-match slice — consistent with the
design (unvalidated claims aren't trusted wholesale). The full Phase D (§8, ~2 h unbounded, two disjoint windows)
resolved it: the retain-loop validated **zero** of the 60 candidates (all `lofo_delta=0`, none load-bearing;
4 retired), and *injecting nothing beats the placebo beats the raw Skills* — the messy Skills injected
wholesale hurt the planner. The distill-first / distrust-unverified design is empirically vindicated. The most valuable artifacts of this pass: the extraction/ground-check validation, the first
grounded efficacy read, and the ext4-materialization operational fix.
