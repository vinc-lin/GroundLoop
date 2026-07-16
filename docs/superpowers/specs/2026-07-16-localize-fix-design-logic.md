# Localize & Fix — the design logic

**What this is.** The reasoning behind how GroundLoop's **localize** and **fix** stages are shaped: the
problem each solves, why each is built the way it is, the single principle that ties them together, and how
we tested that the logic actually holds. It documents design *provenance* — the "why", not the "how-to"
(that lives in `docs/guide.md`) and not the numbers alone (those live in `docs/results-log.md`).

Companion reading: `docs/stages-concept.md` (the concept behind Match·Localize·Fix), `docs/fix-loop.md`
(localize→fix→grade provenance + the KB), `docs/architecture.md` (the ports/adapters control plane),
`docs/capabilities.md` (which of these are Core vs Candidate). SSOT for efficacy: `docs/results-log.md`.

---

## 0. The one principle: grounding over narrative

Every design choice below descends from a single rule: **trust only what reality verifies.** Real matches
over a real index, deterministic control flow, patches that actually apply — these are grounded. LLM prose
is *not* trusted as truth; it is used only to **decide among grounded options**, and its output is
constrained back to grounded artifacts.

Two structural facts enforce this:

- **The Python orchestrator owns control flow.** The deterministic control plane
  (`core/workflow.py`: intake → extract → match → materialize → **localize → fix** → submit → bind) decides
  what happens; the LLM never steers the loop. Grading is a separate offline pass.
- **The loop never sees the oracle.** Localize and fix run oracle-blind; the owning repo / expected files /
  fix commit are hidden fields used only by the offline grader.

So when we "add an LLM" to localize or fix, we are never adding a narrator. We are adding a **judge over a
grounded candidate set** (localize) or a **planner gated against the real worktree** (fix). The LLM ranks or
plans; reality validates.

---

## 1. Localize — the problem

After match names the owning repo, localize must point at the **file(s) that own the defect** inside it.

The measured shape of the problem (`[production]`, `docs/results-log.md`):

> **file@5 ≈ 7/10 but file@1 ≈ 1/10.**

That is not a *recall* problem — the right file is usually already in the top handful. It is a **rank-1
precision** problem: FTS5 keyword search surfaces the right candidate but does not put it *first*. A fix that
only widens recall (more candidates) misses the point; the lever is **reordering the candidates we already
have** so the correct one lands at rank 1.

---

## 2. Localize — the design: retrieve-then-rerank

The shape is a classic two-phase IR pipeline, chosen because it separates *recall* (cheap, deterministic)
from *precision* (expensive, LLM), and keeps both grounded.

```
  signals ─▶ ┌── candidate generation ───────────────┐    ┌── grounded rerank ─────────┐
             │ FTS5 keyword ∪ bge-m3 vector (RRF)     │    │ LLM file-judge over the    │
             │ over kinds = {symbol, doc}             │─▶  │ pool, given per-candidate  │─▶ ranked files
             │ doc hits ─▶ source files (entity_map)  │    │ code-understanding context │   (pool-only)
             └────────────────────────────────────────┘    └────────────────────────────┘
             adapters/index/rerank_localize.py               GatewayFileJudge + _ground()
```

**2.1 Candidate generation keys on signals, not prose.** The pool is a hybrid FTS5 ∪ bge-m3 fusion
(`engines/atlas/retrieve.py::find_related_units`, RRF) over the *extracted signals* (class/method/`.so`
names), falling back to the ticket summary only when signals are empty. Symbols **and** CodeWiki `doc` units
are pulled. Rationale: recall first, cheaply, from the evidence the ticket actually carries.

**2.2 The doc→source bridge turns docs into candidates.** A CodeWiki `doc` unit's `file` is a wiki basename,
not source. The `entity_map` (`engines/lore/bridge`, built by `gloop bridge`) maps *module → source files*,
so a doc hit is **rewritten to the real source files it documents**. Unmappable doc hits are **dropped** — a
wiki basename must never leak into the file pool. This is the mechanism by which per-module documentation
contributes to *localization* at all.

**2.3 The rerank is a grounded judge, not a generator.** An LLM file-judge (`GatewayFileJudge`, cloned from
the match `atlas_judge` pattern) reorders the pool. Three properties make it safe:

- **Grounded (`_ground`):** the judge may only return files that are *in the pool*. Files it invents are
  dropped; files it omits are appended. It can reorder reality; it cannot fabricate it.
