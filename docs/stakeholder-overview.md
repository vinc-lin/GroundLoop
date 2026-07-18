# GroundLoop — Technical Overview for Stakeholders

> **Audience:** technically-interested management stakeholders. **Purpose:** explain how GroundLoop works and, above all, *why its results can be trusted* — to build confidence in the method rather than to sell an outcome.
> **How to read the numbers:** every measured result is tagged **[proxy]** (dev-box proxy fleet — mechanism and regression only, and systematically optimistic) or **[production]** (real production data — the real efficacy number). A bare, untagged efficacy number would be a defect. The convention is canonical in `docs/environments.md`.
> This document is a synthesis for orientation. It links down into the canonical docs (`charter`, `architecture`, `evaluation`, `capabilities`, and the rest under `docs/`), which remain the single source of truth; where this overview and a canonical doc ever disagree, the canonical doc wins.
> **Status:** v1, 2026-07-15.

## 1. Executive summary

GroundLoop is a code-driven, model-portable pipeline and benchmark that automates bug-fixing across an Android Automotive (AAOS) in-vehicle estate of 130+ code repositories. It is one system with two uses at once — a real fix attempt on a defect ticket, and, because the same run is instrumented and graded offline against a hidden oracle the loop never sees, a scored benchmark of every stage.

The loop is a single deterministic sequence: **JIRA ticket + failure logs → MATCH owning repo → localize → fix → bind (JIRA ↔ commit)**. A Python control plane (`run_ticket`) owns that flow; the model never does. The trust posture that makes the numbers believable — grounding over narrative — is the subject of Section 3.

**The bet.** Stage-1, ticket→repo matching (`rank_repos`, top-1 = the predicted owning repo), is the primary objective and the gate: downstream localize, fix, and bind have value only on tickets whose owning repo was identified correctly. The owning repo is a predicted output and hidden-oracle field, never a loop input.

**Where we honestly stand.** Exactly one production run has happened: a first end-to-end `gloop run` over 10 functional GEI cases (2026-07-11), with all eight stages executing without crashes. It scored Match recall@1 **7/10** `[production]` (a run summary said 8/10 — the per-case table shows three missed cases, so 7/10 stands pending reconciliation), Localize **7/10 file@5** and **1/10 file@1** `[production]`, and Fix **0/10 but ungraded** `[production]` (an empty-worktree artifact, not a fix-stage failure). That is small-N. Most alternative matcher and fix arms are `[proxy]`-only **Candidate**s — validated on the 9-repo OSS dev box, never yet on production; the dev-experience KB is **Dormant** (0 positive signal on the current implementation; see `capabilities.md`), not a Candidate; and the JIRA and Gerrit ends are still mocked (`MockJira` / `MockGerrit`), so the traceable JIRA↔commit chain is not yet real end-to-end. The method is deliberately ahead of the claims.

**Canonical source:** `docs/charter.md` (§1–2), `docs/STATUS.md`, `docs/capabilities.md` (§3–4); tag convention in `docs/environments.md`.

## 2. The problem and the bet

A single Android Automotive (AAOS) vehicle program spreads its software across **130+ code repositories** — apps, framework, HALs, vendor middleware, AIDL/HIDL interfaces, native libraries, build and config — hosted on **Gerrit** via `repo` manifests and tracked in **JIRA**. When a tester hits a defect, they file a JIRA Bug ticket carrying a description, repro steps, and, most importantly, failure logs (logcat, Java/Kotlin stack traces, native `#00 pc …` backtraces, ANRs, tombstones). Nearly every ticket carries logs, so logs are the primary evidence.

Today the first move is manual: a senior engineer reads ticket plus logs, *guesses* which of the 130+ repos owns the defect, then hunts the code. It is slow, experience-dependent, and prone to mis-routing — a ticket sent to the wrong repo burns a cycle before anyone touches the actual bug.

### Why matching is the core objective

GroundLoop reframes this as a closed loop — `ticket + logs → MATCH owning repo → localize → fix → bind (JIRA ↔ commit)` — and the **ticket→repo match (Stage-1) is the gate.** The logic is blunt: localization, fix proposal, and binding have value only against a ticket whose owning repo was identified correctly. Localize the wrong repo and every downstream stage is wasted effort. So Stage-1 is the primary objective and the thing we measure hardest — `Recall@1`, `Recall@k`, and `MRR` over a labeled (ticket+logs → owning-repo) set, plus cost per matched ticket. The owning repo is a **predicted output and hidden-oracle field, never a loop input** — the matcher predicts it, and grading reads ground truth only afterward. The mechanism is `CodeIndex.rank_repos(signals, catalog) → [RepoScore]`, with the real adapter (`AtlasIndex`) ranking over a cross-repo index; top-1 is the prediction.

### The bet, and the evidence for it

The bet is that **cross-repo grounding surfaces knowledge an agent cannot reach on its own.** A concept evaluation isolates exactly this, and the split is clean in both directions. All figures below are **`[proxy]` and directional** — OSS corpora, N≈15, small task families, single-model laps; not settled measurement, and not production efficacy.

- **Null intra-repo.** On single-repo tasks, the agent's own `grep` is already optimal — every arm, including the no-KB control, scored ~100% `[proxy]`. On its home turf the grounded retriever was redundant with grep and added nothing.
- **Large cross-repo lift.** When the needed symbol lives in a *sibling repo absent from the work-tree* — structurally un-greppable from the task's local context — value appears. Across 15 non-guessable cross-repo helpers, the no-KB control succeeded **1/15 (7%)** `[proxy]` while the agent shown the un-greppable prior art used the exact helper **10/15 (67%)** `[proxy]` — a **+60pp** `[proxy]` ceiling, **+40pp** `[proxy]` under realistic adoption.

