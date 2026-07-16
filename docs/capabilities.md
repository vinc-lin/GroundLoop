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

The governance states on the promote→archive axis are **Core / Provisional-Core / Candidate / Archived**.
The evidence forces two additional *permanent-role* states that don't sit on that axis (they are never
"promoted" and never "fail"): **Dev-Labs Infra** and **Fixture**.

| State | Meaning | Default-on in the production path? |
|---|---|---|
| **Core** | Validated on real production data **and** the wired default of `run_ticket`. | Yes — by definition. |
| **Provisional-Core** | Made the production **default** on a *fail-safe* mechanism + a charter-aligned safety argument, **before** a `[production]` *effectiveness* read exists. Bounded: it resolves to Core or reverts. | Yes — default-on, but *effectiveness* is production-gated. |
| **Candidate** | Under evaluation in Dev; not yet approved. Includes proxy-only-validated and promising-but-unvalidated. | No — opt-in only. |
| **Dev-Labs Infra** | Permanent measurement / data apparatus (the machinery that *enforces* promote-on-evidence). Never promoted into the loop. | N/A — not part of the loop. |
| **Fixture** | Permanent hermetic Type-1 doubles (mocks, canned stubs). Exist only for tests. | **Never** — must be selected explicitly, never defaulted. |
| **Archived** | A **measured** null/rejected verdict, or abandoned investment. Kept only as a research record. | No. |

**Provisional-Core (added 2026-07-13)** is a *named exception* to the promote-on-real-data rule — not a
relaxation of it. It exists because some capabilities are **fail-safe**: their worst-case failure is an honest
*abstain*, never a wrong or fabricated output. For such a capability, defaulting it on is itself a
charter-aligned ("grounding over narrative") improvement even before its *effectiveness* is measured on real
data. Admission requires **all** of: (1) a **fail-safe mechanism** — worst case is an abstain, never a
confident-wrong result (a capability whose failure is a wrong output — e.g. an unvalidated aggressive
re-ranker — is **not** eligible; it stays Candidate); (2) a **charter-aligned justification** and/or positive
`[proxy]` evidence; (3) a **named, scheduled `[production]` read** that will resolve it. Obligations that keep
it from becoming a loophole: it is recorded default-on but explicitly "effectiveness production-gated"; it
**resolves on the next instrumented `[production]` run** (→ Core if the bar is met, → Candidate / prior default
if not); it is **bounded / fail-closed on governance debt** (if the read hasn't happened by the next
production cycle it reverts to the prior safe default); and the prior default stays selectable as a reversible
opt-out. The **effectiveness** claim still requires a real-data read — Provisional-Core only front-loads the
*safety* half of the promotion on a fail-safe mechanism.

The distinction that matters most: **Candidate vs Fixture.** An untested stub is *not* a Candidate for
promotion — it is a Fixture that must never be default-on. Conflating them is how a hermetic toy ends up on
the production path (see §4).

## 3. The registry

Evidence tags follow [`environments.md`](environments.md): `[production]` = a real-data efficacy read (the
only kind that qualifies for Core); `[proxy]` = the OSS-9-repo dev box (mechanism/regression only).