- **Context-fed:** each candidate is presented with **code-understanding context** — a real source snippet
  (worktree/atlas), its **CodeWiki module summary** (the doc→source bridge again), and its **live CBM
  call-graph** neighbours (`adapters/graph/cbm_live.py`). This is the payload that lets the judge tell the
  owning file from a lexical look-alike.
- **Fail-safe + cost-tracked:** no creds / any error ⇒ the base pool order (never a crash, never a
  fabrication); the judge's spend is surfaced for `$/ticket`.

**2.4 Why swap the *retriever*, not the *query*.** An earlier instinct was to enrich the localize *query*
with injected knowledge. That reproduced a **−0.10 file@1 pollution confound** (`docs/results-log.md`,
KB re-verdict): dumping tokens into the query drags retrieval off-target. Retrieve-then-rerank sidesteps it —
the query stays the ticket's own text, and the enrichment lives in the *judge's context*, downstream of
candidate-gen, where it can only reorder, not distort recall.

**2.5 Composition-root wiring, opt-in.** `SplitIndex(match, localize)` lets `gloop run` choose `--localize`
independently of `--match-arm`; `SplitIndex.rank_repos` propagates the signals into the reranker's stash so
`retrieve` keys on code tokens. `--localize rerank` is an **opt-in Candidate**: `±CodeWiki` via
`KLOOP_REGISTRY` (entity_maps present/absent), `±CBM` via `--repos` (clone root present/absent), judge gated
on gateway creds. No `core/` edit; the atlas schema is untouched (doc units are additive; the entity_map is a
side JSON; CBM is consumed live).

---

## 3. Fix — the problem

Given the localized files, produce a patch that resolves the defect. Two hazards dominate the design:

- **Fabrication is worse than silence.** A plausible-but-wrong patch is a trap: it looks like progress, binds
  a JIRA↔commit chain, and wastes a review cycle. The safe default is to **abstain, not fabricate.**
- **The loop must be gradeable.** "Did the fix work?" needs a real `@base` to apply against, a gold diff, and
  the APIs the real fix used — otherwise `resolved_rate` is undefined and the stage is unmeasurable.

---

## 4. Fix — the design: plan-then-act, gated, over real base source

```
  ticket + localized files
        │
        ▼
  ┌─ PLAN ──▶ anti-leak GATE ──▶ re-plan (bounded) ──▶ ABSTAIN ──▶ EXECUTE ─┐
  │  grounded repair plan       plan must stay        or emit a patch        │
  │  (adapters/fix/planning.py) in localized scope     gated to scope        │
  └───────────────────────────────────────────────────────────────────────┘
        applied against @base = fix_sha^   (fixeval/base_checkout.py)
```

**4.1 Plan-then-act (`PlanningFixEngine`).** The fixer first writes a **grounded repair plan**, passes it
through an **anti-leak gate** (the executed diff must stay within the localized files/APIs), **re-plans** a
bounded number of times, and **abstains** rather than emit an ungrounded patch. Rationale: a plan is
inspectable and gradeable *before* code is written, and the gate is the structural guarantee that the fixer
cannot wander outside the evidence. This is the fix-stage expression of "abstain over fabricate" — the
Provisional-Core default (`--fixer plan`).

**4.2 Fix-context = the same code-understanding, injected into the prompt.** `FixContextProvider`
(`fix/context.py`) renders two grounded blocks and prepends them to the plan+patch prompt (via
`with_preamble`, reaching *patch-writing*, not just planning):

- **CodeWiki** — for each localized file, its module's real `doc`-unit summary (file→module via the
  entity_map, text from the atlas store).
- **CBM** — for the localized symbols, the live call-graph: node source + callers/callees.

Both are `""` when their dependency is absent (byte-identical to today) and per-call fail-safe. The design
intent mirrors localize: give the fixer the *same grounded code-understanding* the reranker gets.

**4.3 Base-checkout makes fix gradeable.** `checkout_base` materializes `@base = fix_sha^` per case from the
shallow fleet clone (copytree + `git checkout sha^`, with a depth-2 fetch fallback), so the fixer edits the
**real buggy source** and `patch_applies` is a real signal. Combined with the miner now emitting the gold
`fix_patch` + `required_apis` (from the merged-PR diff), `resolved_rate` becomes computable for the first
time. All of it is oracle-*side* substrate (offline grader only), never fed to the matcher.

---

## 5. The shared thread — CodeWiki and CBM as *grounded context for a decision*

GroundLoop generates two rich, expensive assets: **CodeWiki** (per-module LLM docs) and **CBM** (a code
relationship graph). The design bet is deliberately narrow:

> Inject them as **grounded context for an LLM decision** (which file? what plan?), **never** as narrative the
> loop treats as truth.

