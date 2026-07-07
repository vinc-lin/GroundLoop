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

## Bottom line

The claim-centric KB **works as a live system** — Skills decompose into 60 grounded claims, the gate rejects
hallucinated refs, and the full inject→archive→score→compare loop runs. **Whether distilled claims beat a
placebo on the grounded metric remains unmeasured** (the preview was too small and confound-dominated to
say); that verdict is the full Phase D, which the ext4 materialization fix now makes affordable. The most
valuable artifacts of this pass: the extraction/ground-check validation, and the ext4-materialization
operational fix.