Ticket→repo matching over 130+ repos *is* the cross-repo regime by construction: the owning repo is one of many, and the discriminating signal lives outside the ticket's local context. The evidence says grounding pays off precisely where GroundLoop operates.

Crucially, the lever is **context, not model tier**. On one cost line (N=9), injected cross-repo context lifted every model off a near-zero floor — Haiku **0→44%** `[proxy]`, Sonnet **22→78%** `[proxy]` — a directional result suggesting the lift is roughly capability-invariant. No amount of reasoning conjures a repo the model has never seen. (The JIRA and Gerrit ends remain mocked; see Section 4.)

**Canonical source:** `docs/charter.md` (§1 Mission & the real problem, §5 Data & test-material strategy, §7 Why the matching premise holds — evidence).

## 3. The trust architecture

Everything downstream in this document — every match score, every localization number — is only as believable as the machinery that produces and grades it. Four structural properties, not promises, make GroundLoop's numbers honestly earned. Each is enforced in code, not policy. These are the trust pillars the rest of the document refers back to.

**Pillar 1 — Grounding over narrative.** The project's founding principle (NFR-1) is that every automated decision must be backed by a signal reality can verify: a matched symbol must actually exist in the repo, a cited file must resolve, a test must pass. Unverifiable LLM prose is treated as the thing to distrust, not the thing to act on. Concretely, the matcher does not "reason about" ownership — `CodeIndex.rank_repos` ranks repos by real hits against a real index (the atlas), and each `RepoScore` carries the matched-token evidence that earned it. The bet is auditable: you can see *why* a repo won, token by token. This is what separates a graded result from a plausible story.

**Pillar 2 — The hidden oracle and the oracle-blind control plane.** The one fact the loop must never be told is which repo owns the defect. GroundLoop enforces this structurally, not by convention: the owning repo is a *predicted output* of `rank_repos` and a *hidden-oracle field*, **never a loop input** (NFR-4). The orchestrator `run_ticket` has no oracle parameter — there is no argument through which ground truth could enter — so the classic owning-repo leak is not "avoided," it is **structurally impossible**. Grading is a strictly separate offline pass: `grade(record, oracle)` in `grade/grader.py` reads the oracle *after* the run has finished and produced its `RunRecord`. Grade is deliberately a plain function, not one of the seven ports the core holds, precisely so the oracle never sits on the loop's dependency path. This is what lets a single execution be both a real fix attempt and a scored benchmark case without the benchmark contaminating the attempt. (Anti-leak invariants are locked by `tests/test_invariants.py` — see Section 7.)

**Pillar 3 — Deterministic control plane vs. cognition plane.** GroundLoop is split into two planes (NFR-6). The **control plane** — deterministic, Python-owned — is `run_ticket`, a straight-line orchestrator that sequences the eight stages, owns all state, and decides termination. The **cognition/IO plane** — the model gateway, the fix engine, everything concrete — sits behind ports and only ever supplies *content* at each step: the extracted signals, the ranking, the proposed patch. The LLM never decides what happens next. No agent chooses the next stage, retries at will, or exits the loop; that logic is ordinary, inspectable Python. This is a deliberate rejection of autonomous-agent-owns-control-flow designs: control flow you can read and re-run is control flow you can trust, and it is why every run is reproducible rather than a one-off improvisation.

**Pillar 4 — The `[proxy]` / `[production]` tagging discipline.** The most expensive mistake available in this project is mistaking a mechanism check for an efficacy claim, so every result number in the repo carries an environment tag. A **`[proxy]`** number is measured on the OSS stand-in fleet on the dev box; it tells you the pipeline *executes and does not regress* — it is optimistic and may not transfer. A **`[production]`** number is measured on the real GEI atlas against the JIRA↔Gerrit oracle; it is the actual scoreboard. The rule is absolute: a bare efficacy number anywhere is a bug in the writeup. This is not bookkeeping — the proxy *systematically flatters*. The canonical cautionary case: functional-text matching scored recall@1 **0.68 `[proxy]`** but only **0.10 `[production]`**, a size-bias artifact of how the OSS fleet is shaped. So throughout this document, treat a `[proxy]` gain as a hypothesis awaiting production confirmation, and read `[production]` as the only real outcome. As of this writing exactly one production run has occurred, most arms are `[proxy]`-only Candidates, and the JIRA and Gerrit ends remain mocked (Section 9) — foregrounding that maturity honestly is exactly what this tagging discipline is for.

Together these four make the rest of the document legible: what is verified, what is merely mechanism, and what has not yet been proven at all.

**Canonical source:** `docs/architecture.md` (§§1–2), `docs/charter.md` (§4 + NFR-1/4/6), `docs/environments.md`.

## 4. System architecture and modules

The trust pillars of Section 3 are not aspirations bolted on afterward; they fall out of the system's shape. GroundLoop is a hexagonal (ports & adapters) system. A **deterministic Python control plane** drives the entire ticket→repo→fix→bind loop through a small set of abstract **ports**, while every concrete behavior — issue I/O, log parsing, repo ranking, patching, model calls — lives behind those ports in a swappable **adapter**. The core imports no adapter, no filesystem path, and no domain literal. That single discipline is what lets the mock environment be "just an adapter set," makes relocating to another machine a config change rather than a code change, and keeps the loop structurally blind to the one fact it must never be told.

