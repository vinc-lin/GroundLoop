# Plan-Format Fix Stage — Design Spec

**Date:** 2026-07-07
**Status:** Design (awaiting review) → to be turned into an implementation plan via `superpowers:writing-plans`.
**Author:** GroundLoop (brainstormed with the user, 2026-07-07)

---

## 1. Motivation

The fix stage is the weakest link in the loop, and grounding the reasons (see the
2026-07-07 fix/localize grounding pass) exposed three concrete defects:

1. **Context starvation.** `ModelPatchEngine._snippet` feeds the model the *first 40 lines from the top*
   of each candidate file (`adapters/fix/model_patch.py`), not the fault site. The model usually
   cannot see the defect it is asked to patch.
2. **A game-able resolution proxy.** `resolved` (`fixeval/scorecard.py`) = `git apply --check` passes
   `∧ file_recall@1>0` (on **localize's** locations, not the patch's) `∧ every required_api appears as a
   whole word on a `+` line` (a name-drop in a comment counts). There is no compile/test oracle.
3. **A no-op self-repair loop.** The refine loop re-calls `propose` with identical args at
   `temperature=0`, so the retry is byte-identical (`fixeval/runner.py`).

Separately, the **Skills KB** is wired into the fix stage only as a raw prose *preamble* prepended to the
propose-patch prompt, and its effectiveness is unmeasured (all 12 Skills are `candidate` tier).

**This design turns the fix stage into a two-phase, plan-then-act engine.** A structured *repair plan*
becomes an explicit, grounded, gradeable artifact between localize and patch. It is the single vehicle
that (a) de-starves the patch call, (b) gives fix a **non-game-able** signal, (c) adds a real
**self-repair + honest-refusal** loop, and (d) becomes the natural, structured home for KB knowledge and
the future case-memory corpus — unifying the fix-strengthening and KB threads.

## 2. Core principle it must honor

GroundLoop's north star is **"grounding over narrative": distrust unverifiable LLM prose.** A "plan" is,
by default, exactly that prose. Therefore the load-bearing rule of this design:

> **The plan is not narrative. It is a structured artifact in which every claim cites reality and is
> checkable against reality** — the files/symbols/APIs it names must exist in the materialized worktree
> and the atlas, and its groundedness is scored **offline, without the oracle**. Get this right and the
> plan is a *grounding surface*; get it wrong and it is the narrative we are built to distrust.

## 3. Goals / non-goals

**Goals**
- A `PlanningFixEngine` that emits a structured `RepairPlan`, gates it in-world, re-plans or abstains on
  failure, then executes the *validated* plan into a patch.
- A new **measured arm** `--fixer {direct, plan}` so plan-then-act is *proven* against today's direct
  patch, not assumed. Composes with `--skills`.
- A new grader tier (`plan_groundedness`, `plan_correctness`) that does not ride on `resolved_rate`.
- Harden the `resolved_rate` proxy so both this arm and the KB retain-loop sit on honest ground.
- Archive every plan + outcome from day one.

**Non-goals (this effort)**
- Symbol-level / line-level plan targets (schema leaves room; deferred).
- Structured field-injection of KB Skills into plan fields (MVP carries KB as prompt context).
- *Using* the archive (retrieval / regression anchor / distill feedstock) — capture only.
- A real compile/test (Tier-3) resolution oracle — still out of scope; `resolved_rate` stays a
  *hardened* proxy, not ground truth.
- Any change to `groundloop/core/` or the atlas SQLite schema.

## 4. Locked design decisions (from the brainstorm)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Plan's role | **Grounded scaffold**: conditions the patch **and** is scored offline **and** archived from day one |
| D2 | In-loop checkpoint | **Gate → bounded re-plan → abstain** (in-world signals only, never the oracle) |
| D3 | Target granularity | **File-level, `symbol` optional** (runs on localize as-is; grows later, no schema break) |
| D4 | Scope | Include **`resolved_rate` hardening** (Phase 0); skip the standalone scored-localize view (subsumed by `plan_correctness`) |
| D5 | Delivery discipline | Ship as a **measured arm** (`--fixer plan`) with `max_replan=1` default; KB carried into the plan prompt |

## 5. Architecture

### 5.1 Two-phase engine, `core/` untouched

The frozen port is `FixEngine.propose(worktree, ticket, locations) -> Patch` (`core/ports.py`). The new
`PlanningFixEngine` (in `adapters/fix/planning.py`) **satisfies that port unchanged** and adds a
plan-aware method that the (non-frozen) eval runner uses to capture the plan:

