# GroundLoop — Effectiveness-Driven Distilled Dev-Experience KB (Design)

> **Status:** design spec (brainstorming output). NOT an implementation plan — the plan follows via
> `superpowers:writing-plans`. **Evolves** §3 of
> [`2026-07-05-type2-negatives-fixloop-kb-design.md`](./2026-07-05-type2-negatives-fixloop-kb-design.md)
> (SP3 "dev-experience KB as a measured arm") from an *atomic-Skills, one-shot arm* into an
> **effectiveness-driven, distilled** KB that grows by retaining only knowledge reality verified. Extends
> the SP3 plan [`2026-07-05-type2-sp3-kb-arm.md`](../plans/2026-07-05-type2-sp3-kb-arm.md).
> **Reconciled against the SP3 merge (`71a67ed`, 2026-07-06):** SP3's KB arm shipped fix-stage; this spec's
> localize-inject and the distill/lifecycle stages remain the net-new extensions. Details in §0/§3.

**Goal:** a Knowledge Base of AAOS log-analysis + bug-fixing knowledge that is **distilled from Skills**
(consolidation + effectiveness-based extraction) and is trustworthy because every entry earned its place
against the SP2 fix-eval — never because a plausible playbook was written.

**Core principle (unchanged):** *grounding over narrative.* A KB of procedural prose is the single most
dangerous artifact to inject here; the discipline that makes it safe is that **admission requires a
verified fix-eval outcome on unseen cases**, and even the distilled/summarized form must **re-earn** the
lift before it is canonical.

---

## 0. What exists (code truth) — the ground we build on
- **SP2 (shipped, master).** `groundloop/fixeval/{runner,scorecard,compare,localize,patch}.py` +
  `adapters/fix/model_patch.ModelPatchEngine` (one `deepseek-chat` propose over candidate files,
  `max_refine=1`) + `gloop {fixeval,compare}`. Real per-arm metrics: `file_recall@{1,3,5}` (graded over
  `rec.locations` from **deterministic localize**), `patch_apply_rate`, `required_api_pass_rate`,
  `resolved_rate` (**proxy** = localization∧required-api∧applies; not test-pass), `fabrication_rate`
  (Bucket-1), `phi_c`, `cost_*`. `compare` names `newly_solved`/`newly_broken` (proxy `resolved`,
  positives only).
- **SP3 KB arm (shipped, master `71a67ed`).** `groundloop/skills/{base,ctx,predicate}.py` (`Skill`,
  `SkillRegistry`, `render_skills` → "# Applicable playbooks", oracle-blind `SkillCtx`/`build_ctx`,
  closed-vocab `compile_predicate`) + `adapters/skills/mock.MockSkillRegistry` (predicate filter + gated
  bge-m3 rerank, `top_k=3`, 4-playbook seed) + migration guide (`docs/skill-kb-migration.md`) + a
  non-vacuous parity self-test. **Wired FIX-STAGE only:** `gloop fixeval --skills {none,mock}`; the runner
  injects `render_skills(registry.select(build_ctx(signals, ticket, predicted)))` into `ModelPatchEngine`
  via `with_preamble` (`fixeval/runner.py:74-77`) — AFTER match, BEFORE `localize()` (`runner.py:80`), which
  stays **skill-blind** → `file_recall@1` is skill-invariant (SP3 confirmed this and made its effect test
  assert on `resolved_rate`). `core/` + SQLite schema untouched.
- **Feedstock corpus (shipped this track, master `16904d4`).** `groundloop/kb/` — 11 grounded, leak-safe,
  localization-first crash-RCA Skills (`data/aaos_kb_seed.toml`) + `validate.py` (closed-vocab + leak
  red-test over `FLEET_OWNER_TOKENS`). Fires on **55% of the 212 synth cases**. Status = `candidate`.
  **Contract-verified against merged SP3:** the corpus loads under the real `adapters/skills/mock.load_skills`
  and all 11 predicates compile (the `tests/kb` drift-guard now RUNS, not skips). It is a SEPARATE file from
  the 4-playbook SP3 seed and is **not yet loaded by `--skills mock`** (see §3 / §7 wire-in).