### Core — production-validated and default-on (13)
| Capability | Evidence |
|---|---|
| `gloop run` — the frozen 8-stage `run_ticket` loop (`core/workflow.py`) | 2026-07-11 GEI run executed all 8 stages to a bound change on 10/10 cases, 0 crashes `[production]`. |
| `AtlasIndex` — FTS5 `rank_repos` (the `flood` base) **and** `retrieve` (the localize) (`adapters/index/atlas.py`) | Base substrate every arm wraps; `retrieve` = plain FTS5 keyword search scored **7/10 file@5** `[production]`. |
| Composition-root wiring (`cli/__init__.py` `main`) | The sole `gloop run` composition root; carried the `[production]` run. |
| `RecordingEstate` (`adapters/estate.py`) | Deterministic materialize-outcome decorator on the batch path; recorded the `[production]` fix-gradeability signal. |
| `gloop index` (atlas build) | Built the exact 19-repo / 126,919-unit GEI atlas the `[production]` run matched against. |
| `RecordingExtractor` (`adapters/extractor_recording.py`) — sidecar (2026-07-13) | Captures the loop's extractor `signals` into the oracle-free run-record (mirrors `RecordingEstate`; no `core/` edit) so a match-miss RCA can see *why*. |
| Run-record data plane (2026-07-13): persisted `signals`/`cost_usd`/`fixer` + per-batch `manifest.json` (`run/{record,manifest}.py`) | Closes the feedback loop's data plane — a card is now attributable to its atlas/model/affinity pins; `change_sink=mock` recorded honestly. `GatewayModel` self-tracks cost; the batch snapshots per-case deltas. |
| `groundloop/fix/` — plan/patch primitives (2026-07-13) | Relocated out of Dev-Labs `fixeval/` so the Core `PlanningFixEngine`/`ModelPatchEngine` don't import Dev-Labs-Infra (governance separation, §1). |
| Production-surface guards (2026-07-13): the `KLOOP_DEV` dev-gate + the snapshot-verifying `--repos` guard (`cli/__init__.py`) | Dev-gate rejects the silent-degrade fixtures (`--index`/`--fixer canned`/`--case`) in production; the `--repos` guard now verifies catalog snapshots exist (a wrong-but-nonempty path no longer yields fabricating empty worktrees). |
| `AndroidSignalExtractor` / `ComponentExtractor` — the domain **extract** stage (`domains/android_ivi/`) | Ran in the `[production]` loop; `ComponentExtractor` wraps the base extractor to add the `Ticket.component` join the affinity prior needs. `AndroidSignalExtractor` = the domain adapter (prod == dev). |
| `GatewayModel` — the live `Model` port (`adapters/model/gateway.py`) | Cross-cutting Core: underlies `--fixer plan`/`model` and any eval rerank, and self-tracks `cost`/`tokens`/`calls` (the run-record data plane reads it). `CannedModel` is the Fixture double. |
| `SplitIndex` (`adapters/index/split.py`) — 2026-07-13 | Composition-root composite: `rank_repos` from the match index, `retrieve` from the localize index — lets `--localize` differ from `--match-arm` (`run_ticket` uses one `CodeIndex` for both). No `core/` edit. |
| **Labs switch** `KLOOP_LABS` / `--profile labs` (`cli/__init__.py`) — 2026-07-13 | A per-environment switch (the analogue of `KLOOP_DEV`): flips the run defaults to the experimental stack (routing match + atlas localize; fix stays `plan`) **only where enabled**. Explicit flags override it; with it **unset the defaults are Core-identical** (`component`/`atlas`/`plan`). The manifest records `profile`/`localize`. It changes *defaults*, not *validation* — the arms it selects are still Candidate until each earns a `[production]` read. |

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
| **`ModelPatchEngine`** (real single-shot fixer, over the Core `GatewayModel`) | Ran in the `[production]` loop; fix ungradeable only for lack of worktrees. | `--fixer model` — since 2026-07-13 the **opt-out** (the default is the Provisional-Core `--fixer plan`); still fail-closed without creds / `--repos`. |
| **`CheckoutEstate`** (real owner-repo checkout) | The materializer that makes `git apply --check` meaningful. | `--repos` given (required with `--fixer model`). |

The **affinity miner** `gloop mine-affinity` is the *offline build step* that produces that artifact — a
production build step feeding Core, like `gloop index`; it is **not** a `run_ticket` stage and the re-point
does not touch it.

### Provisional-Core — default-on on a fail-safe/safety argument, effectiveness production-gated (1 active)
`PlanningFixEngine` is admitted under the strict §2 criteria (fail-safe mechanism + charter-aligned safety +
a scheduled production read). It is default-on with the *effectiveness* claim production-gated and bounded —
it **must** be resolved by the next instrumented `[production]` run or it reverts.

