# KB Fair-Evaluation — Phase 1 design (make resolution gradeable + isolate fix-prompt injection)

**Status:** design, approved 2026-07-12. Phase 1 of the KB re-verdict (Archived → ?). Proxy-only; no production deploy.

## Context & problem

The KB's "Archived (measured null)" verdict is unsound — it was measured on the wrong outcome:

1. **Wrong metric.** The verdict rests on `plan_target_recall@1` (a *file-targeting* metric). The KB's actual
   value channel is *fix content* → `resolved_rate` / `required_api_pass_rate` / `fabrication_rate`.
   CLAUDE.md's own rule: *"grade Skill lift on `resolved_rate`/`patch_applies`/`fabrication_rate`, never
   `file_recall@1`."* `plan_target_recall@1` is in the `file_recall` family — the wrong one.
2. **The right metric was structurally undefined.** `resolved_rate` is computed only over cases carrying
   **both** `expected_files` **and** `required_apis` (`fixeval/scorecard.py:47`). But **no dataset carries
   `required_apis`**: the miner hard-codes `required_apis=[]` (`mine/gh_miner.py:129`) and synth never emits
   it. So `resolved_rate` has been undefined on every real slice — for the whole fix loop, not just the KB.
3. **Injection confound.** Raw skills also feed the *localize query* (`_skill_query` → `runner.py:128`), so
   "raw Skills HURT (Δ−0.14)" partly measures retrieval pollution, not guidance quality.

## Goal (this phase — a de-risk)

Make resolution **gradeable for the first time** (synth-planted `required_apis`), add a **fix-prompt-only**
KB injection mode, and run a fair `none` vs `kb` A/B graded on `resolved_rate`. Outcome: does fixing the
metric + injection flip the null? This is a `[proxy]` mechanism read; a positive result promotes the KB to
**Candidate** (per the governance gate), never straight to Core.

## Design

### A. Synth — plant a gradeable `required_api` per crash class

`CrashClass` (`synth/logs.py:210`) already binds each crash class to the KB `skill_id` it fires. Extend it:

- Add `required_api: str` to `CrashClass`. Its value = the **documented, objectively-correct fix API** for
  that crash class (which the KB skill's guidance also names — because the skill is a correct playbook).
- `synth_log_for_case` returns `(text, kind, required_api)`; `write_synth_case` writes
  `oracle["required_apis"] = [required_api]` on positives that have `expected_files` (negatives keep `[]`).

**Fairness constraints (non-negotiable — this is the trap):**

1. **Not rigged.** `required_api` must be the *genuine* correct-fix API for the class (a real, documented
   Android fix), sourced from the KB skill's declared fix API — **not** an arbitrary token. We are testing
   "does the KB help the model produce the correct non-obvious fix API," not "does the model echo the KB."
2. **Headroom — the API must NOT appear in the crash log.** Some synth logs already contain the fix API
   (e.g. `build_fgs_crash` literally prints `startForeground()`). If the log reveals the API, the `none` arm
   gets it for free and the KB has no room to help → a false null. A validator **excludes** any (class,
   required_api) pair where `required_api` is a substring of the class's generated log.
3. **Grounded.** The API should be one the owner's fixed file can plausibly reference; it names no repo
   (anti-leak preserved — the required_api is a generic framework/API symbol, never a fleet repo name).

Because (2) rules out several classes (FGS, native-lib-load, media, etc. reveal their API), Phase 1 uses the
**subset** of crash classes with a clean canonical fix API absent from the log. Task 1 authors/verifies that
per-class `required_api` table (candidates: `illegalstate-after-savedinstancestate`→`commitAllowingStateLoss`;
`shared-state-race-cme`→`CopyOnWriteArrayList`; `main-thread-blocking-anr`→`Executor`/`HandlerThread`; etc.),
and the validator drops any that fail the headroom check. If too few survive, the slice is small → weak
signal, reported honestly (not laundered into a verdict).

### B. Fixeval — a fix-prompt-only injection mode

Add `--skills-inject {both,fix-only}` to `gloop fixeval` (default `both` = current behavior, back-compat).
`fix-only` sets `skill_query = ""` in `FixEvalRunner._one` so skills do **not** perturb localize, while the
fix/plan prompt still receives the `render_skills` preamble. Under `fix-only`, localize is byte-identical to
the `none` arm — isolating the KB's fix-content value from retrieval pollution. (Claims are already
fix-prompt-only; this makes skills match.)

### C. The A/B + verdict

Live, small run on the synth gradeable slice, `--fixer plan`:
- `gloop fixeval --skills none`
- `gloop fixeval --skills kb --skills-inject fix-only`   ← the fair arm
- (optional) `gloop fixeval --skills kb --skills-inject both`   ← quantifies the localize-pollution confound

Grade on `resolved_rate` / `required_api_pass_rate` / `fabrication_rate`, with `file_recall@k` as an
invariant control (must NOT move under `fix-only`). Verdict via `strengthened_accept` (reuse
`fixeval/compare.py`): KB helps iff Δ`resolved_rate` > 0 **and** Δ`fabrication_rate` ≤ 0. Log the `[proxy]`
result in `results-log.md`; update the KB state in `capabilities.md` + the `workflows.md` matrix with the
real evidence (Archived → Candidate if it shows signal; confirmed-null if it genuinely doesn't).

## Data flow

mined case → **synth (plant `required_api`, headroom-checked)** → gradeable slice → **fixeval (`none` /
`kb` `fix-only`)** → `grade_fix_all` (`resolved_rate` now defined) → `strengthened_accept` → verdict → docs.

## Error handling / anti-leak

- `required_api` planted only on positives with `expected_files`; negatives untouched (`[]`).
- Skill selection stays oracle-blind (`SkillCtx` never reads `_oracle`; `tests/skills/test_invariants.py`).
- Headroom validator is a hard gate: a class whose API leaks into its own log is dropped, not silently kept.
- `fix-only` must be provably localize-invariant (byte-identical to `none`), red-tested.

## Testing (hermetic, Type-1)

1. **synth:** a positive case's oracle gains `required_apis=[api]`; the headroom test asserts, for every
   Phase-1 class, its `required_api` is absent from the generated log; grounding regression (owner still
   ranks top-1 over `build_atlas_fixture`).
2. **fixeval `fix-only`:** localize output byte-identical to `--skills none` (skill_query empty) while the
   fix prompt still carries the skill preamble; `both` still perturbs localize.
3. **scorecard:** on the synth gradeable slice, `resolved_rate.n > 0` (resolution is finally defined).

## Decisions confirmed

- Synth-planted `required_apis` for the de-risk; **miner-extracted** `required_apis` is Phase 2.
- **Hold** the pending doc commit (`workflows.md` + `capabilities.md`) until this verdict, then commit docs +
  the KB reclassification together.
- **Pause before the live A/B** for explicit spend approval.

## Risks

- **Rigging / small slice.** Mitigated by the "documented correct fix" + headroom constraints; if too few
  classes survive, report the weak-signal caveat rather than a verdict.
- **`[proxy]` only.** A positive result → **Candidate**; Core still needs a `[production]` read on GEI
  (unreachable from the dev box) — the deploy is a separate gated step.
- **Live spend.** Serial deepseek calls; keep the slice small; pause for approval.

## Out of scope (Phase 2+)

Miner-extracted `required_apis`; SWE-bench / external benchmarks; multi-domain; flipping the fixeval default
to `fix-only`; any production deployment.