```python
class PlanningFixEngine:  # implements FixEngine
    def __init__(self, model, *, resolver=None, preamble="",
                 max_replan=1, context_window=120):
        # resolver: optional CodeIndex for symbol/API existence checks (file checks are filesystem)
        ...

    def propose(self, worktree, ticket, locations) -> Patch:
        plan, patch = self.propose_with_plan(worktree, ticket, locations)
        return patch                          # frozen-port path (production run_ticket)

    def propose_with_plan(self, worktree, ticket, locations) -> tuple[RepairPlan | None, Patch]:
        plan = self._plan(worktree, ticket, locations)          # model call #1
        for _ in range(self.max_replan + 1):
            failures = check_plan_in_world(plan, worktree, self.resolver)  # oracle-blind gate
            if not failures:
                break
            plan = self._replan(worktree, ticket, locations, plan, failures)  # grounded feedback
        else:
            return plan, Patch(diff="", files=())               # abstain = honest refusal
        if plan is None or plan.abstain:
            return plan, Patch(diff="", files=())
        patch = self._execute(worktree, ticket, plan)           # model call #2, fault-site context
        return plan, patch

    def with_preamble(self, preamble) -> "PlanningFixEngine":   # mirror ModelPatchEngine, share model
        ...
```

- **Production** (`run_ticket`) calls the frozen `propose` and gets a `Patch`; the plan is emitted as a
  side artifact via the same mechanism as `fix.patch` (a `plan.json` written next to it). `run_ticket`
  is unchanged.
- **Eval** (`fixeval/runner.py`, not frozen) calls `propose_with_plan` when the fixer exposes it, so the
  `RepairPlan` is captured for grading + archiving. Runner stays backward-compatible with the plain
  `ModelPatchEngine` (which only has `propose`).
- The re-plan/abstain loop lives **inside the engine**, so production self-repairs too — not just the eval.
- `Patch` is a core type and is **not** modified; the plan travels via `propose_with_plan`, never by
  extending `Patch`.

### 5.2 `RepairPlan` schema (file-level, symbol optional)

```python
@dataclass(frozen=True)
class PlanTarget:
    file: str            # repo-relative path; MUST exist in the worktree
    symbol: str | None   # optional; if present, checked + used to anchor the fault-site window
    why: str             # one-line grounded reason this file changes

@dataclass(frozen=True)
class RepairPlan:
    root_cause: str            # what & where, grounded
    targets: list[PlanTarget]  # files to change (⊆ localize candidates ∪ dependency-adjacent)
    required_apis: list[str]   # APIs/symbols the fix must use (feeds Tier-1.5 + resolution)
    strategy: str              # the change approach
    citations: list[str]       # the localize evidence each claim rests on (files/units from `locations`)
    risks: str = ""            # what could break (seeds future validation + archive)
    confidence: float = 0.0
    abstain: bool = False      # the model may declare it cannot ground a fix
```

The model is prompted to emit this as JSON; a tolerant parser (reuse the fenced-block extraction pattern
from `patch.py`) decodes it. A parse failure is treated as a gate failure (→ re-plan, then abstain).

### 5.3 In-world gate (`check_plan_in_world`, oracle-blind)

Returns a list of specific failures; empty = pass. **None of these reads the oracle.**

1. Every `target.file` exists in the materialized worktree (filesystem check).
2. Every non-null `target.symbol` and every `required_api` resolves via the `resolver` (atlas symbol
   index) **or** appears textually in a target file. Unresolvable ⇒ hallucination.
3. `targets ⊆ localize candidates ∪ their dependency-adjacent files` — bounds hallucinated scope. (MVP:
   the candidate set is `locations`; "dependency-adjacent" is a deferred widening.)
4. `root_cause` and `strategy` are non-empty; `targets` non-empty (unless `abstain`).

Failures are fed back verbatim into `_replan` ("these citations do not resolve: …"), a **grounded,
in-world error signal** — the provenance-blessed self-repair trigger (`docs/downstream-fix-loop.md §4`).
After `max_replan` failed attempts the engine returns an **empty patch = abstain**, which the runner
already treats as a non-answer (no fabrication).

### 5.4 Fault-site context for the patch call (partial context-starvation fix)

`_execute` replaces the 40-lines-from-top snippet with a **best-effort fault-site window**, honest to the
file-level grain:
- If a `target.symbol` is present: locate it textually in `target.file` and window `±context_window`
  lines around it.