> **Amendment 2026-07-16 (workflow-simplification).** `SignalQueryIndex` (`--localize tokens`) was
> **removed from Provisional-Core and reverted to a Candidate**: the localize default went `tokens → atlas`
> (the `[production]`-validated FTS5 floor). It had been default-on on `[proxy]`-only evidence as a §2
> *exception* (not abstain-fail-safe); the simplification stops defaulting on an unproven arm. `--localize
> tokens` stays selectable. See `docs/superpowers/specs/2026-07-15-workflow-overdesign-audit-and-simplification.md`.
| Capability | Why default-on (the safety half — proven) | The gate that resolves it (the effectiveness half — open) |
|---|---|---|
| **`PlanningFixEngine`** — "Bug Plan Mode" (plan→gate→re-plan→abstain→execute); `--fixer plan`, **the run default** since 2026-07-13 | Fail-safe by construction: the in-world gate scope-checks every target *before any disk read*, and the executed diff is **re-gated** against candidate scope, so it **abstains** (empty patch) rather than emit an out-of-scope or ungrounded fix. Measured `fabrication_rate = 0.0` `[proxy]`, with a recorded case of it abstaining where the direct fixer fabricated. That honesty *is* a charter-aligned production improvement and reduces incorrect-run risk (Ask-3). | **No measured resolution lift** over `ModelPatchEngine` yet — `resolved_rate` was never gradeable (`[proxy]` ungradeable 2026-07-07; 0-floor 2026-07-13). The next instrumented `[production]` run measures `resolved_rate` (grade-run emits a promotion-eligibility note) → **confirm Core** if it clears the bar with `fabrication_rate ≤ 0`, else **revert** to `--fixer model`. Until then it is bounded: it reverts on governance debt. |
| **`SignalQueryIndex`** — signal-aware FTS5 localize; `--localize tokens` — **REVERTED to a Candidate 2026-07-16** (was the run default 2026-07-15→16; localize default back to `atlas`, see the amendment above). Historical rationale retained: | **NOT abstain-fail-safe — this is a deliberate, recorded relaxation of §2(1), not compliance.** Its worst case is a *worse-ranked file list*, not an abstain — the disclosed `audio −0.017` is exactly such a wrong-output case — so by the letter of §2 it would "stay Candidate". It is default-on anyway on an **operator decision (2026-07-15)** backed by: (a) strong `[proxy]` evidence — functional isolated `file@1` **0.010→0.166 (16×)**, ≥ the atlas/dispatch arms per class; (b) **no gateway dependency** (pure FTS5), so no new production fragility; (c) **no *categorical* new failure mode** vs the `atlas` default it replaces — a token-less ticket falls back byte-identical to `atlas`, and a token-bearing ticket only rewrites the FTS5 query string (not the ranking algorithm — it is not an aggressive re-ranker); (d) **trivially reversible** (`--localize atlas`). The regression surface is *bounded per-ticket*, not categorical. | **Only `[proxy]` evidence; no `[production]` read yet, AND it does not meet strict §2 — so the production read is load-bearing, not a formality.** Bounded per-ticket regression: a ticket whose extracted tokens localize *worse* than its summary (measured `audio −0.017`, ~1/69 — a weak `.so`-only signal). The next instrumented `[production]` GEI run measures `--localize tokens` vs `atlas` `file@1` (`canonical_path` grading) → **confirm Core** if it wins, else **revert** to `--localize atlas`. Reverts on governance debt. |

### Candidate — Dev-Labs research, blocked on a first `[production]` read (7)

> **Amendment 2026-07-16 (workflow-simplification, see the plan spec).** Four run-menu arms were pruned:
> **`LocalizeDispatchIndex` (localize `dispatch`) → Archived** (removed from `--localize`; measured null
> `file@1 0/10 [production]`); the **bge-m3 localize retrieve** (semantic localize) **parked** (removed from
> `--localize`; `SemanticAtlasIndex` is retained for `--match-arm semantic`); **`LLMJudgeIndex` (match
> `judge`) is now eval-only** (removed from `--match-arm`; still reachable via `gloop eval --judge`); and
> **`SignalQueryIndex` (`--localize tokens`) reverted here from Provisional-Core** (still selectable). The
> run localize menu is now `{atlas, tokens}` (superseded — `{atlas, tokens, rerank}` after the follow-on
> below); the run match menu drops `judge`. The historical prose below predates this pruning.

> **Follow-on 2026-07-16 (`feat/codewiki-cbm-localize-fix`).** A NEW `--localize rerank` arm
> (`RerankLocalizeIndex`) was added as an opt-in **Candidate**, so the run localize menu is now
> `{atlas, tokens, rerank}` and the "there is **no** LLM/qwen-rerank localize" statement in the prose
> below no longer holds (it does now). It is a grounded LLM file-reranker over an RRF hybrid candidate
> pool (symbol+doc), enriched per candidate with the source snippet + the CodeWiki module summary + the
> **live per-repo CBM graph** (engaged when `--repos` points at a clone root; the same lazy `_cbm_provider`
> as `--fix-context cbm`), that may only REORDER the pool — never fabricate a path (grounded to real
> source files). Fail-safe throughout: no gateway judge → the grounded pool order; a CBM/map/model error
> drops that context block, never sinks localize. The judge's `cost_usd` is summed into the run cost
> plane (`$/ticket`). `[proxy]`-**unmeasured** — **no `[production]` read yet** (blocked on a first
> isolated `file@1` A/B vs `atlas`/`tokens`); opt-in, defaults unchanged.

