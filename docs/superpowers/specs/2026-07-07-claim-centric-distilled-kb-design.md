# Claim-Centric Distilled KB — Design Spec

**Date:** 2026-07-07
**Status:** Design (awaiting review) → to become an implementation plan via `superpowers:writing-plans`.
**Supersedes:** `docs/superpowers/specs/2026-07-06-effectiveness-driven-distilled-kb-design.md` — this reuses
its retain-loop machinery (placebo control, LOFO, the two-sided accept gate, tier ladder) but **re-centers
it on the atomic claim** and **inverts the ordering** (distill-first, not distill-last).
**Author:** GroundLoop (brainstormed with the user, 2026-07-07)

---

## 1. Motivation

The authored Skills carry useful knowledge, but they are **messy and only partly valid** — a single Skill
mixes a gold `Localize:` heuristic with a stale or wrong `Fix:` step, verbose prose, and overlap with other
Skills. The current KB design under-serves this in three concrete ways (all verified against the code):

1. **The unit of trust is the whole Skill.** Selection fires a whole Skill and injects its *entire*
   guidance (`render_skills` → preamble), so the wrong parts ride along on every run.
2. **Distillation is gated behind the messy corpus proving itself.** `kb-distill` only runs on a positive
   whole-corpus A/B verdict — but the messiness is the *reason* to distill; if the messy corpus doesn't
   lift, distillation never runs and the messy Skills are all there ever is. Backwards.
3. **The verdict is per-corpus, not per-claim.** `kb-promote` applies one accept/reject to all 12 Skills at
   once — it structurally cannot say "claim A is valid, claim B isn't."

**This design inverts the KB: the atomic, grounded *claim* becomes the unit of trust; distillation moves to
the front (raw Skills are feedstock, never injected wholesale); and validation/retention is per-claim.** The
plan-format fix stage (shipped 2026-07-07) is the enabler — it already turns each fix into structured,
checkable claims and archives them, so per-claim grounding and per-claim effectiveness become measurable.

## 2. Core principle

Applies GroundLoop's "grounding over narrative" to the KB itself:

> **A claim is "valid" only if it is (a) GROUNDED — every code entity it names actually exists — AND (b)
> EFFECTIVE — it measurably lifts the grounded fix metrics versus a length-matched placebo.** "Valid" is
> never an editorial judgment (human or LLM deciding what *looks* right); it is an operational property
> earned by measurement. The LLM may *propose* claims; only grounding + measurement may *admit* them.

## 3. Locked design decisions (from the brainstorm)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Unit of trust | the atomic **Claim**, not the Skill |
| D2 | Extraction | **Hybrid** — LLM decomposes Skills into candidate claims; a deterministic grounding gate + the effectiveness gate dispose |
| D3 | Effectiveness attribution | **Staged** — cheap archive screen → shortlist → LOFO ablation-confirm vs placebo |
| D4 | Trust boundary | **Candidates eval-only**; a claim reaches production only after it clears attribution (candidate → validated → canonical) |
| D5 | Ordering | **Distill-first** — raw Skills are feedstock, never injected wholesale |
| D6 | Taxonomy | 3 advice types (`localize_hint` / `fix_step` / `api_requirement`), each carrying its own `applies_when` predicate (reusing the existing `[skill.match]` compiler) |

## 4. The Claim model

```python
@dataclass(frozen=True)
class Claim:
    id: str                       # stable, content-derived
    applies_when: dict            # a [skill.match]-style predicate: WHEN this claim fires (reuses the compiler)
    type: str                     # "localize_hint" | "fix_step" | "api_requirement"
    content: str                  # the ONE thing it advises (this is what enters the plan prompt)
    grounding_refs: tuple[str,...] # the code entities it asserts exist (files/symbols/APIs) — checkable
    provenance: str               # the source Skill id it was distilled from (kept; never trusted)
    tier: str                     # "candidate" | "validated" | "canonical" | "retired"
    evidence: dict                # measured_lift, wilson95, validating_case_ids, fail_streak, evidence_context
```

- The old "signature" clause is **not** a claim type — it is each claim's `applies_when`. A claim is a
  *self-contained, grounded piece of advice with its own firing condition*.
- Claims persist in a **claim store** (`groundloop/kb/data/claims.json`, analogous to `provenance.json` but
  per-claim), with tiers + evidence updated by the retain-loop. `aaos_kb_seed.toml` remains as **feedstock
  provenance** only.

## 5. Architecture — the distill-first pipeline

