# Capability Registry & Governance — Production Core + Dev Labs

> **What this doc is.** The single place that says, for every capability GroundLoop has built, *whether it
> is part of the production system or research scaffolding*, and *why* (grounded in real evidence, not
> intent). It exists so nobody — human or agent — mistakes an experiment for the product. Read
> [`environments.md`](environments.md) first for the dev-proxy ↔ production split and the `[proxy]` /
> `[production]` tag convention this registry depends on.
>
> Seeded 2026-07-12 from an evidence-graded classification of the whole tree (parallel readers over every
> subsystem → strict state assignment → adversarial verification of each Core/Archived verdict).

## 1. The model

**Production is responsible for stable delivery. Dev is responsible for exploring possibilities.
Research may expand freely, but Production must continuously converge.**

- **Production Core** = the *smallest* system validated on **real production data** (the 19-repo GEI atlas +
  the JIRA↔Gerrit oracle), reliably deliverable and long-term maintainable. It contains **only** the modules
  the core business workflow needs (the 8-stage `run_ticket` loop: intake → extract → match → materialize →
  localize → fix → submit → bind). Deterministic, stable interfaces, traceable, reversible. Experimental
  strategies, alternative algorithms, and research branches **must not** sit on the production path.
- **Dev Labs** = an independent research/validation space. It may be complex — many matchers, retrieval
  strategies, KB experiments, synthetic datasets, experimental commands — but it stays **isolated** from
  Production: no new production dependencies, no `core/` interface changes, **no change to default production
  behavior**.
- **Promotion rule.** A capability enters Production only after it **consistently outperforms the current
  solution on real production data** and passes stability + cost + regression gates. Promotion is a
  deliberate act recorded here, not a side effect of merging code.

## 2. Capability states

The three governance states are **Core / Candidate / Archived**. The evidence forces two additional
*permanent-role* states that don't sit on the promote→archive axis (they are never "promoted" and never
"fail"): **Dev-Labs Infra** and **Fixture**.

| State | Meaning | Default-on in the production path? |
|---|---|---|
| **Core** | Validated on real production data **and** the wired default of `run_ticket`. | Yes — by definition. |
| **Candidate** | Under evaluation in Dev; not yet approved. Includes proxy-only-validated and promising-but-unvalidated. | No — opt-in only. |
| **Dev-Labs Infra** | Permanent measurement / data apparatus (the machinery that *enforces* promote-on-evidence). Never promoted into the loop. | N/A — not part of the loop. |
| **Fixture** | Permanent hermetic Type-1 doubles (mocks, canned stubs). Exist only for tests. | **Never** — must be selected explicitly, never defaulted. |
| **Archived** | A **measured** null/rejected verdict, or abandoned investment. Kept only as a research record. | No. |

The distinction that matters most: **Candidate vs Fixture.** An untested stub is *not* a Candidate for
promotion — it is a Fixture that must never be default-on. Conflating them is how a hermetic toy ends up on
the production path (see §4).

## 3. The registry

Evidence tags follow [`environments.md`](environments.md): `[production]` = a real-data efficacy read (the
only kind that qualifies for Core); `[proxy]` = the OSS-9-repo dev box (mechanism/regression only).

### Core — production-validated and default-on (5)
| Capability | Evidence |
|---|---|
| `gloop run` — the frozen 8-stage `run_ticket` loop (`core/workflow.py`) | 2026-07-11 GEI run executed all 8 stages to a bound change on 10/10 cases, 0 crashes `[production]`. |
| `AtlasIndex` — FTS5 `rank_repos` (the `flood` base) **and** `retrieve` (the localize) (`adapters/index/atlas.py`) | Base substrate every arm wraps; `retrieve` = plain FTS5 keyword search scored **7/10 file@5** `[production]`. |
| Composition-root wiring (`cli/__init__.py` `main`) | The sole `gloop run` composition root; carried the `[production]` run. |
| `RecordingEstate` (`adapters/estate.py`) | Deterministic materialize-outcome decorator on the batch path; recorded the `[production]` fix-gradeability signal. |
| `gloop index` (atlas build) | Built the exact 19-repo / 126,919-unit GEI atlas the `[production]` run matched against. |

### Core-when-configured — production-validated, engaged when their artifact/flags are supplied
These have real `[production]` validation. **§4 re-points the default *selection*** so a correctly-configured
production run uses them by default. One honest caveat: `component` is now the default *arm*, but the affinity
**prior** additionally needs a mined artifact (`--affinity` / `KLOOP_AFFINITY`); with no artifact the match
stage falls back — loudly, and recorded honestly as `flood` — to the baseline (~0.10). The re-point points the
defaults at the validated components; it does not fabricate the affinity lever out of thin air.
| Capability | Evidence | Engaged when |
|---|---|---|
| **Component→repo affinity arm** (`ComponentPriorIndex`, RRF-fused) | The dominant Stage-1 lever: recall@1 **0.10 → 0.50** `[production]`. | default arm is now `component`; the prior engages with `--affinity`/`KLOOP_AFFINITY`, else an honest flood fallback. |
| **RRF fusion** (K=60) | The RRF form (not additive-raw) lands the 0.50/0.90 `[production]` shape. | the component prior engages. |
| **`ModelPatchEngine`** (real fixer) + `GatewayModel` | Ran in the `[production]` loop; fix ungradeable only for lack of worktrees. | `--fixer model` — now the default (fail-closed without creds / `--repos`). |
| **`CheckoutEstate`** (real owner-repo checkout) | The materializer that makes `git apply --check` meaningful. | `--repos` given (required with `--fixer model`). |