That is why, in *both* stages, the LLM output is constrained back to reality: the judge may only return pool
files; the planner's diff is gated to localized scope. CodeWiki/CBM sharpen the *decision*; they never become
the *answer*. This is "grounding over narrative" made concrete — and, as §7 shows, it is also what the
evidence rewards.

---

## 6. How we tested the logic (the measurement design)

The reasoning is only as good as the isolation that tests it. Three disciplines:

- **Match-independent isolation.** Localize is measured by forcing retrieval onto the **oracle repo** (the
  trusted `grade_run` isolated pattern), so localize quality is not contaminated by match error. Fix is
  measured by forcing the oracle repo **and** oracle localization, so only the fix-*context* varies.
- **Ablation ladders — one variable at a time.** Localize:
  `atlas → +hybrid pool → +CodeWiki-in-pool → +judge → +CodeWiki-under-judge → +CBM`. Each rung isolates a
  single mechanism, so a delta is attributable.
- **Adversarial verification before recording.** Findings were stress-tested by four independent
  refutation lenses (harness fidelity, attribution, fix-context fidelity, over-claim) *before* entering the
  SSOT — which caught real caveats (see §7).

---

## 7. What the logic proved — and its honest limits

Full numbers + tags: `docs/results-log.md` (2026-07-16, `[proxy]`). In brief:

- **Localize — the logic holds.** The grounded judge is the rank-1 lever it was designed to be: file@1
  **0.075 (FTS5 floor) → 0.212** (isolated ceiling, n=108, 2.8×). The **judge is the larger lever (+0.083)**;
  **CodeWiki *under the judge* adds +0.056 file@1 / +0.108 file@5** on top. Notably the hybrid pool and
  CodeWiki-in-pool do ≈0 for rank-1 *without* the judge — vindicating retrieve-then-**rerank**: recall alone
  doesn't move rank-1; the grounded reorder does. CBM was **marginal for localize (+0.038, within noise)**.
- **Fix — logic sound, substrate insufficient.** On a forced-repo + forced-localization slice (n=29), the
  plan fixer correctly **abstained rather than fabricated**, and fix-context showed **no measurable effect**
  (resolved floor ≤1/29; and CBM *never fired* because the prose mined tickets carry no signals). This is the
  "abstain over fabricate" design working — and the honest read that fix effectiveness is blocked on a
  **crash-with-fix substrate**, not on context.

**The load-bearing caveats (from the adversarial pass):**
1. Localize numbers are **isolated ceilings on a prose-ticket regime** — the opposite of GEI crash tickets;
   because match scores ≈0 on prose tickets, the lift is currently unrealizable end-to-end here.
2. The **+0.056 is CodeWiki pool+context *entangled*** (one `entity_map` toggle changes both), not context
   alone; the judge remains the dominant share.
3. The fix result is **underpowered noise**, not evidence that context hurts.

**Governance consequence (`docs/capabilities.md`):** `--localize rerank` earns **Candidate** — the first
`[proxy]` file@1 lever — with the promotion gate being a `[production]` **crash-ticket** file@1 read.
`--localize +CBM` and `--fix-context {codewiki,cbm}` stay **off** (no measurable benefit / untested).

---

## 8. Design decisions, at a glance

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Localize shape | retrieve-then-rerank | one-shot FTS5 | the gap is rank-1 precision, not recall |
| Where enrichment lives | judge *context* | localize *query* | query injection reproduced a −0.10 file@1 pollution confound |
| Rerank output | grounded to the pool | free-form file list | the LLM may reorder reality, never fabricate it |
| Fix shape | plan → gate → abstain → patch | single-shot patch | inspectable/gradeable plan; scope gate; abstain over fabricate |
| CodeWiki/CBM role | grounded context for a decision | narrative the loop trusts | grounding over narrative |
| Fix gradeability | `@base = fix_sha^` + mined gold diff | proxy/empty worktree | real `patch_applies` ⇒ real `resolved_rate` |
| Rollout | opt-in Candidates | silent defaults | governance: earn Core on a `[production]` read |

---

## 9. Open threads

- **Disentangle CodeWiki pool-vs-context** — add a `judge + doc→source pool, no wiki-context` arm.
- **The promotion gate** — a `[production]` **crash-ticket** localize file@1 read (where code-token
  candidate-gen, not prose fallback, drives the pool) + an e2e (match-gated) confirmation.
- **Fix substrate** — a crash-with-fix corpus (real stack-trace tickets bound to their fix commits) so
  `resolved_rate` and the fix-context question are answerable at all.
- **CBM in fix** — genuinely untested (it never fired on signal-less tickets); revisit on the crash substrate.