- Else: window around the strongest localize evidence for that file, or provide a larger/chunked slice
  than 40-from-top.

Full line-anchored windowing needs symbol/line grain from localize (the atlas *has* symbol units;
`retrieve` drops them) and is deferred with the symbol-level target work. The MVP is a real improvement,
not the final form — stated plainly so we do not over-claim.

### 5.5 KB absorption (MVP)

The existing `MockSkillRegistry.select → render_skills` path (`fixeval/runner.py`) is unchanged, but the
resulting guidance preamble is carried into the **plan** prompt (`_plan`) instead of the patch prompt —
so the KB genuinely informs the plan. The plan records which Skill ids fired (`fired_skills`, stored in
the archive, not the frozen `RepairPlan`) for later retain-loop attribution. Mapping Skill
`Localize:`/`Fix:` clauses into structured plan *fields* is deferred.

### 5.6 Composition-root wiring

`groundloop/cli/__init__.py` gains `--fixer {direct, plan}` (default `direct`) on `fixeval` (and
`kb-ab`). `_run_fixeval` builds `PlanningFixEngine` when `--fixer plan`, injecting the `GatewayModel`,
the atlas `resolver`, and (as today) the env-driven embedder for skill rerank. Everything else in the
runner is arm-agnostic.

## 6. Grader tier (Phase 2)

Two new metrics in `fixeval/scorecard.py`, computed over cases that carry a plan:

- **`plan_groundedness`** — fraction of the plan's citations (target files, symbols, `required_apis`)
  that resolve **in-world**. Oracle-blind ⇒ runs even in Type-1 against a fixture repo. Measures "did the
  model hallucinate?"
- **`plan_correctness`** — the offline oracle pass:
  - `target_recall@k` = recall of `plan.targets[].file` vs `expected_files` (the plan's own targets, not
    localize's `locations`).
  - `api_match` = fraction of oracle `required_apis` named in `plan.required_apis`.

These give the fix stage a signal grounded in *the plan's* correctness, independent of the game-able
`resolved_rate`. Reported alongside the existing `resolved_rate`/`patch_apply_rate`/`fabrication_rate` so
we can see, per arm, whether planning improves the grounded signal even where the proxy is noisy.

## 7. `resolved_rate` hardening (Phase 0)

Small, independent, done first so every downstream number is honest. In `fixeval/scorecard.py` /
`fixeval/patch.py`:

1. **Bind the file term to the patch's own edits.** Replace `_file_recall(rec.locations, …)` in the
   `resolved` predicate with a check over the patch's own touched files (`touched_files(rec.patch_diff)`)
   ∩ `expected_files`. A patch that edits the wrong file no longer scores file-correct because localize
   surfaced the right one.
2. **Require APIs on non-comment added lines.** `references_api` must match on `+` lines excluding
   comment lines (`//`, `/* */`, `#`, `*` continuations). A name-drop in a comment no longer satisfies
   resolution.

Because this changes the `resolved` definition, the current-proxy baseline (from the in-flight live run)
is snapshotted first, and the hardened metric ships as a **clearly labeled variant** so historical
numbers stay interpretable. (`resolved_rate` remains advisory — this hardens a proxy, it does not make it
ground truth.)

## 8. Archive (capture only)

Every eval case persists `plan.json` = `{RepairPlan, fired_skills, outcome}` where `outcome` =
`{gated: bool, replans: int, abstained: bool, patch_applied: bool, resolved: bool}`, keyed by case id,
under the run's out dir. Schema is versioned. *How* we consume it later (case retrieval, regression
anchor, distill feedstock) is a separate future design.

## 9. Data flow (end-to-end, eval)

```
case → match+decide (abstain gate) → materialize @base
     → localize (retrieve top-k files)                     [unchanged]
     → propose_with_plan:
          _plan(ticket, locations, KB-preamble)  ── model call #1 → RepairPlan(JSON)
          check_plan_in_world (worktree + atlas) ── oracle-blind
              fail → _replan(failures)  (≤ max_replan)  → recheck
              still fail → abstain (empty Patch)
          _execute(validated plan, fault-site window) ── model call #2 → unified diff
     → patch_applies (git apply --check)                   [unchanged]
     → archive plan.json + outcome
offline grade (separate pass, sees oracle):
     plan_groundedness (oracle-blind) · plan_correctness (target_recall@k, api_match)
     · hardened resolved_rate · patch_apply_rate · fabrication_rate
```

## 10. Error handling / edge cases