**The FROZEN core.** `groundloop/core/` is domain-agnostic and off-limits for feature work. It holds the domain types, the seven port Protocols (`core/ports.py`), and `core/workflow.py::run_ticket` — a straight-line orchestrator that runs the eight loop stages (intake → extract → match → materialize → localize → fix → submit → bind) as ordinary Python. No LLM decides what happens next; only the *content* at each step comes from the cognition/IO plane. The owning repo is a **predicted output** of the match stage, never a `run_ticket` input, so the owning-repo leak is not merely avoided but structurally impossible.

**The 7 core ports.** These Protocols are the contract between the frozen core and the outside world. The mock adapters are the hermetic test substrate; the real adapters wrap the migrated engines and live services.

| Port | Responsibility | Mock adapter | Real adapter |
|---|---|---|---|
| **IssueSource** | Ticket I/O incl. logs + write-back | `MockJira` (dataset files + `ledger.jsonl`) | JIRA client — *still mocked (later)* |
| **SignalExtractor** *(domain)* | logs + ticket → structured signals | supplied by the DomainPack | `AndroidSignalExtractor` — shipped |
| **RepoEstate** | fleet catalog + scrubbed checkout | `MockEstate` | `GitFixtureEstate` / `CheckoutEstate` — shipped (via `--repos`) |
| **CodeIndex** | repo-ranking (MATCH) + within-repo retrieval | `TokenIndex` (membership-overlap stub) | `AtlasIndex` (real FTS5 over an `atlas.db`) |
| **FixEngine** | localize + propose a patch | `CannedFixEngine` (deterministic diff stub) | `ModelPatchEngine` / `PlanningFixEngine` — shipped |
| **ChangeSink** | patch→Change + bind (JIRA↔commit) | `MockGerrit` (content-hashed Change-Id + ledger) | Gerrit client — *still mocked (later)* |
| **Model** *(infra)* | text completion | `CannedModel` | `GatewayModel` (LiteLLM) — **shipped** (live Core `Model` port behind `--fixer model`/`plan`; fail-closed without creds) |

Two ends of the pipeline remain deliberately mocked: the JIRA (IssueSource) and Gerrit (ChangeSink) clients are seams, not shipped integrations. `CodeIndex` is the heart of Stage-1: `rank_repos(signals, catalog) -> [RepoScore]` **is** the ticket→repo MATCH method (top-1 = predicted owning repo, with `score` + matched-token `evidence`), and `retrieve(repo, query)` is within-repo localization.

**Behavior is swapped at the composition root**, `groundloop/cli/__init__.py` — never inside the core. The CLI (`gloop run`, `gloop index`, and siblings) selects each adapter and passes it to `run_ticket` by keyword; upgrading `TokenIndex` → `AtlasIndex`, `CannedFixEngine` → a real fixer, or adding a domain changes only the wiring. `groundloop/config/settings.py` is the single env-reading surface (`KLOOP_*`), so no other module reads a path or env var directly.

**The atlas.** Both `rank_repos` and `retrieve` run over the **atlas** — a SQLite store of *code units*, each held in two searchable forms: an **FTS5** keyword row and a **bge-m3** semantic vector. A unit's `kind` is **symbol** (one per class/method/function, enumerated by CBM; its indexed text is a compact `name label qualified_name file_path` identity — the shape a `package.Class.method` or `.so` signal matches) or **doc** (CodeWiki markdown chunks). The shipped fleet atlas is largely symbol-only. The two arms split the work: **membership** is pure FTS5 keyword overlap (fully offline, no GPU); **semantic** cosines embedded signal tokens against stored vectors, recovering prose logs where keyword matching collapses. The embed model is pinned to `bge-m3` at both index and query time — a mismatch would corrupt cosine ranking, so it is guarded at construction.

**The domain pack seam.** Domain specifics — the AAOS fleet catalog and `AndroidSignalExtractor` (logcat / Java-stack / native-backtrace parsing) — live behind a `DomainPack` seam so the core stays generic. **Exactly one pack exists today: `groundloop/domains/android_ivi/`.** Multi-domain is a design-for-later seam, not a feature: there is no plugin, discovery, or registry framework and no second domain (YAGNI). Adding a domain later means adding a package; the core is untouched.

**Migration, not rewrite.** The valuable `atlas`, `lore`, and `produce` engines under `groundloop/engines/` were migrated **verbatim** from the read-only `knowledgeLoop` source — copy the file, rewire `knowledgeloop.*` → `groundloop.engines.*`, preserve logic exactly (only the import rewire and an `_envcompat` shim change). Nothing was reimplemented.

**Canonical source:** `docs/architecture.md` (§2–§7).

## 5. The four stages

The loop is one deterministic control plane — `run_ticket`'s eight steps (intake → extract → match → materialize → localize → fix → submit → bind) — collapsing to four objective stages. Each is a **port** (a frozen `Protocol` in `core/`) with a **real adapter** wired at the composition root, plus a set of selectable, individually A/B-able **arms** (the improvement method itself is Section 6). Stage-1 MATCH is the gate: downstream stages are graded only against correctly-matched tickets. The four blocks below share one template so the maturity gradient is legible at a glance — and that gradient is steep: Match has a real production read, Localize has one too, Fix is wired but not yet gradeable, and Bind is still mocked. *For the concept behind each stage — the underlying idea and why it is shaped that way — see the companion [`stages-concept.md`](stages-concept.md).*

