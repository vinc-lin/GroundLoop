# GroundLoop — Type-2 Honest-Refusal Negatives + Downstream Fix-Loop + Dev-Experience KB (Design)

> **Status:** Design v1 (2026-07-05). One comprehensive, **phased** spec covering three coupled
> sub-projects, built in order **SP1 → SP2 → SP3**. It **extends** the canonical
> [`type2-evaluation.md`](../../type2-evaluation.md) (Test 2) and
> [`downstream-fix-loop.md`](../../downstream-fix-loop.md); where this spec and those differ on the items
> below, this spec wins for the negative-case / fix-loop-eval / KB-arm surfaces. It does **not** edit
> `core/`; all behavior is swapped at the composition root (`cli/__init__.py`) per the hexagonal
> architecture.

---

## 0. The through-line (why these three are one plan)

The real problem GroundLoop automates is: **JIRA defect + failure logs → identify the owning repo among
130+ AAOS in-vehicle repos → localize → fix → JIRA↔commit bind.** In that real world, a large fraction of
inbound is *not* a clean, in-fleet, well-signalled defect: tickets are misfiled (not ours), the index is
stale (the fix lives in code we haven't indexed), the report is terse (under-determined), or it isn't a
defect at all. **A trustworthy system must answer honestly — abstain / route out — instead of fabricating
a repo match or a patch from hallucination.**

One thesis unifies the three sub-projects:

> **Honest refusal is only meaningful if (a) we *measure* it, and (b) the aids we add to improve
> fixing don't *erode* it.**

- **SP1** builds the **negative cases** and scores honest refusal at Stage-1 (match) — turning the
  audit's *designed-but-unwired* grounded-refusal machinery into a real number.
- **SP2** builds the **downstream fix/RCA loop + its eval surface**, so honest refusal can be graded
  end-to-end (don't fabricate a *patch*), and so fix quality is measurable at all.
- **SP3** builds the **dev-experience KB (Skills)** as a **measured arm** on SP2, with the explicit
  requirement that it must **help grounded fixing on positives without increasing hallucination on
  negatives.** SP1's negatives are what make SP3 honestly gradeable.

**Provenance:** motivated by the 2026-07-05 Type-2 audit, which found grounded refusal unwired
(`is_answerable` stripped, catalog global, `abstention_recall_oof` absent), the abstain policy
scale-broken across arms, and the downstream fix-loop entirely aspirational.

---

## 1. Phase SP1 — negative / honest-refusal cases (Stage-1 scored)

**Goal:** a dataset of realistic negative cases across four classes, oracle-blind, adversarially
surface-similar to positives, scored at Stage-1 (repo match) now, and **authored once** so the same cases
flow into SP2's whole-loop grading with no re-mining.

### 1.1 Taxonomy + scoring buckets

Every case carries a hidden typed label; scoring uses the Φ_c payoff (answered-correct `+1`,
answered-wrong `−c`, abstain per class). The classes split into two buckets by **whether refusing is the
ground-truth answer or merely the safe move on a solvable case.**

| Class | Reality | Honest answer | `is_answerable` | Abstain | Wrong guess |
|---|---|---|---|---|---|
| **out_of_fleet** | owner not in our estate | "not ours / route out" | `false` | **+1** | −c |
| **coverage_gap** | repo ours, code not indexed | "can't ground / needs re-index" | `false` | **+1** | −c |
| **not_a_defect** | feature/question/dupe/user-error | "not a code defect" | `false` | **+1** | −c |
| **insufficient_signal** | real in-fleet target, weak ticket | ideally still find it, else abstain | `true` | **0** | −c |
| *(positive)* | real in-fleet, good signal | name the repo | `true` | 0 | −c |

- **Bucket 1 (`is_answerable=false`) — refusal is ground truth:** `out_of_fleet`, `coverage_gap`,
  `not_a_defect`. Naming any repo is a fabrication (`−c`); abstaining is correct (`+1`).
- **Bucket 2 (`is_answerable=true`) — answerable-but-hard:** `insufficient_signal` (+ all positives).
  The target exists and is grounded in the index, so abstaining forgoes the `+1` (scores `0`) but avoids
  the `−c` wrong-guess penalty. This is where the risk-coverage curve earns its keep.

Two deliberate calls: **coverage_gap → Bucket 1** (an un-indexed match would be a name-guess = narrative,
not grounding; the distinct label lets SP3 later score the better "flag for re-index" action); and
**insufficient_signal → Bucket 2** (rewarding abstain here would reward *giving up* on a solvable case).

### 1.2 Sourcing per class

Backbone = **naturally-occurring** negatives; **controlled synthetic** for volume/balance/difficulty.
Two of four classes fall out of existing miner machinery.

| Class | Primary (realistic) | Supplement (controlled) | Reuses / needs |
|---|---|---|---|
| **out_of_fleet** | **Catalog hold-out** — a real answerable case with its owner removed from *that ticket's* catalog (adversarial by construction). | **Foreign-repo injection** — real issue→fix from an adjacent-domain repo not in the fleet; its own owner scrubbed so refusal must come from "no grounding," not spotting a foreign name. | Hold-out **needs a per-ticket catalog** (audit: catalog is global today). |
| **coverage_gap** | **Temporal (post-SHA)** — cases whose `expected_files` did **not** exist at the pinned `owning_repo_sha` = the *inverse of the positive admit-filter* (§4.2 requires they exist), so filter-rejects become negatives. | **Subtree-omission** — drop a subtree (e.g. `vendor/`) from the index and use a case that lands there. | Reuses the SHA-existence check, inverted. Mirrors real "stale index" — the most AAOS-realistic negative. |
| **insufficient_signal** | **Real prose-only** — the miner already buckets `BUCKET_PROSE_ONLY`; admit them (with their real linked fix as hidden oracle) instead of dropping. | **Signal-ablation** — strip discriminative signals from a positive, keep symptom prose + *some* weak in-fleet signal (still Bucket 2). | Reuses `BUCKET_PROSE_ONLY`. Models terse real JIRA. |
| **not_a_defect** | **Label-based harvest** — issues labeled `enhancement`/`question`/`duplicate`/`wontfix`/`invalid` (JIRA: type/resolution). No linked fix → no `expected_files`. | Pick ones that *sound* like bugs for adversarial similarity. | **New non-linked harvest path.** **Cap volume** (high-frequency but upstream of repo-matching). |

### 1.3 Schema + wiring

**Oracle/schema** (new keys ride *oracle-side* as extra keys the eval loader reads and the frozen
`core.types.Oracle` ignores — no `core/` edit, no SQLite schema bump):
- `_oracle/oracle.json`: `is_answerable` (bool), `negative_class` (`null`|the four), `held_out_repo` (OOF
  hold-out). `owning_repo` = real owner for coverage_gap/insufficient_signal; sentinel
  (`__OUT_OF_FLEET__`/`__NOT_A_DEFECT__`) otherwise.
- `provenance.json`: `source_method` (`hold_out`|`foreign_inject`|`temporal_gap`|`subtree_omission`|
  `prose_only`|`signal_ablation`|`label_harvest`), `nearest_confusable_repos`.

**Wiring changes** (audit Tier-0, each with a purpose):
1. **Un-strip `is_answerable`/`negative_class`** in the eval-side oracle loader (`_ORACLE_KEYS` drops them
   today) — read only by the eval layer.
2. **Per-ticket catalog** — `EvalRunner` fetches the catalog once (global); make it per-case so OOF
   hold-out can remove `held_out_repo`. *This is what makes hold-out possible.*
3. **`score_match` passes `is_answerable` + class** (hardcoded `True` today) → Φ_c gets the +1/0/−c
   branches from §1.1.
4. **Per-arm calibrated τ** (replaces the single global `tau_score`) — fixes the audit scale bug
   (semantic always-abstains / judge never-abstains). *Refusal must be reachable on every arm or negatives
   can't be scored on them.* τ calibrated on `calib`, frozen for test.
5. **Scorecard additions:** `abstention_recall_oof` (NoAns recall over `is_answerable=false`) + per-class
   breakdown. (Full AURC/AUGRC/RC-curve stays deferred to the audit's E1-C v2.)
6. **Leak red-test over mined negatives** — extend `tests/test_invariants.py` to run over `gloop mine`
   negative output (today only hand-authored fixtures): assert **opaque `case_id`**, no fleet-owner token
   survives, no `_oracle/` field is loop-visible. (Also fixes the audit's `case_id={repo}-{n}` BLOCKER.)

### 1.4 Volume, ratio, splits

- Target **answerable : unanswerable ≈ 1:1** overall (per canonical §4.1) so grounded refusal is
  well-powered; `insufficient_signal` counts answerable, the other three unanswerable.
- **Per-class caps** so no class dominates: OOF + coverage_gap are the unanswerable bulk;
  `not_a_defect ≤ ~10%` of total; `insufficient_signal` sized to populate the RC-curve mid-range.
- **`calib` carries the same class mix** (τ is calibrated there). `holdout-postcutoff` also carries
  negatives.
- These are **calibration knobs**, pinned against pilot volume; the aggregate clears `n≥128` for the
  selective metrics, thin per-class slices flagged directional-only.

### 1.5 SP1 deliverables & acceptance
- Miner emits the four negative classes (+ per-ticket catalog for hold-out); opaque `case_id`.
- Eval scores Stage-1 refusal via Φ_c + `abstention_recall_oof` + per-class breakdown; per-arm τ.
- Type-1 leak red-test passes over mined negatives.
- **Acceptance:** on a pilot dataset, the scorecard shows a real selective view where a grounded arm
  abstains on Bucket-1 (high `abstention_recall_oof`) and answers positives — and a degenerate
  always-answer arm is visibly punished by Φ_c.

---

## 2. Phase SP2 — downstream fix/RCA loop + eval surface

**Goal:** replace the `CannedFixEngine` stub with a real (thin) fix/RCA loop and a `gloop` eval surface,
so (a) fix quality is measurable and (b) SP1's negatives can be graded end-to-end (don't fabricate a
patch). Adapts `bfl`'s pipeline per the migrate-as-is convention; no `core/` edit.

### 2.1 Engine
- **Agentless-style, code-driven** loop on the LiteLLM gateway (`deepseek-chat`, model-portable via
  `KLOOP_*`): deterministic **localize** (candidate files/locations from the matched repo + signals) →
  **LLM propose-patch**. Bounded grounded refinement triggers only on **in-world deterministic signals**
  (`git apply --check` fails → re-run; cited location doesn't resolve → re-localize) — **never** the
  oracle.
- Exposed as a `FixEngine` port impl (`AgentFixEngine`) swapped at the composition root; `CannedFixEngine`
  stays the hermetic Type-1 substitute.

### 2.2 Eval surface
- A `gloop` analogue of `bfl {run, grade, board, compare}`: `run` → `RunRecord`; `grade` (offline, sole
  oracle read); `board` (per-run scoreboard); `compare --base --head` → `Δ` metrics + **`newly_solved` /
  `newly_broken`** (regressions named).
- Grading is a separate offline pass; the loop never sees the oracle (extends canonical §8.2/§9 to the
  fix stage).

### 2.3 Headline metric (AAOS reality: few runnable test suites)
- **Headline = `file_recall@1/@k`** (over `expected_files`) **+ `patch_applies`** (`git apply --check`
  clean) **+ `required_api_pass_rate`** (over oracle `required_apis`).
- **`resolved_rate` is advisory-only**, computed **only over the grounded-gradeable subset** (repos with
  runnable tests); test-execution `resolved` deferred (no per-repo build/test harness in scope).
- Cost first-class: `cost_per_bug`, `cost_per_solved`, tokens, p50/p95 latency.

### 2.4 Whole-loop refusal grading (SP1 ∩ SP2)
- SP1's negatives run match→localize→fix. Define **`fabrication_rate`** = fraction of **Bucket-1** cases
  where the loop produced a **confident non-empty patch** (or confidently named a repo) instead of
  abstaining. On Bucket-1: explicit "insufficient grounding" abstain `= +1`; a fabricated patch `= −c`.
- Honest-refusal Φ_c is thus measured **end-to-end**, not just at Stage-1 — the operational definition of
  "don't hallucinate a solution."

### 2.5 SP2 deliverables & acceptance
- `AgentFixEngine` + `gloop run/grade/board/compare` + the metrics above.
- SP1 negatives graded through the whole loop with `fabrication_rate`.
- **Acceptance:** the loop produces a real `file_recall`/`patch_applies` board on positives and a
  `fabrication_rate` on negatives; `compare` names `newly_solved`/`newly_broken` between two configs.

---

## 3. Phase SP3 — dev-experience KB (Skills) as a measured arm

**Goal:** a retrievable **development-experience KB** that aids RCA + fixing, wired as a **measured arm**
on SP2. The real Skills live in **another environment and arrive post-migration**; for now we stand up a
**mock registry seeded with *real* dev-experience data** to validate the arm, plus a **migration guide**.

### 3.1 Skill contract + `SkillRegistry` port
Extend the `bfl` primitive (`bfl/skills/base.py`):
```python
@dataclass(frozen=True)
class Skill:
    id: str
    applies_to: Callable[[ctx], bool]   # predicate on signal class / family / native / apis
    guidance: str                        # the playbook text (real dev experience)
    hint_apis: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()        # NEW: retrieval keys / tags
    provenance: str = ""                 # NEW: source (doc/commit), for KB traceability
```
- `SkillRegistry` port: `select(ctx) -> list[Skill]` = predicate filter **+ optional bge-m3 retrieval**
  over `guidance` (top-k, keyed on ticket signals). `render_skills()` injects them into the fix/RCA
  prompt as "# Applicable playbooks."
- Composition-root swap: `MockSkillRegistry` now → real registry post-migration. Reuse-contract: the KB
  embedder is pinned `bge-m3` (query == index).

### 3.2 `MockSkillRegistry` seeded with real data
- Seeded from the dev-experience we **do** have: real playbooks distilled from the findings/ops docs
  (e.g. the CBM operational rules, produce latency/giant-repo gotchas, AAOS native/`.so` RCA heuristics)
  and real fix patterns from git history. Stored as **data** (TOML/JSON) so real Skills swap in by
  replacing the data source, not code.
- "Mock" = the *registry wiring*; the *content* is real, so the arm measures a genuine (if small) effect.

### 3.3 Measured arm + the anti-hallucination through-line
- Arm axis: `skills ∈ {none, mock}` × the SP2 fix loop (`RunConfig.skills`, never a trusted input —
  "does injecting this help?" per `downstream-fix-loop.md:189`).
- **Two-sided acceptance (the unifying requirement):**
  - **Positives:** KB must improve `Δresolved`/`Δfile_recall@k` at **≤ `cost_per_solved`**.
  - **Negatives:** KB must **not** degrade honesty — `abstention_recall_oof` must not drop and
    `fabrication_rate` on Bucket-1 must not rise. (A KB that makes the model *more confidently wrong* on
    OOF is a regression, caught here.)

### 3.4 Migration guide (deliverable)
A `docs/` guide covering: (a) the `Skill` contract the real Skills must conform to; (b) the
extraction/transform from the other environment's format → `Skill` records (+ `provenance`); (c) the
composition-root swap (`MockSkillRegistry` → real); (d) a **parity self-test** — the migrated registry
reproduces the mock arm's behavior on a fixture, so migration is verifiable.

### 3.5 SP3 deliverables & acceptance
- `Skill`/`SkillRegistry` contract + `MockSkillRegistry` (real-data-seeded) + bge-m3 retrieval + inject
  seam; the `skills` arm in SP2's eval; the migration guide + parity self-test.
- **Acceptance:** the scorecard shows the KB arm's effect on both positives (fix quality/cost) and
  negatives (honesty), and the migration guide + parity test let a real Skill set drop in unchanged.

---

## 4. Build order, dependencies, guardrails

- **Order:** SP1 → SP2 → SP3. SP1 is independently useful (ships the first honest-refusal number over
  Type-2 today). SP2 depends on SP1's dataset labels. SP3 depends on SP2's fix loop + eval to inject into
  and be graded against.
- **Oracle-blindness (cross-cutting, extends canonical §9):** negatives' typed label + provenance are
  hidden oracle-side; opaque `case_id`; every injected/harvested negative passes the same leak-scrubber;
  the fix loop and the KB registry never read `_oracle/`; grading is the sole offline oracle read.
- **Frozen core / reuse contract:** no `core/` edits; no SQLite schema change; embedders pinned `bge-m3`
  (query == index) for the semantic and KB-retrieval paths.
- **Two test surfaces:** membership/metric/mock paths are Type-1 hermetic; the live fix loop + real
  embed/judge/KB retrieval are Type-2 gated (`skipif` on `KLOOP_*`).

## 5. Risks & open questions
- **Adversarial similarity** of negatives — a trivially separable negative tests nothing; hold-out and
  temporal-gap are adversarial by construction, foreign-injection and not_a_defect need deliberate
  similarity selection.
- **`not_a_defect` is upstream of repo-matching** — a real system may pre-classify; keep it capped and
  treat its metric as routing-signal, not core Stage-1.
- **Mock-KB representativeness** — the mock's real-data seed is small; the arm validates *plumbing +
  direction of effect*, not the full lift the migrated Skills will show. Flagged, not hidden.
- **`resolved_rate` coverage** — advisory-only until a per-repo test harness exists; `file_recall` +
  `patch_applies` carry the headline meanwhile.
- **Cost of the live fix loop** — DeepSeek-latency-bound; run on a capped pilot subset, snapshot outputs.

## 6. Relationship to existing docs
Extends [`type2-evaluation.md`](../../type2-evaluation.md) (Test 2 canonical: fleet, dataset, arms,
scorecard) and [`downstream-fix-loop.md`](../../downstream-fix-loop.md) (fix-loop provenance, the
skills-as-measured-arm seam). Corrects/implements the 2026-07-05 audit's grounded-refusal, abstain-scale,
and fix-loop gaps. Milestone naming stays namespaced (not a bare "M1"); this is a Type-2 extension track,
sequenced SP1→SP2→SP3.