## 1. The loop, formalized
The KB grows by a **retain loop** (lineage: CBR Retain phase · Voyager verified-skill library · STaR
verifier-gated curation):

```
retrieve+apply Skills  →  measure effectiveness (SP2 fix-eval A/B)  →  distill the useful parts
                                                                              ↓  (guards)
        fold validated knowledge into the KB  ←────────────────  re-validate the distilled form
```

Invariant: **admit only on verified outcome, never on narrative.** Every arrow below carries a guard; the
guards ARE the design.

## 2. Components (ports & adapters; each independently testable)
| Component | Home | Status | Responsibility |
|---|---|---|---|
| Feedstock corpus + validator | `groundloop/kb/` (our lane) | **done** | authored/harvested Skills as data; leak+contract gate |
| Harvester | `groundloop/kb/harvest/` (our lane) | deferred | build-time, split-firewalled GitHub issue↔PR → `candidate` Skills |
| `SkillRegistry` arm | `groundloop/skills/` + `adapters/skills/` (SP3) | **shipped `71a67ed`** (fix-stage) | `select(ctx)` + `render_skills`; injected at **fix** today — **localize** inject is the §3 extension |
| Effectiveness measurement | `groundloop/fixeval/` (SP2, shipped) | done | the two-sided A/B that grades a Skill's lift |
| Distiller | `groundloop/kb/distill/` (our lane) | deferred | oracle-blind, extraction-over-synthesis, leak-scrubbed |
| Lifecycle/tier manager | `groundloop/kb/lifecycle.py` (our lane) | deferred | tiers + auto-demote (staleness→demotion) |
| Provenance sidecar | `groundloop/kb/data/` (our lane) | partial | per-entry lineage + validating cases + measured lift + evidence context |

## 3. Inject point — **localize AND fix** (localization-first) [DECISION]
Skills inject at **both** the localize stage and the fix stage.
- **Why both:** an RCA playbook's biggest value is "for signature X, look in code of kind Y" — that helps
  *localization*. But under SP2 today, `file_recall` grades the **deterministic localize output computed
  before** `fixer.propose`, so a fix-only Skill is **`file_recall`-invariant** (a real code truth). To let
  a Skill earn `file_recall`, its `Localize:` half must feed the localizer.
- **Shipped today (fix-stage):** `runner.py:74-77` already injects the preamble into `ModelPatchEngine`
  after match. What remains for localize-inject: feed `render_skills(registry.select(ctx))` into
  `localize(arm.index, predicted, signals, ticket.summary)` (`runner.py:80`), which is currently skill-blind
  — e.g. append the applicable Skills' `Localize:` cues / `signals` to the retrieve query so a playbook can
  bias candidate-file ranking.
- **Coordination delta (reframed against merged SP3):** shipped SP3 injects fix-only and already ABSORBS the
  `file_recall`-invariance — its `accept()` (`fixeval/compare.accept`) uses `pos_ok = Δfile_recall@1>0 OR
  newly_solved>newly_broken`, so the positive signal comes from `newly_solved` on the `resolved` proxy. Our
  localize-inject is therefore a **net-new extension** (not a bug-fix): it makes `file_recall@1` a *live*
  positive signal instead of a dead OR-branch. It edits SP3's `runner.py`/`localize.py` → reconcile with the
  SP3 owner before wiring.

## 4. Effectiveness — honest measurement (the red-team core)
1. **Metrics that can actually move.** With localize+fix injection the skill-sensitive set is
   `file_recall@k` (via localize) + `patch_apply_rate` + `required_api_pass_rate` + `resolved_rate`
   (**proxy**) + `fabrication_rate` + `cost`. `resolved` is a proxy (no runnable AAOS tests) — every lift
   is reported as **proxy-lift**.