### Stage 1 — Match (the gate)
- **Principle.** From ticket text + extracted log signals, rank which repo among the fleet *owns* the defect; top-1 is the prediction. The owning repo is a predicted output and hidden-oracle field, **never a loop input**.
- **Module(s).** Port `CodeIndex.rank_repos(signals, catalog) -> [RepoScore]`; real adapter `AtlasIndex` — FTS5 unit-membership scoring over a real `atlas.db` (the `flood` base every arm wraps).
- **How it is improved.** Selectable arms (method → Section 6): `flood` baseline (`AtlasIndex` FTS5); **`component`-affinity RRF** (`ComponentPriorIndex`, `--match-arm component`, the Core default — a mined JIRA-component→repo prior, RRF-fused so it is scale-invariant to base score magnitude, built offline by `gloop mine-affinity`); `semantic` (`SemanticAtlasIndex`, bge-m3 vectors); `judge` (`LLMJudgeIndex`); `functional` (title+description over a repo-text profile, for no-crash bugs); `dispatch` (per-ticket crash|functional router); `fault-routing` (`FaultRoutingIndex`, log-match v2). All but `flood`/`component` are **Candidate** — run-reachable, opt-in, not default.
- **Current evidence.** The affinity prior is the dominant lever: recall@1 **0.10 → 0.50** `[production]` (recall@3 **0.90** `[production]`), the read the component-routing pivot was built for. The single production run scored match recall@1 **7/10** `[production]` by the per-case table — with an honest reconciliation flag: a run summary reported 8/10, and the correct figure is 7/10 (three missed cases; the two match root causes — a label≠owner ticket and a CarPlay near-tie — both need signal beyond the `component` field). Candidate arms are `[proxy]`-only: functional/dispatch recall@1 **0.68** vs flood 0.32 `[proxy]`; routing **0.94** `[proxy]` on crash logs.

