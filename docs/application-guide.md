# GroundLoop — Application Guide (How It Is Applied)

> Companion doc. It answers one narrow question: **how is GroundLoop meant to be used, by whom, and in
> what scenarios?** For the *why/what* see [charter.md](charter.md) (mission + FR/NFR); for *how it is
> built* see [architecture.md](architecture.md); for *what's next* see [roadmap.md](roadmap.md); for the
> *current build state* see [STATUS.md](STATUS.md). This guide cross-links rather than restating those.

## 1. One system, two uses (bridged by a hidden oracle)

GroundLoop is simultaneously a **pipeline** and a **benchmark** over the same substrate:

- **As a pipeline** — an automated, traceable *closed loop* from a **JIRA defect ticket + failure logs**
  to a **code fix**, across a 130+-repo Android Automotive (AAOS) estate:
  `ticket + logs → MATCH owning repo → localize → fix → bind (JIRA ↔ commit)`.
- **As a benchmark** — the *same* loop instrumented so each stage — above all **Stage-1 repo-match
  accuracy and cost** — is scored over labeled data as A/B-able arms with per-repo breakdowns.

The bridge is the **hidden oracle**: the loop never sees ground truth; an offline `grade(record, oracle)`
pass reads it *afterward* to produce the benchmark numbers. That is what lets a *single run* be both a
real fix attempt and a scored evaluation case.

**The defining bet:** **Stage-1 ticket→repo matching is the gate.** From ticket text + log-derived
signals, predict which repo among many OWNS the defect. The owning repo is a **predicted output +
hidden-oracle field, never a loop input** — downstream stages are only worth pursuing against tickets
whose owner was matched correctly.

## 2. The application workflow (the pipeline)

Real-world context: AAOS/IVI software for one vehicle program is spread across 130+ Gerrit repos (apps,
framework, HALs, vendor middleware, AIDL/HIDL, native libs). A tester files a JIRA bug with description,
repro steps, and — critically — **failure logs** (logcat, Java/Kotlin stack traces, native `#00 pc …`
backtraces, ANRs, tombstones). Today a senior engineer manually reads ticket + logs, guesses the owning
repo, and hunts the code — slow, experience-dependent, and prone to mis-routing.

GroundLoop automates this as the deterministic `run_ticket` control plane (`groundloop/core/workflow.py`),
an 8-stage sequence appended to an append-only event trace. Control flow is ordinary Python — the LLM
owns only the *content* at each step, never *what happens next*:

| Stage | What it does |
|---|---|
| intake | `IssueSource.fetch(ticket_id) → Ticket` (summary, description, logs; owner absent) |
| extract | `SignalExtractor.extract(logs, ticket) → Signals` (packages/classes/methods/native symbols/`.so`/errors) |
| **match** | `CodeIndex.rank_repos(signals, catalog) → [RepoScore]`; `chosen = ranked[0]` = **predicted owning repo** |
| materialize | `RepoEstate.materialize(chosen) → WorkTree` (scrubbed, isolated) |
| localize | `CodeIndex.retrieve(chosen, query) → candidate file locations` |
| fix | `FixEngine.propose(worktree, ticket, locations) → Patch` (today a `CannedFixEngine` stub) |
| submit | `ChangeSink.submit(chosen, patch, ticket) → Change` (Change-Id + JIRA key in subject) |
| bind | `ChangeSink.bind(change, ticket)` — append the ledger + transition the ticket (the JIRA↔commit chain) |

Output is a `RunRecord` — the artifact the offline grader scores. Full stage/port design:
[architecture.md](architecture.md).

## 3. Main application scenarios

**A. Stage-1 matcher evaluation (the primary near-term use).** Run many ticket cases through the loop,
then offline `grade(record, oracle) → Scores` per case and aggregate Stage-1 metrics — `repo_recall@1`,
`repo_rank` (rank of the correct repo = a triage-effort proxy), forward `recall@k`/MRR, per-repo
confusion, and **cost per matched ticket**. The question it answers: *is the matcher actually picking
the owner out of N confusable repos, or just guessing?*

**B. Closed-loop triage & fix on a real ticket (the end-state pipeline).** Drive one ticket + logs all
the way to a bound change. Fully wired through `run_ticket` today with mock JIRA/Gerrit; the fix stage is
a `CannedFixEngine` stub until the real agentic `FixEngine` lands (design provenance:
[downstream-fix-loop.md](downstream-fix-loop.md)).

**C. A/B-arm mechanism comparison (measured-mechanism mode).** Add each new mechanism only as a *measured
arm* and keep it only if it beats its cost: matching-strategy arms (membership-only baseline → +semantic
rerank → +LLM-judge) and signal arms (text-only vs +logs, to quantify how much the logs help). See
[roadmap.md](roadmap.md) for the arm design and [groundloop-testing-strategy.md](groundloop-testing-strategy.md) §3.3.

**D. Build / refresh the index substrate (`gloop index`).** Register a fleet at pinned SHAs and build the
shareable `atlas.db` (FTS5 unit-membership over doc + symbol units) that is the matching primitive.
Honors the reuse contract (`bge-m3` pinned, stable names, pinned SHAs, unchanged schema) so the artifact
is portable — build once where CBM runs, ship the `.db` elsewhere. See [m1-index-build.md](m1-index-build.md)
and [engines.md](engines.md).