```
messy Skills  (aaos_kb_seed.toml — feedstock, NEVER injected raw)
   │  ① EXTRACT      LLM decomposes each Skill's prose → candidate atomic claims (typed, with grounding_refs)
   ▼
 ② GROUND-CHECK      drop any claim whose grounding_refs don't resolve in the atlas; drop leak-tainted claims
   ▼                 (deterministic; oracle-blind; reuses the plan-gate existence check + the leak red-test)
 candidate claims (tier=candidate)  ───────────────►  injected ONLY in the EVAL arm
   ▼
 ③ MEASURE           run the plan-format fix eval with candidate claims injected; archive fired_claims + outcomes
   ▼
 ④ ATTRIBUTE (staged)  archive SCREEN → shortlist → LOFO ablation CONFIRM vs per-claim placebo → Δ + Wilson CI
   ▼
 ⑤ PROMOTE / RETIRE  per-claim two-sided gate; pass → tier↑ ; persistent fail → retired
   ▼
 validated / canonical claims  ─────────────────────►  the ONLY thing PRODUCTION injects
```

### 5.1 ① Extract (hybrid, LLM-proposed)
A batch step (`gloop kb-extract`) runs an LLM over each feedstock Skill's `Signature:/Localize:/Fix:` prose
and `hint_apis`, prompting it to emit **atomic typed claims**, each with an explicit `content`, a `type`,
an `applies_when` predicate (seeded from the Skill's `[skill.match]`, optionally refined), and the
`grounding_refs` it names. The LLM is a *proposer*; its output is never trusted directly.

### 5.2 ② Ground-check (deterministic, oracle-blind)
Every candidate claim is filtered:
- **Existence:** each `grounding_ref` (file/symbol/API) must resolve in the atlas (reuse
  `store.keyword_search` / the plan-gate existence primitive). A claim naming something that doesn't exist
  in the fleet is a hallucination → dropped.
- **Leak red-test:** the claim's `content`/`grounding_refs`/`applies_when` may name **no fleet-owner
  token** (reuse `kb/validate.py`'s `FLEET_OWNER_TOKENS` denylist; generic `android.*`/`androidx.*`/sonames
  kept). Prevents a distilled claim from leaking the answer.
- **Well-formedness:** valid `type`, compilable predicate, non-empty content, unique id.

Survivors enter the store at `tier=candidate`.

### 5.3 ③ Measure (candidates eval-only)
A claim-aware `ClaimRegistry.select(ctx, tier_floor)` returns applicable claims whose `applies_when` matches
**and** whose tier ≥ the floor (**`candidate` in eval, `validated` in production**). Selected claims'
`content` is composed by `render_claims(...)` into the **plan prompt**, grouped by type ("known localize
hints / fix steps / required APIs for this crash class"). The plan records **`fired_claims`** (per-claim
attribution feedstock) in the archive. Injection is oracle-blind exactly as today.

### 5.4 ④ Attribute (staged: screen → confirm)
- **Screen (cheap, no new spend):** from the accumulated plan archive, compute a directional per-claim
  signal — grounded-metric outcome on cases where the claim fired vs a matched baseline / its placebo —
  and shortlist promising *and* suspicious claims. Correlational only; used to prioritize, never to promote.
- **Confirm (causal, targeted):** for each shortlisted claim, run **LOFO ablation** (reuse
  `kb/distill/lofo.py`) — remove the claim from the candidate set on its firing cases and measure the Δ on
  the grounded metrics (`plan_target_recall@1` / `resolved_rate_strict` / `plan_groundedness` /
  `fabrication_rate`) versus its **per-claim placebo** (a length-matched irrelevant claim with the *same*
  `applies_when`, so it fires on the same cases — reuse `kb/placebo.py` at claim granularity). Yields a
  per-claim lift + Wilson-95 CI. Cost scales with the shortlist, not the whole corpus.

### 5.5 ⑤ Promote / retire (per-claim governance)
Each claim rides its own tier ladder (`candidate → validated → canonical`, + `retired`) via the two-sided
grounded gate (reuse `accept_grounded` + `lifecycle.apply_verdict`, applied **per claim**):

> **promote iff** grounded (still resolves) **∧** Δlift > 0 (Δplan_target_recall@1 or Δresolved_rate_strict)
> **∧** Δfabrication_rate ≤ 0 **∧** Δplan_groundedness ≥ 0 **∧** Wilson-95 lower bound > 0.

Promotion advances one tier; a persistent fail (hysteresis ≥ 2) retires the claim. This replaces the
whole-corpus verdict — the system can now retain claim A and retire claim B independently.

### 5.6 Runtime (production)
Identical selection/injection to §5.3 but with `tier_floor = validated`: a real fix only ever sees claims
that have *earned* promotion. `render_claims` composes them into the plan prompt. No whole-Skill prose
reaches production, ever.

## 6. Scope — reuse / change / deprecate (an inversion, not a rewrite)

- **Reuse:** the plan-format fix stage + archive (`fired_skills` → `fired_claims`), `accept_grounded` (now
  per-claim), **LOFO** (`kb/distill/lofo.py`), the placebo mechanism (`kb/placebo.py`, per-claim), the
  `[skill.match]` predicate compiler (`skills/predicate.py`), the plan-gate grounding checks, the
  leak red-test (`kb/validate.py`), and the tier/lifecycle machinery (`kb/lifecycle.py`,
  `kb/provenance.py`) — repurposed onto claims.
- **Change:** the unit (Skill → Claim); add the **extract + ground-check** front step; injection composes
  validated *claims* (`render_claims`, `ClaimRegistry`); the verdict is *per-claim*; ordering is
  *distill-first* (candidates eval-only).
- **Deprecate:** wholesale `render_skills` injection of full Skills. The 12 authored Skills become the
  **first feedstock batch to decompose**; their provenance is kept, their prose is never trusted at runtime.

## 7. Invariants preserved

- **Oracle-blind:** extraction, grounding, selection, injection, and attribution never read the oracle.
  Grounding checks the **atlas** (code reality, not the answer); attribution uses the **archive** + the
  **grounded metrics**; the offline grade remains the sole oracle read. Anti-leak red-test runs at claim
  granularity.
- **`core/` frozen; atlas SQLite schema unchanged** (grounding uses existing queries; the claim store is a
  new sidecar file, not a schema change). **bge-m3 pin** unchanged (reused only for claim rerank).
- Behavior swapped only at the composition root; the plan-format `--fixer plan` path is unchanged.

## 8. Metrics / success criteria

- **Per-claim:** measured_lift + Wilson-95 LB on the grounded metrics; a validated claim has LB > 0 and
  Δfabrication ≤ 0.
- **Corpus-level:** the *validated claim set* beats placebo on the grounded fix metrics **and is smaller /
  cleaner** than the raw Skills (compression with retained-or-improved lift) — the concrete signal that
  distillation removed the invalid/messy parts.
- **Honesty:** claims that don't clear the gate are retired, not silently kept; a "no claim beats placebo"
  outcome is a valid, reportable result.

## 9. Phasing (design-level; the impl plan will refine)

- **Phase A — Claim model + store + extraction:** `Claim`, `claims.json` store, `gloop kb-extract`
  (LLM decompose) + the deterministic ground-check/leak filter → candidate claims from the 12 Skills.
- **Phase B — Claim-aware runtime:** `ClaimRegistry` + `render_claims` into the plan prompt; `fired_claims`
  in the archive; the eval arm injects `tier≥candidate`, production injects `tier≥validated`.
- **Phase C — Staged attribution + per-claim lifecycle:** the archive screen, per-claim placebo, LOFO
  confirm, and the per-claim `accept_grounded` promote/retire loop (`gloop kb-attribute` / `kb-promote`
  per-claim).
- **Phase D — Cut over:** production selects validated/canonical claims only; deprecate `render_skills`.

## 10. Honest constraints & risks

- **Cold-start volume:** a claim needs to fire on enough cases to earn promotion (Wilson-LB > 0 needs
  N); production starts with an empty validated set and grows. The KB adds nothing to real fixes on day 1
  — by design.
- **Attribution cost:** LOFO-confirm is real fix-loop spend; the archive screen exists precisely to keep it
  to a shortlist. Ablation is gated + budgeted.
- **Extraction quality:** a bad LLM decomposition just produces more candidates that fail the gates — noisy
  but not dangerous (grounding + measurement filter them). The risk is *wasted eval spend* on junk
  candidates, mitigated by the ground-check dropping hallucinated/leaky claims before they ever run.
- **Predicate validity:** a claim's `applies_when` can be too broad/narrow; firing precision is itself
  observable from the archive (does it fire on relevant crashes?) and can gate promotion — deferred to the
  impl plan.

## 11. Open questions (for the reviewer)

1. **Claim store format** — `claims.json` (like `provenance.json`) vs a TOML corpus like the Skill seed?
   (Leaning JSON — it's machine-updated by the retain-loop, not hand-edited.)
2. **Extraction cadence** — one-time batch over the 12 Skills, or a standing `kb-extract` that also mines
   *new* candidate claims from the plan archive itself (successful fixes → candidate fix_step claims)? The
   latter closes the loop fully but is a bigger Phase-C+ item.
3. **Screen statistic** — exact per-claim archive screen (e.g. grounded-lift delta on fired vs matched
   non-fired, or fired-claim vs placebo-in-archive). To be pinned in the plan with a concrete formula.

## 12. Non-goals (this design)

- No editorial/LLM-trusted claim admission (grounding + measurement only).
- No change to the plan-format fix engine, the match stage, or the atlas schema.
- No production use of candidate (unvalidated) claims.
- Auto-mining brand-new claims from the archive (open question #2) is out of scope for the first plan.