### Stage 2 — Localize
- **Principle.** Within the matched repo's work-tree, retrieve the suspicious files/symbols. Localize runs *before* fix, so it is measured independently (and isolated on the oracle repo to remove match error).
- **Module(s).** Port `CodeIndex.retrieve`; real adapter `AtlasIndex.retrieve` — **plain FTS5 keyword search** over symbol units. (The bge-m3 vector and any rerank paths are eval-only arms, never wired into `run_ticket` by default.)
- **How it is improved.** Selectable arms: `atlas` (FTS5, the prior default); **`tokens`** (`SignalQueryIndex`, `--localize tokens` — queries extracted code tokens rather than the summary, no embedder, the new **Provisional-Core** default as of 2026-07-15); `semantic` (`SemanticAtlasIndex.retrieve`, bge-m3, composed via `SplitIndex` so localize can differ from the match arm); `dispatch` (`LocalizeDispatchIndex`, per-ticket router — **Candidate**).
- **Current evidence.** On the production run, keyword localize alone got **7/10 file@5** `[production]` but only **1/10 file@1** `[production]` — a real rank-1 precision gap (an earlier "0/10" was a misread of the fix stage's fabricated file). The `tokens` arm is the `[proxy]` answer to that gap: isolated `file@1` **0.166** vs dispatch 0.161 vs atlas 0.010 `[proxy]`, matching dispatch's win with no embedder dependency. Both remain `[proxy]` and Provisional-Core/Candidate; the `[production]` GEI `file@1` read is the resolver.

### Stage 3 — Fix
- **Principle.** Emit a candidate patch, and — the load-bearing safety property — **abstain rather than fabricate** when the fix cannot be grounded to the localized scope.
- **Module(s).** Port `FixEngine.propose`; real adapters `PlanningFixEngine` (`--fixer plan`, "Bug Plan Mode": plan → in-world scope gate → re-plan → abstain → execute, re-gating its executed diff) and `ModelPatchEngine` (`--fixer model`, single-shot). The `CannedFixEngine` is a **Fixture** double, dev-gated (`KLOOP_DEV`), never a production default.
- **How it is improved.** The engine ladder is `canned` (Fixture) → `model` (`ModelPatchEngine`) → **`plan`** (Bug Plan Mode, the Core-aligned default and a **Provisional-Core** capability — default-on on a fail-safe/safety argument, *effectiveness* still production-gated). Orthogonally, the **dev-experience KB** injects distilled `Knowledge` playbooks into the fix prompt (`--skills` / `--knowledge`, fix-only injection so it is localize-invariant) — a *measured* arm, currently **Dormant** (0 positive signal on the current implementation, blocked on a redesign; see `capabilities.md`).
- **Current evidence.** On the production run, fix scored **0/10** `[production]` — but this is **UNGRADED, not a fix failure**: an empty-worktree artifact (no corpus checkout for the owner repos, so any real fixer fabricates paths). The one honest, tagged fix number is `PlanningFixEngine`'s **`fabrication_rate = 0.0`** `[proxy]` — with a recorded case of it abstaining where the direct fixer fabricated. `resolved_rate` (the effectiveness metric) has **never been gradeable** — inconclusive on `[proxy]` synth (0-resolution floor, synth log disconnected from the real fix). The KB is likewise production-gated: the dev-box substrates are exhausted (~7–15 real crash-with-fix cases fleet-wide). The deferred `[production]` `resolved_rate` A/B (plan vs model) is what resolves Bug Plan Mode to Core or reverts it.

### Stage 4 — Bind
- **Principle.** On commit/PR, bind the fix to the originating ticket and persist an append-only, auditable chain (discovery → logs → repo → localization → fix → PR/commit ↔ ticket) — the loop's central JIRA↔commit-traceability promise.
- **Module(s).** Port `ChangeSink.submit` + `ChangeSink.bind`; adapter **`MockGerrit` — STILL MOCKED** (and the intake end, `MockJira`, likewise). These are **Fixture** doubles, not validated production components.
- **How it is improved.** There are no competing arms here — the improvement is a single net-new build, explicitly **forward-looking**: a live Gerrit `ChangeSink` (real change + verifiable JIRA↔commit binding) and a live JIRA REST `IssueSource` (fetch + comment/transition write-back). Until those land, the traceable chain is mocked at both ends.
- **Current evidence.** **None — and by design.** Bind carries no efficacy number: the production run executed the stage to a *mock* bound change (recorded honestly as `change_sink=mock`). This is the most honest boundary of the system's current maturity — the ends of the loop are demonstrated mechanically, not measured.

**Canonical source:** `docs/charter.md` §2 · `docs/capabilities.md` §3 · `docs/results-log.md` · `docs/fix-loop.md` (with `docs/STATUS.md` for current state).

## 6. The improvement engine

The arms in Section 5 are not one-off experiments; they are instances of a single, reusable machine for changing behavior without changing risk. Three properties make that machine trustworthy: every strategy is a swappable adapter measured against the incumbent, tuning happens on cheap deterministic layers while the expensive agentic test is reserved for outcome validation, and a formal governance model decides when — and only when — an experiment is allowed to become the product.

### Arms and offline A/B

A stage's behavior is an adapter selected at the composition root (`cli/__init__.py`), never a branch inside the frozen `core/`. A new strategy is therefore an *arm*: a new adapter wired in behind a flag (`--match-arm`, `--localize`, `--fixer`), measured head-to-head against the current incumbent, with `core/run_ticket` and the atlas schema left untouched. Match arms wrap the base `AtlasIndex`; the fix stage swaps `PlanningFixEngine`, `ModelPatchEngine`, or the hermetic `CannedFixEngine`. Because the loop is oracle-blind (Section 3), an arm can be added and A/B'd with zero edits to the control plane and no path to the answer — the swap is the only variable that moves.

### The evaluation pyramid

Not every A/B is worth the same cost, and treating them alike is how noise gets mistaken for signal. GroundLoop tunes on a four-layer pyramid, cheapest first:

1. **Retrieval** — `Success@k` / `MRR`, agent-free, milliseconds per case.
2. **Grounding** — precision / recall against grep-verified source reality, deterministic.
3. **Context-injection** — dozens of runs.
4. **Agentic A/B** — the actual end-to-end outcome; expensive and noisy.

Layers 1–2 run in seconds over N in the hundreds, so a strategy or signal arm can be tuned offline with real statistical power via `gloop eval` / `fixeval` / `funceval` / `faulteval`. Layer 4 is the only layer that measures the true goal, but it is statistically weak at the N we can afford: the knowledgeLoop lap-log measured two *behaviourally identical* conditions scoring **20% vs 40% `[proxy]`**, pinning the N≈10 agentic noise floor at ≈ **±20pp `[proxy]`**. The discipline that follows is strict — the agentic layer *validates* that an offline gain survives end-to-end; it is never the tuning instrument. Any agentic arm difference below the floor is treated as noise.

### Production-Core / Dev-Labs governance

The pyramid says *how* to measure; the governance model says *when a measurement counts*. Every capability sits in exactly one state. Four are on a promote→archive axis — **Core**, **Provisional-Core**, **Candidate**, **Archived** — and two are permanent roles off that axis: **Dev-Labs Infra** (the measurement apparatus — `grade-run`, `compare`, the eval commands — that enforces the rule and is never promoted into the loop) and **Fixture** (hermetic Type-1 doubles like `MockJira`, `MockGerrit`, `CannedFixEngine` that must be selected explicitly, never defaulted).

The promotion rule is the confidence backbone: a capability enters **Core only after it consistently outperforms the current solution on real production data** and clears stability, cost, and regression gates — a deliberate act, not a side effect of merging. A `[proxy]` win keeps a capability a **Candidate**; only a `[production]` read promotes. The component→repo affinity arm (`ComponentPriorIndex`) is the one capability that has cleared this: recall@1 **0.10 → 0.50 `[production]`**.

**Provisional-Core** is the single, named, bounded exception — not a loophole. It admits a *fail-safe* capability whose worst-case failure is an honest **abstain**, never a confident-wrong output, to become the default *before* an effectiveness read exists, on a charter-aligned safety argument. `PlanningFixEngine` (`--fixer plan`) qualifies: it abstains rather than emit an out-of-scope patch, measured **fabrication_rate = 0.0 `[proxy]`**. The safety half is proven; the effectiveness half (`resolved_rate`) is explicitly still production-gated, and the state is bounded — it resolves to Core or reverts on the next instrumented `[production]` run, or reverts on unpaid governance debt. The second Provisional-Core member — `SignalQueryIndex` (`--localize tokens`) — is admitted as a *documented exception* to that fail-safe criterion: its worst case is a worse-ranked file list (the disclosed `audio −0.017` `[proxy]`), not an abstain, so it was made default-on on strong `[proxy]` evidence, the absence of any new categorical failure mode, and trivial reversibility (`--localize atlas`) — not by meeting the abstain-fail-safe rule.

The governance model is itself a confidence argument because it structurally prevents an experiment from masquerading as the product — and it was written *because* that had happened. The classification's single biggest finding: the default `gloop run` was a hermetic toy end-to-end — canned fixer → empty worktree → mock JIRA → mock Gerrit → `flood` matcher — and the one real production run worked only because it hand-overrode roughly four defaults. The fix re-pointed the defaults (composition root only) at the validated components, made every fixture explicit and `KLOOP_DEV`-gated so production cannot silently select a double, and fails closed without credentials or valid repos. Enforcement is now asserted: defaults must be Core- or Provisional-Core-aligned, fixtures must be opt-in. This is the mechanism that keeps the honest-maturity picture in Section 9 honest.

**Canonical source:** `docs/capabilities.md` (governance model + registry); `docs/evaluation.md` §10 (evaluation pyramid + noise floor); `docs/workflows.md` (Candidate→Core promotion checklist).

## 7. Testing

The governance rule of Section 6 is only credible if the guarantees it rests on are themselves tested. GroundLoop runs **two paired test surfaces**, and keeping them distinct is what lets the numbers be read honestly. **Type-1** is the hermetic development-test suite: it measures **correctness** (pass/fail), takes no network and no real LLM, and runs on every change. **Type-2** is the live effectiveness eval: real models over a real `atlas.db`, producing a graded scorecard (Section 8). The two map cleanly onto the dev-box ↔ production split — Type-1 and Type-2-on-proxy run on the dev box; the real efficacy scoreboard is production. This is exactly the separation NFR-8 mandates: a hermetic no-network suite (Type-1) plus live tests gated on credentials (Type-2), over pinned repo SHAs.

**Type-1 substrate and coverage.** The suite runs against a deterministic micro-fleet with no live dependency: `CannedModel` (`adapters/mock/model.py`) stands in for the LLM, and a 4-repo FTS5 `atlas.db` fixture (`tests/fixtures/atlas_fixture.py`, no CBM/embedder) stands in for the real corpus. Shared fixtures live in `tests/conftest.py` (`harness`, `atlas_harness`, `case`, `atlas_db`, `catalog_path`). Coverage is the full hermetic vertical slice (`test_e2e_vertical_slice.py`: `run_ticket` → match → … → bind → offline `grade`), plus per-stage tests, the engines, the ports/types/CLI/settings, and the self-scoring layer. The two `tests/e2e/` live cases are `skipif`-gated on `KLOOP_*` credentials — production leaves them dormant unless the gateway is reachable.

**Leak-tightness is tested, not merely intended.** This is the section's load-bearing point and a direct confidence lever. The trust guarantees the loop rests on (Section 3) are pinned by executable regression guards in `tests/test_invariants.py`; a failure there means a real leak was reintroduced, not a style nit. The invariants assert, among others:

- **The ticket never names the owner.** The sanitized ticket (component/summary/description/logs/comments) never contains the owning repo, and `owning_repo` lives only in the hidden oracle — the anti-leakage contract NFR-4 requires.
- **The loop never reads the oracle.** A `Path.read_text` **read-spy** over a full `run_ticket` execution asserts nothing under the oracle (or bind output) is opened during the loop.
- **Deterministic control flow.** Identical inputs produce identical events, repo choice, ranked order, and `Change-Id`.
- **The run-record is oracle-free, and `grade_run` is the sole oracle reader.** The persisted `RunRecord` carries no oracle field; grading is a separate offline pass (`gloop grade-run`), so the loop cannot peek at what it will be scored against.

A bridge test, `test_atlas_matcher_honors_invariants`, extends this to the real `AtlasIndex`: it must pick the owner from log signals alone and beat a `1/N` guess (FR-3's genuine N-way choice), so the leak-safety proven on fixtures is anchored to the production matcher.

**Honest maturity note.** One invariant is deliberately not yet green: the full `@base = fix^` history-scrub (invariant #3) is `skip`-pending the real `RepoEstate`; only its weak form is enforced today. That gap is tracked in the open, not papered over — consistent with the project's "grounding over narrative" stance that a known, tested gap is worth more than an untested claim.

**Canonical source:** `docs/evaluation.md` (§9, §14); `docs/environments.md`; `docs/charter.md` (NFR-4, NFR-8).

## 8. Evaluation and scoring

Where Type-1 asks "does it run correctly," Type-2 asks "how well." It does not gate on pass/fail; its verdict is a **scorecard** — the offline artifact that turns a batch of runs into a defensible measurement. `groundloop/eval/scorecard.py` emits `scorecard.json` (with a human-readable markdown twin from `report.py`) structured as **per-arm × per-repo × per-stage metrics + cost + provenance**. The provenance block stamps the `atlas_db_sha`, the pinned `bge-m3` embed model, the repo pins, the harvest-snapshot SHA, and the answerable/unanswerable case counts, so any number is reproducible against the exact substrate that produced it. Every efficacy figure the scorecard reports is tagged `[proxy]` or `[production]`; a bare efficacy number is treated as a defect.

**Two views per arm.** Each matcher arm is scored twice. The **forced ceiling** (abstention off, always emit top-k) keeps arms comparable and stops an arm hiding weak retrieval behind refusal. The **selective view** (abstention on) measures grounded refusal. The charter is explicit that a metric rewarding guessing over grounded refusal is broken, so the selective view is not optional.

**Stage-1 forced metrics.** `repo_recall@1` — top-1 equals the hidden `owning_repo` — is the headline. Alongside it: `repo_recall@3`, `repo_recall@5`, `repo_mrr`, and `mean_repo_rank` (a triage-effort proxy). Because Stage-1 has a single exact-match target, the file-level any-of metrics collapse (`recall@k == success@k`, `mrr == 1/repo_rank`); `grade/grader.py` encodes this single-exact behaviour, and the migrated any-of retrieval metrics are re-purposed for the Stage-2 `localization_recall` path, never for repo-matching.

**Grounded refusal, and why guessing can't win.** The matcher abstains when the **top1−top2 margin** (`ranked[0].score − ranked[1].score`) falls below a threshold `τ` calibrated on a held-out `calib` split and frozen for test — a scale-robust gate over the uncalibrated FTS5 count score. The selective view then reports `coverage`, `selective_risk`, the **risk-coverage curve**, `AURC`/`AUGRC`, and fixed operating points (`accuracy@70%-coverage`, `coverage@5%-risk`). The load-bearing scalar is **Effective Reliability `Φ_c`**: answered-correct = +1, answered-wrong = −c, abstain-on-answerable = 0, abstain-on-unanswerable = +1, answered-on-unanswerable = −c. The construction is deliberate — a wrong guess (−c) scores strictly below an honest abstain (0), and on an out-of-fleet ticket a correct abstain (+1) beats a fabricated answer (−c). No always-answer policy can therefore dominate a calibrated abstain policy: **guessing can never beat grounded refusal.** `Φ_c` is swept over c ∈ {0.5, 1, 2} with c=1 the neutral default, and `abstention_recall_oof` reports NoAns recall on the deliberately surface-similar out-of-fleet negatives, so a degenerate always-answer or always-abstain arm is immediately visible. This is the scoring-layer expression of the Section 3 trust pillars: the score is computed against a hidden oracle the loop never sees, and the metric refuses to pay for confident narrative that reality cannot verify.

**Cost is a first-class metric.** NFR-2 makes cost co-equal with accuracy: the scorecard's `cost` block reports `usd_per_ticket` (dollars per ticket-matched) with input/output token counts, and the downstream fix-loop reports `$/solved`. Arms are compared per dollar, not on accuracy alone.

**Statistics honesty knobs.** Every proportion carries a **Wilson 95% CI** (stable from n≈10, unlike Wald). `AURC`/`AUGRC` are **gated on n ≥ ~128** (badly biased below n=32); the aggregate ticket volume clears this, but any per-stratum slice that falls short is flagged directional-only. Arms are compared at matched coverage (or via `Φ_c` / the full RC curve), never at whatever coverage each happened to choose. The discipline is grounded in a measured lap-log result: two behaviourally identical conditions once scored 20% vs 40% `[proxy]`, pinning the N≈10 agentic noise floor at ≈±20pp — which is exactly why the primary effort sits on the cheap deterministic retrieval layer and the selective view, not the expensive agentic A/B.

**One run is both.** A single `core.run_ticket` execution is simultaneously a real fix attempt (a pipeline run) and a graded eval case (a benchmark row), bridged by the hidden oracle: the loop emits its prediction with no ground truth in scope, then an offline pass reads `_oracle/` and scores it — `grade/grader.py` for a full run, `score_match` for the matching-only slice (`gloop grade-run` for a pipeline batch, `gloop eval` for the Type-2 harness). To date exactly one such run has been graded on production data (see Section 9); the remaining matcher and fix arms are `[proxy]`-only Candidates, and the JIRA and Gerrit ends are still mocked.

**Canonical source:** `docs/evaluation.md` (§7 metrics & scorecard, §2 staged plan, §10 methodology) + `docs/charter.md` §4.

## 9. Where we stand

GroundLoop grades its own maturity the same way it grades a fix: on evidence, not intent. The capability registry (`docs/capabilities.md`) sorts every built component onto a governance axis — **Core / Provisional-Core / Candidate / Fixture / Archived** — with **Core** reserved for what has been validated on real production data *and* wired as the default. That line is the honest snapshot.

**The maturity map (drawn from the registry):**

| Layer | State | What it means here |
|---|---|---|
| The 8-stage `run_ticket` loop; `AtlasIndex` FTS5 match+`retrieve`; the composition-root wiring; `gloop index`; `ComponentExtractor`/`AndroidSignalExtractor`; `GatewayModel` | **Core** (13) | Ran end-to-end on the real 19-repo / 126,919-unit GEI atlas. Deterministic, default-on. |
| Component→repo affinity (`ComponentPriorIndex`, RRF-fused); `ModelPatchEngine`; `CheckoutEstate` | **Core-when-configured** | Production-validated; engaged when their artifact/flags (`--affinity`, `--repos`) are supplied. |
| `PlanningFixEngine` (`--fixer plan`); `SignalQueryIndex` (`--localize tokens`) | **Provisional-Core** (2) | Default-on on a *safety/fail-safe* argument; **effectiveness is still production-gated**. |
| `FaultRoutingIndex`, functional/`dispatch` arm, `SemanticAtlasIndex`, `LLMJudgeIndex`, the bge-m3 localize retrieve, `LocalizeDispatchIndex` (plus the dev-experience KB, separately reclassified to **Dormant**, 2026-07-18) | **Candidate** (6) | `[proxy]`-only or unproven; opt-in, never the silent default. |
| `MockJira`, `MockGerrit`, `CannedFixEngine`, `MockEstate`, `CannedModel`, `TokenIndex` | **Fixture** | Hermetic Type-1 doubles — must be selected explicitly, dev-gated behind `KLOOP_DEV`. |

Archived is currently **empty**: the KB null was discredited (measured on the wrong metric), so it was moved back to Candidate, then further reclassified **Dormant** (2026-07-18, see `capabilities.md`) rather than left as a false conclusion.

**The one production run.** Exactly one full `[production]` read exists: the first full 8-stage `gloop run` over **10 functional GEI cases** (2026-07-11). All 10 ran every stage to a bound change with 0 crashes. **Match recall@1 = 7/10 `[production]`** by the per-case table — a reconciliation caveat: the run summary reported 8/10, but the per-case table shows three misses (`13363`/`14905`/`8185`), so the honest figure is 7/10 pending a raw-scorecard confirm. **Localize = 7/10 file@5 `[production]`** (1/10 file@1 `[production]`), measured via plain FTS5 `AtlasIndex.retrieve`; the earlier "0/10" was a measurement error (it read the fix stage's fabricated file). **Fix = 0/10 but ungraded `[production]`** — an empty-worktree artifact (no owner repo checked out), not a fix-stage failure. The dominant Stage-1 lever behind that run is separately measured: the affinity prior lifts match recall@1 **0.10 → 0.50 `[production]`** (recall@3 0.90 `[production]`).

**The remaining gaps to a real Core** are named precisely, not hedged:

- The JIRA and Gerrit ends are **still mocked**. Closing them means net-new builds: `MockJira` → a live JIRA REST `IssueSource` (fetch + write-back) and `MockGerrit` → a live Gerrit `ChangeSink`. Until both land, the loop's central promise — a traceable JIRA↔commit chain — is real for match→localize→fix but mocked at intake and submit.
- **Bug Plan Mode** (`PlanningFixEngine`) is default-on on a proven safety property (`fabrication_rate = 0.0` `[proxy]` — it abstains rather than fabricate) but its resolution lift is unmeasured. The scheduled **`[production]` `resolved_rate` A/B (plan vs model)** is the resolver: it promotes Bug Plan Mode to Core or reverts to `--fixer model`. `gloop grade-run` already emits the promotion-eligibility note.

**Direction.** The production scoreboard is the 19-repo GEI atlas today; the target is the **130+ repo AAOS fleet**, where a `1/N` guess scores far below a real match and Stage-1 becomes genuinely load-bearing. The Candidate arms (functional/`dispatch` at 0.68 `[proxy]` vs flood 0.32 `[proxy]`; fault-routing at 0.94 `[proxy]`) are already run-reachable, each waiting on its own first `[production]` read to earn Core. The method is deliberately ahead of the claims: what is proven is small and labeled; what is promising is reachable but unpromoted.

**Canonical source:** `docs/capabilities.md` (§3–4), `docs/results-log.md`, `docs/STATUS.md`, `docs/roadmap.md`.

## 10. Glossary and pointers

This section is the map. The terms below are load-bearing across the whole document; the table routes each topic to its single canonical doc so you can go deeper without this overview duplicating (and drifting from) the source of truth.

### Glossary

- **Owning repo** — the repository that contains the defect (and where the fix lands). Stage-1's prediction target; a predicted output and hidden-oracle field, **never a loop input**.
- **atlas.db (repo-atlas)** — the cross-repo SQLite index of code units, where every hit is tagged with its owning repo (the core matching primitive). Built by `gloop index`; queried by the `AtlasIndex` FTS5 matcher.
- **Fleet** — the set of N candidate repos the matcher ranks against (production target: the 130+ AAOS vehicle repos; pilot: a curated OSS IVI proxy fleet).
- **Signals** — structured discriminators extracted from failure logs: exception/error types, stack frames, package/class/method names, process/module names, `.so` names, error codes.
- **Grounding** — verifying a claim against reality (code, tests, logs) rather than trusting LLM prose. The project's founding principle.
- **Oracle** — hidden ground truth (owning repo + fix) used only by the offline `grade()` pass, never seen by the loop.
- **CBM** — Codebase-Memory (`codebase-memory-mcp`), the code-graph backend behind localization.
- **Type-1 / Type-2** — hermetic no-network development tests / live-eval with real models and a real atlas.db.
- **[proxy] / [production]** — the mandatory result-tag convention: `[proxy]` = a number earned on the OSS proxy fleet (flatters the mechanism); `[production]` = earned on the real AAOS/GEI estate. A bare efficacy number is a defect.
- **Arm** — an A/B-able configuration of a stage (e.g. match arms `component`/`semantic`/`judge`/`functional`/`dispatch`; fixer arms `canned`/`model`/`plan`).
- **Core / Candidate** — governance states from the capability registry: **Core** (production-aligned, the default) vs **Candidate** (reachable but proxy-only, unproven, awaiting a `[production]` read). The registry also carries Provisional-Core, Dev-Labs-Infra, Fixture, and Archived.

### Read next

| Topic | Canonical doc |
|---|---|
| Mission, FR/NFR requirements, four stages, metrics | `docs/charter.md` |
| Hexagonal ports & adapters, control plane, atlas internals | `docs/architecture.md` |
| Evaluation method, arms, scorecard; Type-1 surface (§14) | `docs/evaluation.md` |
| Core/Candidate governance + capability registry | `docs/capabilities.md` |
| Dev-box↔production split + `[proxy]`/`[production]` tags | `docs/environments.md` |
| Localize→fix→grade design + the dev-experience KB | `docs/fix-loop.md` |
| Atlas build, env vars, reuse contract, gated-live setup | `docs/build-setup.md` |
| Deploy / run / migrate how-to + adapter swap map | `docs/guide.md` |
| Mining, two-stage matcher, milestone tracks, phasing | `docs/roadmap.md` |
| Chronological, tagged log of every eval result | `docs/results-log.md` |
| Current state, blockers, next steps (read first) | `docs/STATUS.md` |

**Canonical source:** `docs/charter.md` §9 (glossary) + the `CLAUDE.md` docs index.