The **affinity miner** `gloop mine-affinity` is the *offline build step* that produces that artifact — a
production build step feeding Core, like `gloop index`; it is **not** a `run_ticket` stage and the re-point
does not touch it.

### Candidate — Dev-Labs research, blocked on a first `[production]` read (6)
`FaultRoutingIndex` / log-match v2 (routing 0.94 `[proxy]`) · functional/dispatch arm (0.68 `[proxy]`) ·
`SemanticAtlasIndex` (bge-m3 vector) · `LLMJudgeIndex` · `PlanningFixEngine` (plan-then-act, merged, live
A/B pending) · the bge-m3+qwen **localize** retrieve (eval-only; the "fancy" localize the production run did
**not** use).

### Dev-Labs Infra — permanent measurement / data apparatus (never promoted)
`eval` · `fixeval` · `funceval` · `faulteval` · `compare` · `grade-run` (the production **feedback**
scorecard) · `synth` · `mine` · `combine-oracle` / `label-bugkind` · `build-atlas` · `doctor` ·
`GitFixtureEstate`. This is the machinery that *enforces* the promotion rule — it stays in Dev Labs by design.

### Fixture — permanent hermetic Type-1 doubles (must be explicit, never default)
`CannedFixEngine` · `MockEstate` · `MockJira` · `MockGerrit` · `CannedModel` · `TokenIndex` (M0 stub) ·
legacy `grade()`. **The trap that §4 closes: several of these were the production *defaults*.**

### Archived — measured NULL, stop investing (the KB track)
The entire dev-experience KB line concluded on a hard, twice-reproduced null:
- Raw 12-Skill injection **hurt** the planner: plan_target_recall@1 0.36 → 0.22 (Δ **−0.14**) `[proxy]`.
- Claim-centric distill + LOFO retain-loop validated **0 / 60** claims `[proxy]`; no-injection 0.51 >
  placebo 0.37 > raw Skills 0.22.
- Machinery kept as record only: `kb-ab` / `kb-promote` / `kb-distill` / `kb-extract` / `kb-attribute`,
  placebo + distilled arms, `MockSkillRegistry`.

The mechanism works; it produced zero load-bearing knowledge. This *vindicates* the "grounding over
narrative / distrust-unverified" principle — and is exactly what Archived is for.

## 4. Enforcement — defaults must be Core, Fixtures must be explicit

The single biggest finding of the classification: **the default `gloop run` was a hermetic toy end-to-end**
— canned fixer → empty worktree → mock JIRA → mock Gerrit → `flood` matcher. Every production-validated
capability was opt-in; the one real production run only worked because it hand-overrode ~4 defaults. That is
the "too complicated to be realistic" gap, and it is small to close.

**Re-pointed 2026-07-12 (`cli/__init__.py`, composition root only — no `core/` edit):**
- **Match** default `flood` → **`component`**: resolves the affinity artifact from `--affinity` or
  `KLOOP_AFFINITY`; engages the validated prior when present, else **loudly** falls back to the flood
  baseline (honest degrade — a weaker but real matcher, unlike a garbage-producing one).
- **Fixer** default `canned` → **`model`** (`ModelPatchEngine`).
- **Fail-closed** on the production path: `--fixer model` **errors** if `KLOOP_PRODUCE_API_KEY` is unset
  (no more silent `CannedModel` degrade) **or** if `--repos` is missing (a real fixer over empty worktrees
  fabricates paths — the 2026-07-11 fix-0/10 lesson, now enforced).
- Fixtures are now selected **explicitly**: hermetic Type-1 runs pass `--fixer canned`; the single-case
  `--case` path remains a labelled hermetic demo (production uses batch `--out`).

**Remaining gaps to a fully real Core (net-new builds, not re-points):**
- **`MockJira` → a live JIRA REST `IssueSource`** (fetch + `post_comment`/`transition` write-back).
- **`MockGerrit` → a live Gerrit `ChangeSink`** (real change + a verifiable JIRA↔commit binding).

Until those land, the loop's central promise — a **traceable JIRA↔commit chain** — is still mocked at the
intake/submit/bind ends, even though the default *selection* for match → localize → fix now points at the
validated components (the affinity prior engaged whenever its artifact is configured, else an honest flood fallback).

## 5. Keeping this registry honest

- A capability's state changes **only** on evidence: a `[production]` read promotes Candidate → Core; a
  measured null moves it → Archived. Record the move here with its evidence line in
  [`results-log.md`](results-log.md).
- Never let a Fixture become a default (CI/regression should assert the production defaults are Core-aligned).
- When in doubt between Candidate and Fixture: *is anyone trying to promote it?* If no, it's a Fixture.