**E. Operate the engines (`gloop produce`, `gloop doctor`).** `produce` generates a CodeWiki for a repo;
`doctor` resolves and reports CBM/index readiness. Supporting scenarios, not the loop itself. Runbook:
[type2-eval-setup.md](type2-eval-setup.md).

**F. Mine benchmark tickets from real issues (`gloop mine` — ASPIRATIONAL, not built).** The designed
data path: per-repo history mirror → link `issue ↔ fix_commit ↔ changed_files` → emit a `Ticket` (symptom
text + logs, **owner not written in**) plus a hidden `Oracle` (`owning_repo`, `expected_files`,
`fix_patch`). Ground truth is free: an issue in repo R is owned by R; the fix commit's changed files are
the localization oracle. The current CLI is `gloop {run, index, produce, doctor}` only — there is no
`gloop mine` yet.

## 4. What makes it non-trivial (the load-bearing properties)

- **Matching among *confusable* repos.** The fleet is chosen for lexically distinct namespaces so hard
  negatives make selection genuinely hard and a `1/N` guess scores far below a real match.
- **Owner = predicted output + hidden oracle, never a loop input.** Enforced *structurally* — `run_ticket`
  has no oracle parameter, and `grade()` is a plain offline function, not a port the core holds.
- **Anti-leak (benchmark integrity).** The owner must not appear in any loop-visible ticket field and the
  loop must never read the oracle. Locked by `tests/test_invariants.py` (see §5).
- **Grounded refusal beats confident guessing.** A metric that rewards guessing over an honest
  "insufficient evidence" is considered broken; the scorecard reports a selective / risk–coverage view.
- **Logs are the primary evidence.** The `Signals` shape *is* the log-derived discriminators.
- **Cost & model portability are first-class** (`$/ticket-matched`, `$/solved`); provider-agnostic.

The evidence for *why the matching premise holds* (cross-repo grounding vs an intra-repo null) lives in
[charter.md](charter.md) — this guide does not restate it.

## 5. How it is developed and evaluated — the two-part test design

The test design has **two parts**, cross-cutting every scenario above. They ask two different questions
and are held to two different standards — this is the canonical two-surface strategy in full detail at
[groundloop-testing-strategy.md](groundloop-testing-strategy.md):

- **Test 1 — System development testing** *(= Type-1; "is the code **correct**?")*. Hermetic and
  deterministic: **no network, no real LLM**, mock adapters + a 4-repo fixture `atlas.db`. Runs on every
  change. This is where Stage-1 matching **correctness and integrity** are proven — including the
  anti-leak invariants (`tests/test_invariants.py`) and the bridge test
  (`test_atlas_matcher_honors_invariants`) asserting the **real** `AtlasIndex` picks the owner *from log
  signals alone*, deterministically, over an N≥3 field on evidence — not a guess.

- **Test 2 — Overall evaluation** *(= Type-2; "is the system **effective**?")*. Graded, over **real
  models + a real `atlas.db`** on the corpora fleet: a scorecard of `recall@k`/MRR, per-repo confusion,
  cost, and grounded-refusal. This is where Stage-1 matching **effectiveness** is measured. It is
  **largely pending**: the multi-ticket arms harness + scorecard are the core Type-2 build; today only
  the `grade()` seed and the live build-acceptance tests (`tests/e2e/`, `skipif`-gated) exist.

**Why the split.** Correctness is deterministic, so it belongs in the hermetic development surface;
effectiveness is stochastic (live models), so it belongs in the graded evaluation surface. Re-checking
matching *accuracy* live would be flaky by construction and redundant with the Type-1 bridge test — so
the two surfaces divide the labor deliberately, they do not overlap it.

## 6. The estate it ranges over (fleet layers)

The application ranges over a fleet that **grows by requirement** — four distinct layers (full
reconciliation in [charter.md](charter.md)):

- **Target (production goal):** 130+ AAOS vehicle repos on Gerrit/JIRA.
- **Charter pilot:** ~11 OSS Android-IVI repos (GitHub-issue-derived proxy tickets + hard negatives).
- **Built corpora:** 3 repos at pinned SHAs (`android-gpuimage-plus`, `libxcam`, `ndk-samples`).
- **Hermetic fixture:** 4 repos (the Type-1 no-network matcher tests).

## 7. What GroundLoop is NOT (scope)

- **Not a JIRA/Gerrit synchronization tool** — the problem is the ticket→repo→code→fix→binding loop, not
  ticket sync. Real enterprise JIRA/Gerrit are **mocked** initially.
- **Not the full 130+-repo fleet yet** — a curated confusable pilot proves the pipeline first.
- **The fix stage is a stub** — `CannedFixEngine` until the real agentic engine lands.
- Further non-goals (no ANN yet, no Tier-3 build/test grading, no plugin framework): [charter.md](charter.md) §8.

## See also
- [charter.md](charter.md) — mission, FR/NFR, metrics, fleet layers, glossary.
- [architecture.md](architecture.md) — ports & adapters, `run_ticket`, migration.
- [roadmap.md](roadmap.md) — mining, the two-stage matcher, milestone tracks.
- [groundloop-testing-strategy.md](groundloop-testing-strategy.md) — the two test surfaces in full.
- [STATUS.md](STATUS.md) — current state and blockers · [../CLAUDE.md](../CLAUDE.md) — project orientation.