2. **Attribution (no confounded win-rates).** Score a Skill by a **placebo-controlled paired
   counterfactual**: same case, arms `{none, placebo, kb}` where placebo = a length/format-matched
   irrelevant playbook (nets out prompt-presence artifacts). Decide at the **population** level (case as a
   random effect, Wilson-95 CI), never per-case (per-case is underpowered under `temp=0`, `runs=1`). Fold
   on the **help/hurt sign-split**, not the mean. Multi-Skill bundles: **leave-one-out + leave-one-in**
   ablation on the *firing subset*; "useful parts" via **leave-one-fragment-out + non-inferiority**.
3. **Two-sided `accept()` (the honesty gate is mandatory).** A Skill lowers the threshold to commit a fix
   — the same lever turns a should-abstain negative into a confident fabrication. **Shipped gate**
   (`fixeval/compare.accept`): `pos_ok = Δfile_recall@1>0 OR newly_solved>newly_broken`; `honesty_ok =
   Δfabrication_rate ≤ 0`; `cost_ok` advisory unless a budget is passed. (`abstention_recall_oof` is
   skill-invariant — post-match injection can't move the abstain decision — so `fabrication_rate` on
   Bucket-1 is the honesty surface.) **Proposed strengthening for the retain loop:** also require
   **ΔΦ_c ≥ 0 across c∈{0.5,1,2}** (prices the honesty/lift trade at the deployment's cost-of-wrong) and a
   **Wilson-95 CI lower bound** on the lift, so a lucky point estimate can't promote a Skill.
4. **Splits so "validated" means unseen.** Distill/select on the **calib/train** split only; confirm lift
   on a **temporal** hold-out (`holdout-postcutoff`) + **leave-one-repo-out** (the 9→130 generalization
   canary); report TEST once, never gate on it. Apply BH-FDR multiplicity control across Skills tested.

## 5. Distillation — the fold-back (sharpest risk: oracle laundering)
"Summarize the useful parts" creates NEW unmeasured prose, and the offline distiller **sees the oracle**
during grading — it can smuggle `expected_files`/`required_apis` into loop-visible KB text (the exact leak
the architecture forbids). Guards, all mandatory:
- **Extraction over synthesis** — prefer verbatim load-bearing spans (LOFO-confirmed) to free-writing.
- **Oracle-blind distiller** — feed only loop-visible traces (ticket, `Signals`, injected Skill, the patch
  that applied, the binary "helped") — never `_oracle/`. Hard-fail if any oracle-derived token appears.
- **Leak-scrub the output** — run the ticket scrubber + `groundloop/kb/validate.py` leak red-test over the
  distilled `guidance`; reject on any owner token / file basename.
- **Re-validation gate** — the distilled form **B** becomes canonical only after a fresh `gloop fixeval`
  injecting **B** reproduces ≥ the accepted lift on the held-out/temporal split under the same two-sided
  `accept()`. If B < A, keep A or discard both. (Grounding-over-narrative applied to distillation itself.)

## 6. Lifecycle & provenance — staleness as a feature
Tiers, each a concrete gate; failing re-measurement **auto-demotes**, which removes a stale playbook from
the live prompt without human action:
- `candidate` → `applied`: fires + directional two-sided pass on its firing subset.
- `applied` → `validated`: Wilson-95 lower bound of the lift > 0 (≈30 firing cases), honesty strictly
  held, cost in budget. *(Most Skills stall here — thin strata never reach n; honest and fine.)*
- `validated` → `canonical`: reproduced across **independent realities** — the temporal/LORO hold-out, a
  **model swap** (portability), and two consecutive re-measurement cycles.
- **Demotion trigger:** event-driven (atlas SHA change · model-pin change · new harvest batch) + a ~90d TTL
  backstop; demote one tier after **two** consecutive fails (hysteresis absorbs gateway noise).

**Provenance sidecar** (per entry, so it stays traceable + droppable): `id`, `tier`, source lineage
(authored doc / harvested issue-PR refs / distilled parent-ids + run-id), `validating_case_ids`
(opaque, split-tagged), `measured_lift` (Δs + Wilson CI, flagged **proxy**), `evidence_context`
(`atlas_db_sha`, `bge-m3`, model pin, `n_firing`, date), `fail_count`/`demotions[]`, `leak_check`.

## 7. Feasibility & phasing — build the measurement, defer the automation
The bundle A/B is ~$2 and answers the real question; the full self-improving lifecycle is not justified
until (a) the A/B shows a lift worth protecting and (b) enough cases fire per Skill to validate one.
- **Phase A (now — mostly unblocked):** feedstock corpus (**done**) + SP3 fix-stage arm (**shipped**). The
  remaining wire-in is small: (a) let `--skills` load OUR corpus — add `--skills-seed <path>` (the CLI
  hardcodes `MockSkillRegistry.load()`'s default seed today) or repoint the default at `groundloop/kb/data/`;
  (b) add a length/format-matched **`placebo`** seed for the control arm; (c) optionally the §3
  localize-inject. Then run the capped bundle A/B (`--skills none|placebo|kb` over the firing subset +
  Bucket-1 negatives) → **one two-sided `accept()` verdict.** That verdict *is* the loop proven end-to-end.
- **Phase B (iff A is positive):** harvester (split-firewalled) + tier/lifecycle manager + provenance
  sidecar.
- **Phase C (iff B yields a canonical-worthy entry):** the oracle-blind, split-firewalled distiller +
  re-validation gate.
- **Smallest first slice:** the 11 candidate Skills, one matcher arm, `deepseek-chat`, `temp=0`, snapshot;
  `none` vs `placebo` vs `kb`; success = `accept()` accepted with no `fabrication_rate` regression.

## 8. Coordination & guardrails
- **Lanes:** feedstock corpus / harvester / distiller / lifecycle = **our (dataset/eval) lane**; the
  `SkillRegistry` arm = **SP3 (shipped `71a67ed`)**; the fix-eval = **SP2 (shipped)**. The corpus is the
  shared interface. Two concrete wire-ins to reconcile with the SP3 owner: **(1) corpus load** — `--skills
  mock` loads only the 4-playbook SP3 seed (`adapters/skills/data/aaos_playbooks.toml`); our 11 Skills
  (`groundloop/kb/data/aaos_kb_seed.toml`) need a `--skills-seed` option or a merged/repointed default;
  **(2) the localize-inject** (§3), which edits SP3's `runner.py`/`localize.py`.
- **Untouched:** `rank_repos`, `groundloop/mine/`, `owner_tokens.py`, `cli/_run_mine` (other sessions).
- **Invariants:** frozen `core/`; no SQLite schema change; embedders pinned `bge-m3` (query==index); the
  fix loop + registry **never read `_oracle/`**; grading is the sole offline oracle read; every
  injected/harvested/distilled Skill passes the leak-scrubber.

## 9. Risks & open questions
- **Proxy ceiling.** Effectiveness optimizes file_recall/patch/required-api, not resolution — a Skill can
  win the proxy without fixing. Grow the runnable-test subset; report proxy-vs-resolved gap where testable.
- **Thin strata.** Many Skills fire on <30 cases → CIs only directional → the tier ladder bottlenecks at
  `applied`. Honest ceiling set by fleet size, not effort.
- **Synth-dataset coverage gap.** 3 corpus Skills fire on 0 synth cases; broaden the synth generator
  (binder / savedInstanceState / ANR crash classes) so more Skills are measurable.
- **Distiller integrity.** If we cannot guarantee the oracle-blind + split-firewall + re-validation
  guards, **do not build the distiller** — keep the KB author+harvest only.

## 10. Relationship to existing docs
Extends [`type2-evaluation.md`](../../type2-evaluation.md) (Test-2 canonical) and
[`downstream-fix-loop.md`](../../downstream-fix-loop.md) (measured-arm rule). Evolves §3 of the
negatives-fixloop-kb spec and the SP3 plan (now **shipped**, `71a67ed`). The feedstock corpus + validator
are already on master (`groundloop/kb/`), contract-verified against the merged SP3 loader.