- **Plan JSON unparsable** → gate failure → re-plan → abstain. Never crash the case.
- **Model returns empty** (gateway swallows errors to `""`) → treated as abstain, cost still counted.
- **`abstain:true` from the model** → empty patch, no execute call (cost saved), counts as honest refusal;
  on an unanswerable (Bucket-1) case this is the *correct* behavior and must not raise `fabrication_rate`.
- **Re-plan makes it worse** (fewer valid citations) → still bounded by `max_replan`, then abstain.
- **`--fixer plan` with a non-plan-aware runner path** → runner falls back to `propose` (patch only, no
  plan captured); grader skips plan metrics for that case.
- **No `resolver`/atlas** (hermetic) → symbol/API checks degrade to textual-in-file only; file checks
  still hold.

## 11. Testing strategy

**Type-1 (hermetic, every change):**
- `check_plan_in_world`: unit tests for each failure class (missing file, unresolvable symbol/api,
  out-of-scope target, empty fields) over a fixture worktree.
- `PlanningFixEngine` with a scripted `CannedModel`: plan→gate→execute happy path; hallucinated citation
  → re-plan → success; persistent hallucination → abstain (empty patch); `abstain:true` short-circuit.
- `plan_groundedness` on a fixture (oracle-blind) — a hallucinated-citation plan scores < 1.0.
- `plan_correctness` target_recall/api_match against a fixture oracle.
- Hardened `resolved_rate`: a patch editing the wrong file, and an API only in a comment, both now score
  *unresolved* (regression tests locking the tightened predicate).
- `--fixer` arm selection + arm composition with `--skills`.

**Type-2 (live, gated):**
- `--fixer direct` vs `--fixer plan` A/B on the 278-subset with negatives: report Δ`plan_correctness`,
  Δ hardened `resolved_rate`, Δ`fabrication_rate`, Δcost, abstain rate. Planning is adopted only if it
  beats direct on the grounded signal per cost (the roadmap §6 arm discipline).

## 12. Invariants preserved

- **`core/` frozen** — `PlanningFixEngine` satisfies `FixEngine.propose` unchanged; the plan-aware method
  lives on the adapter and is used only by the non-frozen eval runner. `Patch` and `run_ticket` untouched.
- **Loop never sees the oracle** — the gate/re-plan use only in-world signals; `plan_correctness` is an
  offline grade pass. Abstain-on-ungrounded is honest refusal, not oracle peeking.
- **Atlas SQLite schema unchanged**; **bge-m3 embed pin** unchanged (only reused for the existing skill
  rerank / resolver).
- Behavior swapped only at the composition root (`cli/__init__.py`).

## 13. Phasing

- **Phase 0** — Harden `resolved_rate` (touched_files + non-comment API). Snapshot the current-proxy
  baseline; ship the hardened metric as a labeled variant.
- **Phase 1** — `PlanningFixEngine` + `RepairPlan` + `check_plan_in_world` + re-plan/abstain + fault-site
  window + `--fixer plan` arm.
- **Phase 2** — `plan_groundedness` + `plan_correctness` grader in the scorecard; archive capture.
- **Phase 3 (deferred, not this plan)** — structured KB field-injection; symbol/line-level targets +
  localize line spans; archive *use* (retrieval / regression / distill).

## 14. Open questions (for the reviewer)

1. `max_replan` default of **1** (plan → one re-plan → abstain) — acceptable cost/quality tradeoff, or
   start at 0 (gate → abstain, no loop) for the very first measurement?
2. `context_window` default (**±120 lines** around the symbol/evidence) — reasonable, or tune to a token
   budget?
3. Should Phase 0's hardened `resolved_rate` **replace** the old predicate outright, or run **both**
   (old + hardened) side-by-side for one release to preserve comparability? (Spec currently: labeled
   variant, both reported.)

## 15. Risks

- **Cost.** Planning is ~2–3× model calls/case; the arm is opt-in and abstention is free, but a large
  live A/B is more expensive than the direct arm. Mitigate with the subset + `--cost-budget`.
- **Grounded-but-wrong.** The gate proves citations are *real*, not *correct*; `plan_correctness`
  (offline) is what catches real-but-wrong targets. The two are complementary and both are reported.
- **Over-abstention.** A too-strict gate could turn answerable cases into refusals; watched via the
  abstain rate on answerable cases in the A/B.
- **Partial context fix.** File-level grain limits the fault-site window; full fix is gated on the
  deferred symbol/line work. Not over-claimed.