`FaultRoutingIndex` / log-match v2 (routing 0.94 `[proxy]`) · functional/dispatch arm (0.68 `[proxy]`) ·
`SemanticAtlasIndex` (bge-m3 vector) · `LLMJudgeIndex` · the bge-m3 vector **localize** retrieve
(`SemanticAtlasIndex.retrieve`, unmeasured for localize; ~~there is **no** LLM/qwen-rerank localize —
`LLMJudgeIndex.retrieve` delegates to plain FTS5~~ — **superseded 2026-07-16:** `RerankLocalizeIndex` /
`--localize rerank` IS an LLM file-reranker localize, see the follow-on note above) · the
functional/no-crash **localize dispatch**
(`LocalizeDispatchIndex`, 2026-07-14 — reachable via `gloop run --localize dispatch`; per-ticket localize
routing: prose-only/no-anchor tickets → the bge-m3 semantic retriever, crash/anchored tickets → the FTS5
retriever, byte-identical to `atlas`; a composition-root class, no `core/`/schema edit; needs an embedder
(`KLOOP_EMBED_BASE_URL`), else degrades to `atlas` with a warn (fails closed if `--localize dispatch` was
explicit); **`[production]` read 2026-07-14: INERT — `file@1 = 0/10`.** Under the production default
`--match-arm component` the extractor is `ComponentExtractor(AndroidSignalExtractor())`, which never sets
`PROSE_MARK` and fills `signals.classes` from the logcat, so `is_functional_localize` is always `False` →
every ticket routes to FTS5 and the bge-m3 branch never engages (`--localize dispatch` ≡ `atlas` in prod).
The earlier `[proxy]` "file@5 +0.021" was on prose-only (`logs=[]`) cases — the one shape where the
discriminator fires — so **non-representative**. **Bugs 1/2/3 FIXED 2026-07-14** (frame-evidence
discriminator + crash-branch code-tokens query + grading `canonical_path`, merged to master): the fixed
dispatch lifted functional isolated `file@1` 0.010→**0.161** `[proxy]` — but the A/B showed the win is
**entirely the FTS5-code-tokens branch**, while the bge-m3 semantic branch is neutral-to-negative at
`file@1`.) (`SignalQueryIndex` / `--localize tokens` — the "keep only the winner" distillation of dispatch
(`code_query` FTS5, no embedder; `[proxy]` `file@1` 0.166) — was **PROMOTED OUT of Candidate to the
Provisional-Core default on 2026-07-15**; see the Provisional-Core table above.) (`PlanningFixEngine` moved to **Provisional-Core** above on 2026-07-13.)

> **Now run-reachable (2026-07-13).** These arms are wired into `gloop run` as opt-in, fail-closed selectable
> arms — `--match-arm {semantic,judge,functional,dispatch}` and `--localize semantic` (via `SplitIndex`) — so
> each can earn its `[production]` read directly. Their blocker moved from *"wire into run + `[production]`"* to
> just **a `[production]` read**. They stay **Candidate**: run-reachable ≠ default. The Core default is
> unchanged unless the **labs switch** (below) is enabled.

**Dev-experience KB** (raw Skills → knowledge distill) — *unproven, not null* (reclassified from Archived
2026-07-13). The prior null was measured on the wrong metric (`plan_target_recall`, not `resolved_rate`) and
rode a localize-query pollution confound — reproduced: skills-in-query cost **Δ−0.10 file@1**. A fair
`resolved_rate` test (`fixeval --skills-inject fix-only`, which is provably localize-invariant) was
**inconclusive** — a 0-resolution floor on a synth slice (the synthetic crash log is disconnected from the
real fix, so nothing resolves). **Production-gated** (2026-07-13 Phase-2 scout): the dev-box proxy provably
*cannot* test the KB — synth fires it but floors resolution at 0, and the OSS fleet has only **~7–15** genuine
crash-with-fix cases (features/UI/usage dominate, not AAOS crashes) — too few for a verdict. The KB is
AAOS-crash-specific; a fair `resolved_rate` verdict needs real **production** AAOS crash+fix tickets (the
[`Phase 2 spec`](superpowers/specs/2026-07-13-kb-fair-eval-phase2-design.md) is therefore a production-side
task). Its A/B machinery (`kb-ab`/`kb-extract`/`kb-attribute`/placebo) — gating on distilled
**Knowledge** — is the eval infra for that test.

