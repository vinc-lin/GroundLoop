# GroundLoop — First-Principles Review (Aggressive)

> **Date:** 2026-07-18 · **Status:** review deliverable (Phase 1 of a review→spec cycle). **Not SSOT** —
> this is an argument *about* the system, meant to force a rescope; the canonical docs are in `docs/`.
>
> **Method.** A deliberately aggressive first-principles teardown that pre-exempts **nothing** except three
> fixed correctness invariants (oracle-blindness, the anti-leak contract, deterministic Python control
> flow). Produced by a grounded multi-agent workflow: 8 sacred-cow teardowns, each **refuted by 3
> independent skeptics against the real code** before it earned a place here, plus 3 radical
> target-architecture designs scored by a 4-lens judge panel (48 agents; the survivors below are the claims
> that lived through refutation). Every efficacy number is tagged `[proxy]` (dev-box, "systematically
> optimistic" by the project's own admission) or `[production]` (the one real read). Line citations in
> `core/workflow.py` and `capabilities.md` were verified by hand.

---

## 0. The one-paragraph verdict

The shipped, `[production]`-validated GroundLoop is **a ~60-LOC Stage-1 repo matcher** (`AtlasIndex` FTS5
"flood" fused with `ComponentPriorIndex` component→repo affinity via RRF, recall@1 **0.10 → 0.50**) **plus a
recall-localize** that also earned a real read (**7/10 file@5**), **wrapped in a genuinely minimal 42-LOC
oracle-blind control plane.** That control plane is excellent and should not be touched. Everything else —
**65% of the tree is a vendored build-time doc generator the runtime imports *zero lines of*,** and the rest
is a research apparatus (13 index arms, 4 eval harnesses for one concept, an empty-store KB validated
**0/60**) that the project's **own governance says a `[proxy]` read can never promote to Core** — is either
build scaffolding or falsification machinery. The apparatus is disciplined and defensible; it de-risked the
one win and caught the arms that failed. **But the product is not a "closed-loop bug-fixer across 130+
repos." It is a validated repo matcher and a rigorous research lab, and the documentation must say so.**

## 1. The fundamental problem — and the honest headline

**The problem, in one sentence:** *From a JIRA ticket's text + failure-log signals, predict which of 130+
AAOS repos **owns** the defect — oracle-blind (the loop never sees the answer; grading is a separate offline
pass).*

You cannot state it in one sentence *without the qualifier* "then localize → fix → bind," because the
charter deliberately fuses **two** problems: a *pipeline* (fix a bug) and a *benchmark* (prove the pipeline
works). That duality is the honest reason for the size — but it has been used as a narrative that licenses
sprawl, and the evidence does not support treating the two halves as co-equal delivered capabilities.

**The honest headline the charter currently oversells:** GroundLoop has validated **exactly one thing in
production** — Stage-1 matching at recall@1 **0.50**. That number is **wrong half the time**, on **n = 10
cases**, from a GEI fleet **the dev box cannot even reproduce**. Everything downstream (localize → fix →
bind, the "traceable JIRA↔commit chain") is **charter aspiration, not delivered capability.** This is not a
criticism of the work; it is a correction of the *label*.

## 2. The smallest workflow that solves it

```
extract signals (AndroidSignalExtractor)
   → rank_repos (AtlasIndex FTS5 flood ⊕ ComponentPriorIndex affinity, RRF)
   → top-k RepoScore                       ← the ONLY [production]-validated deliverable, ~60 LOC
   [→ retrieve (plain FTS5) as a recall SEED ← also earned a [production] read, 7/10 file@5]
```

That is it. The validated product is **~60 LOC of retrieval + an affinity prior over a symbol atlas.** A
recall-localize step is a legitimate *second* stage — but as a **seed, not a gate** (`workflow.py:33-35`
hands the fixer the full worktree *and* the locations; localize does not filter the fix). The remaining
stages of the advertised 8 are I/O plumbing, one real-but-unproven stage, and two always-mock sinks.

## 3. Stage-by-stage — why it exists, what breaks, could it merge

`run_ticket` runs 8 named stages. First-principles, they are **not** 8 co-equal stages:

| Stage | Reality | Verdict |
|---|---|---|
| **intake** | `issues.fetch` — pure I/O | plumbing, trivial, keep |
| **extract** | logs → `Signals` — the discriminator that beats prose | **essential, validated** |
| **match** | `rank_repos` → top-1 = the prediction | **the product** — `[production]` 0.50 |
| **materialize** | `estate.materialize` — pure I/O checkout | plumbing, trivial, keep |
| **localize** | `retrieve` → seed files; got a `[production]` read (7/10 file@5) | **real second stage, as a seed** |
| **fix** | `PlanningFixEngine`/`ModelPatchEngine` — real code | **`[production]`-UNPROVEN** (0/10, ungraded, empty worktree) |
| **submit** | `MockGerrit` — always mock | aspirational |
| **bind** | `MockGerrit.bind` → then `bound=True` is a **hardcoded literal** | **aspirational; delivers a constant, not a chain** |

**The sharp finding — `bound=True` is a constant sold as an efficacy read.** `core/workflow.py:42`
constructs the `RunRecord` with `bound=True` unconditionally; the `changes.bind()` call on line 39 returns
nothing and its outcome is never checked. Yet `capabilities.md:72` cites *"executed all 8 stages to a **bound
change on 10/10 cases**, 0 crashes `[production]`"* as the Core efficacy evidence for the flagship `gloop
run` capability. **A hardcoded literal is being reported as a `[production]` result.** The same doc admits
(§4) that the JIRA↔commit chain is mocked at both ends — so the registry line contradicts the gap admission
four sections later.

**The one real merge signal — `CodeIndex` is wrong-shaped.** The port fuses *match* (`rank_repos`) and
*localize* (`retrieve`) into one interface, and `retrieve(repo, query)` cannot carry `Signals`
(`workflow.py:33` passes only `ticket.summary`). To work around this, three localize adapters keep a mutable
`_last_signals` side-channel with a documented "race-free *only because the batch runs sequentially*" caveat
(`adapters/index/signal_query.py`), plus a 24-LOC `SplitIndex` wrapper exists solely to let `--localize`
differ from `--match-arm`. This is a genuine design smell — **but the clean fix (split into `RepoMatcher` +
`Localizer(repo, signals, query)`) edits the FROZEN core and cannot be done** under fixed-invariant #3.
Document it; do not act on it.

## 4. Essential vs implementation

| **Essential** (invariant-bearing — keep verbatim) | **Implementation choice** (swappable/removable without touching an invariant) |
|---|---|
| The oracle-blind `run_ticket` (**42 LOC, takes no `oracle` argument** — *this single fact is the real "hexagon"*, not the 7 ports) | The 45-LOC `@runtime_checkable` Protocol layer (structurally inert — nothing subclasses it; loop tests substitute plain classes with zero inheritance) |
| The concrete dataclasses in `types.py` | The **13 `CodeIndex` arms** (one validated; the rest `[proxy]`-only) |
| The anti-leak scrub (`mine/scrub`, 136 LOC) | The **vectors table + CBM + bge-m3 embed** layer (never in a `[production]` number; default query reads no vector) |
| **FTS5 + affinity retrieval** (~60 LOC) | The **`produce/` doc generator** (19,914 LOC, build-only) |
| One offline recall grader | **3 of the 4 eval harnesses** (one concept, four implementations) |
| | **The entire current KB implementation** (empty store, 0/60) |

The lesson: **the concept count is tiny; the implementation count is the sprawl.** ~7 conceptual ports, one
atlas, five logical steps — versus 13 index arms, 4 harnesses, a 20k-LOC generator, and a KB track.

## 5. Can it be simpler? — surviving findings (each refuted against real code)

Ranked by value/risk. These **survived** adversarial refutation; §6 lists what did not.

| # | Finding (grounded) | Move | Risk | Value |
|---|---|---|---|---|
| **1** | `engines/produce` is **65% of the tree** (19,914 LOC), coupled by 2 import sites + a ~30-LOC markdown contract, imports **0 runtime lines**, emitted **0 doc units** in the only production run; ~4,500 LOC (web FE, MCP, HTML viewer) is dead even inside it | **Externalize** to a standalone build utility (`externalize ≠ delete`); `build_atlas` symbol-only by default (`wiki_stub` already does this) | **Low** | **High** |
| **2** | `bound=True` hardcoded (`workflow.py:42`) is cited as `[production]` Core evidence (`capabilities.md:72`); submit+bind are always-mock | Compute `bound` from a real binding or delete the field; **rescope** the "8-stage closed loop" claim to "validated match + recall-localize · unproven fix · mocked bind" | **Low** | **High** |
| **3** | The charter's named "hidden-oracle bridge" `grade(record, oracle)` is a **12-LOC grader called only by tests**, plus `core.types.Oracle/Scores` (dead outside tests) — the real grade path uses a separate `EvalOracle`; the true benchmark:product ratio is **~1:1, not 8:1** | Reclassify `grade()`/`Oracle`/`Scores` as test **Fixture**; correct the ratio framing in the docs | Low | Med |
| **4** | The Core/Labs boundary is **documentary, not structural**: 13 arms, 4 harnesses, the KB, and the product share one package tree, one CLI, one composition root | **Compile** it (`product/` package + arm-registry + import-linter CI contract) — **but last**, after 1–3 | Med | Med |
| **5** | `CodeIndex` port wrong-shaped (match+localize fused → `_last_signals` stash + `SplitIndex`) | Document as a known smell; the clean fix is **blocked by the frozen-core invariant** | Low | Low |
| **6** | CBM is documented as a "Level-1 hard dependency load-bearing for matching and localization" (`architecture.md §5`) with **zero `[production]` evidence**; the default query path reads no vector | Demote the *framing* to "build-time symbol enumerator (swappable) + opt-in labs runtime graph"; **do not** drop the vectors table (schema has no version guard → full re-index) | Low | Low |
| **7** | The KB implementation governs an **empty store**, is off the run path, has produced **0 positive signal** (0/60 validated, 0.0 resolved in every fair arm); its Archived→Candidate relabel **launders an unvalidated null** | Relabel the *current implementation* **Dormant**; queue the redesign (§7 below); **do not delete** (fixeval hard-imports `kb/`) | Low | see §7 |

## 6. What refutation killed (disciplined aggression)

The review is stronger for admitting where the aggression was wrong. These claims were generated, then
**wounded fatally or materially** by a skeptic reading the actual code:

- **The pure "RADICAL FLOOR" amputation** (delete localize/fix/submit/bind + all non-Core arms + produce +
  CBM + embed + KB down to an ~850-LOC matcher). Scored **highest** on the design rubric (33/40) — and is
  **rejected as an action.** It deletes the exact `AtlasIndex.retrieve`/FTS5 path that earned a
  `[production]` localize read (7/10 file@5), and forfeits the falsification substrate that de-risked the one
  win. **Kept as the honest mental model, rejected as a plan.**
- **Splitting the benchmark into a sibling repo** (scored lowest, 23/40). It strands the affinity miner
  (`gloop mine-affinity`) in labs, so a standalone product silently degrades to the flood **0.10** floor; and
  it demotes the #1 oracle-blindness invariant from an in-tree cross-seam test (`test_invariants.py` runs the
  real loop against a hidden oracle and asserts `grade_run` is the sole reader) to cross-repo integration
  faith. **Co-location is a structural precondition, not a convenience.**
- **Deleting `ports.py`.** The Protocols *are* inert at runtime — but they are the cheapest published spec
  for the ~5 hand-copied oracle-blind loop replicas (`batch` + the eval/fixeval/fault/func runners that
  re-walk the loop rather than call `run_ticket`) and the
  roadmap's real Jira/Gerrit/vector adapters. Deleting a read-time architectural firewall to save lines no
  runtime path costs is a bad trade on a frozen core. **The inertness observation survives; the deletion does
  not.**
- **Splitting the `CodeIndex` port / collapsing IssueSource+ChangeSink** — breaches the frozen core and
  forfeits the JIRA↔Gerrit seam that *is* the charter's mission. Correct diagnosis, un-actionable.
- **Dropping the vectors table / gating embed off** — the atlas schema has **no version guard**, so this
  invalidates every existing atlas.db (including the 126,919-unit GEI production atlas) and forces the most
  expensive operation in the system (CBM ~1800s/repo, GPU bge-m3, one-index-at-a-time) to re-run. One-time
  disk saving < mandatory re-index of every atlas that produced every number the project has.
- **Downgrading the `[proxy]` apparatus to PASS/FAIL assertions.** Killed on all three lenses: the
  *comparative decimals* are load-bearing — same-substrate arm-ranking is exactly how the one production win
  was de-risked (component-routing `[proxy]` 0.32→0.49 correctly predicted `[production]` 0.50) and how
  `cascade_judge` was known to beat `rerank_cw_judge`. PASS/FAIL could not have produced any of the last two
  weeks of shipped decisions. **The one true residue:** never headline a `[proxy]` *absolute*, and note the
  synth construct-validity tautology (`synth/logs.py` assembles the crash log from the owning repo's own
  atlas rows, then the FTS5 matcher queries that same atlas — "does retrieval return a token copied out of the
  document it's retrieving") — already neutralized by the mandatory tag convention, kept as a footnote.

## 7. The KB — a weak first cut of the highest-ceiling concept

**The current KB implementation is Dormant and should be labeled so.** But the *concept* is not the null —
and the evidence for that is inside GroundLoop's own charter. Charter §7 is the strongest efficacy signal in
the whole project: cross-repo grounding surfaced knowledge an agent could not reach itself — **+40–60pp** on
non-guessable cross-repo helpers, roughly *capability-invariant* (no amount of reasoning conjures a repo the
model has never seen). **A KB is the productization of exactly that finding.** Killing the *concept* would be
killing the thing §7 names as the biggest measured lever.

What actually failed is the *implementation*, along three axes (the redesign roadmap):

1. **Injection mechanism is crude — a firehose, not a retriever.** Raw Skills dumped into the *localize
   query* polluted it (reproduced Δ−0.10 file@1); dumped wholesale into the *planner* prompt they **hurt**
   (`plan_target_recall@1` none 0.51 → raw-Skills 0.22). The redesign: retrieve *relevant* knowledge, at the
   *right stage* (fix, not the localize query — which is `file_recall`-invariant anyway), in a *bounded* form.
2. **Knowledge representation is wrong.** Distilling raw Skills into atomic "claims" validated **0/60** and
   throws away the §7 value. The unit should be richer — **worked crash-RCA playbooks, structured fix-patterns,
   cross-repo helper pointers** — and the ground-check gate is mis-tuned (0/60 is too lossy to be a filter;
   it's a wall).
3. **It never learns.** The store is static and hand-seeded; there is no `resolved fix → distilled knowledge
   → better next fix` loop. At fleet scale, the compounding feedback loop *is* the value; a static seed KB
   cannot compound.

**Disposition:** relabel the current implementation **Dormant** (not Archived — the null was never validly
measured; not Candidate — "Candidate = promising-but-unvalidated" launders a 0-signal capability). Keep it
in-tree (a dormant branch bit-rots against the churning eval substrate, and `fixeval/runner.py` hard-imports
`kb/`; the continuously-green in-tree tests *are* the future-readiness). **And queue the 3-axis redesign as a
first-class Phase-2 candidate** (§9, item 6) — this is a bet on the ceiling, not the cleanup.

## 8. The recommended target architecture

**A hybrid** — adopt the *honest mental model* of the RADICAL FLOOR (the shipped, `[production]`-validated
product is a **Stage-1 matcher + recall-localize**; fix is **real-but-unproven**; submit/bind are
**aspirational mock**) but **implement via the one-repo Product/Labs structural split** (the design the judge
panel scored 30/40, second only to the amputation-as-mental-model), sequenced **low-risk-first**:

- **Reject the external sibling repo** (23/40) — strands the affinity miner → silent degrade to 0.10, and
  fractures the oracle-blindness invariant enforcement across a repo boundary (§6).
- **Reject the pure amputation as an action** (33/40 on the rubric, but wounded on correctness) — it deletes
  a `[production]`-measured stage and the falsification substrate.
- **Adopt the one-repo compiled boundary** (30/40) — it converts the documentary Core/Labs line into a
  CI-enforced one **without** deleting the in-tree cross-seam invariant tests and **without** touching the
  frozen core. But it is **not step 1**: first externalize `produce` and pull the two real product→labs edges
  down (`GatewayModel → eval.cost.cost_of`; `batch → fixeval.patch`), then compile the boundary as the finish.

The end state: a `product/` package of exclusively `[production]`-path code (~3,500 LOC, independently
shippable, imports nothing experimental) + a `labs/` package (arms, harnesses, dormant KB) behind a registry
the run path cannot reach without opting in + an externalized `produce` build tool + honest docs.

## 9. Ranked Phase-2 menu

1. **Externalize `produce/`** to a standalone build utility. −65% of the product tree, **zero runtime-import
   loss**; strip the ~4,500 dead LOC even from the tool. *Lowest risk, highest value — the single most
   defensible cut.*
2. **Documentary rescope + fix `bound=True`.** Compute `bound` from a real binding or delete the field; stop
   citing it as `[production]` efficacy; **rescope charter + `capabilities.md` from "8-stage automated closed
   loop" to "validated Stage-1 match + recall-localize; unproven fix; mocked bind."** *(This is a
   documentary-integrity **mandate**, not a nicety — see §10.)*
3. **Reclassify the vestigial oracle bridge** (`grade()` + `Oracle`/`Scores`, ~26 LOC) as test-only Fixture;
   correct the benchmark:product ratio framing (~1:1).
4. **Fix two documentary defects:** the `capabilities.md` `0.68 [proxy]` citation that contradicts
   `environments.md`'s use of the same number as the canonical "proxy lies" cautionary tale; and relabel the
   KB **Dormant** + fix the one rotting default in `kb/attribute.py`.
5. **(Larger, last) Compile the Core/Labs boundary** in one repo: a `product/` package importing nothing
   experimental behind an arm-registry + an import-linter CI contract; first pull the two real cross-edges
   down. Only after 1–4.
6. **(First-class ceiling bet) The KB 3-axis redesign** (§7): retriever-style injection · richer Knowledge
   representation (playbooks / cross-repo helper pointers) · a loop-outcome learning loop. Its own
   spec→plan→implementation cycle; the productization of charter §7's +40–60pp lever.

## 10. The uncomfortable truth — and the headline mandate

> GroundLoop presents itself as a code-driven closed-loop bug-fixer across 130+ repos. By its own evidence
> it has shipped **exactly one thing to `[production]`: a Stage-1 repo matcher at recall@1 0.50 — wrong half
> the time, on n = 10 cases, from a GEI fleet the dev box cannot even reproduce.** 65% of the tree is a
> vendored doc generator the runtime imports zero lines of; the fix stage is 0/10 ungraded; submit/bind are
> always-mock and `bound=True` is a hardcoded literal that `capabilities.md` cites as `[production]` Core
> evidence. The dev box — **by the project's own governance** — is a *falsifier* that can never promote a
> single line to Core, and the empirical `[proxy]`→`[production]` transfer record for non-Core arms is
> **0-for-2** (functional-text 0.68→0.10 collapse; localize-dispatch inert 0/10 → Archived). The research
> apparatus is genuinely disciplined and defensible: it de-risked the one win and it caught the arms that
> failed. **Selling it as a delivered closed loop is not.**

**The mandate this review issues:** the charter and `capabilities.md` **must be rescoped** — the product's
honest name is *"a `[production]`-validated Stage-1 repo matcher (recall@1 0.50, n=10) + a recall-localize,
atop a rigorous research lab for the unsolved downstream (functional matching, rank-1 localize precision, fix
resolution, the JIRA↔commit chain)."* The three fixed invariants stay sacred. The 42-LOC oracle-blind core is
the crown jewel and is not to be touched. Everything else in §9 follows from telling the truth about what has
and has not been delivered.

---

### Appendix — method & grounding

- **Workflow:** `groundloop-first-principles-teardown` — 8 subsystem teardowns × 3 refuters + 3 designs × 4
  judges + synthesis (48 agents, ~2.8M tokens). Findings that a refuter wounded fatally/materially were
  demoted to §6.
- **Hand-verified citations:** `core/workflow.py:19-20` (no `oracle` param), `:33` (`retrieve` receives only
  `ticket.summary`), `:42` (`bound=True` literal); `capabilities.md:67` (`[proxy]` = mechanism/regression
  only, never Core), `:72` (the `bound`-as-`[production]`-evidence citation).
- **LOC map:** `groundloop/` 30,770 · `core/` 172 · `adapters/` 1,733 · `cli/__init__.py` 1,570 ·
  `engines/produce/` 19,914 (65%) · `engines/atlas/` 646 · KB `kb/` 1,022.
- **Fixed invariants (non-negotiable):** oracle-blindness · anti-leak contract · deterministic control flow.