### Dev-Labs Infra — permanent measurement / data apparatus (never promoted)
`eval` · `fixeval` · `funceval` · `faulteval` · `compare` · `grade-run` (the production **feedback**
scorecard — now with per-case predicted/oracle/`signals`/`cost` rows, a `--compare <prev-card>` regression
verdict, and reporting-only **promotion-eligibility notes**, 2026-07-13) · `synth` · `mine` ·
`combine-oracle` / `label-bugkind` · `build-atlas` · `doctor` · `GitFixtureEstate`. This is the machinery that
*enforces* the promotion rule — it stays in Dev Labs by design.

### Fixture — permanent hermetic Type-1 doubles (must be explicit, never default)
`CannedFixEngine` · `MockEstate` · `MockJira` · `MockGerrit` · `CannedModel` · `TokenIndex` (M0 stub) ·
legacy `grade()`. **The trap that §4 closes: several of these were the production *defaults*.**

### Archived — measured NULL, stop investing
**`LocalizeDispatchIndex`** (localize `dispatch`) — **Archived 2026-07-16** (workflow-simplification): a
`[production]` measured null (`file@1 0/10`, inert under the `ComponentExtractor` default); removed from the
`--localize` menu + wiring, module + tests deleted (recoverable from git history). *(This section was
previously "currently empty".)* The dev-experience KB track was **reclassified Archived → Candidate (2026-07-13)**: its
null was measured on the wrong metric (`plan_target_recall`, not `resolved_rate`) and rode a localize-query
pollution confound (reproduced: Δ−0.10 file@1), and the fair `resolved_rate` re-test was inconclusive (a
0-resolution floor on a synth slice — the wrong substrate). So the null is **not** validly established and
Archived requires a *genuinely-concluded* one. Nothing else has that yet. See Candidate (KB) +
[`results-log.md`](results-log.md) 2026-07-13. (The lesson still stands — *distrust unverified* — but here it
cuts the other way: we must not archive on an invalid null either.)

## 4. Enforcement — defaults must be Core, Fixtures must be explicit

The single biggest finding of the classification: **the default `gloop run` was a hermetic toy end-to-end**
— canned fixer → empty worktree → mock JIRA → mock Gerrit → `flood` matcher. Every production-validated
capability was opt-in; the one real production run only worked because it hand-overrode ~4 defaults. That is
the "too complicated to be realistic" gap, and it is small to close.

**Re-pointed 2026-07-12 (`cli/__init__.py`, composition root only — no `core/` edit):**
- **Match** default `flood` → **`component`**: resolves the affinity artifact from `--affinity` or
  `KLOOP_AFFINITY`; engages the validated prior when present, else **loudly** falls back to the flood
  baseline (honest degrade — a weaker but real matcher, unlike a garbage-producing one).
- **Fixer** default `canned` → **`model`** (`ModelPatchEngine`); **since 2026-07-13** the default is
  **`--fixer plan`** (the Provisional-Core `PlanningFixEngine`), with `model` as the opt-out (§3).
- **Fail-closed** on the production path: `--fixer model/plan` **errors** if `KLOOP_PRODUCE_API_KEY` is unset
  (no more silent `CannedModel` degrade) **or** if `--repos` has no catalog snapshots (a real fixer over empty
  worktrees fabricates paths — the 2026-07-11 fix-0/10 lesson; the `--repos` check was hardened 2026-07-13
  from presence-only to snapshot-verifying).
- Fixtures are now selected **explicitly and dev-gated (2026-07-13)**: `--fixer canned`, the `--index` M0
  stub, and the single-case `--case` demo are rejected in production and reachable only behind `KLOOP_DEV=1`
  (or the hidden `--dev` flag). The Type-1 suite arms `KLOOP_DEV=1` via an autouse fixture; production cannot
  silently select a hermetic double.

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
- **Provisional-Core is a temporary state, not a resting place.** It resolves on the next instrumented
  `[production]` run: the deferred effectiveness read either promotes it → Core (bar met, `fabrication_rate`
  not worsened) or reverts it → Candidate / the prior default. If that read has not happened by the next
  production cycle, revert to the prior safe default — do **not** let it sit default-on indefinitely on an
  unpaid governance debt. Admit a new Provisional-Core **only** for a fail-safe mechanism (§2 criteria).
- Never let a Fixture (or an unvalidated Candidate) become a default (CI/regression should assert the
  production defaults are **Core- or Provisional-Core-aligned**, and that `KLOOP_DEV` **and `KLOOP_LABS`** are
  off in the production config — `tests/run/test_core_defaults_unchanged.py` locks the labs half:
  no-profile/no-env → `component`/`atlas`/`plan`).
- When in doubt between Candidate and Fixture: *is anyone trying to promote it?* If no, it's a Fixture.
