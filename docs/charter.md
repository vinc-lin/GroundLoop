# GroundLoop — Charter & Requirements

> **Status:** foundational charter. Defines *why* GroundLoop exists, *what* it must do, and the
> requirements it is measured against. Implementation-light; the *how* lives in
> [architecture.md](architecture.md), [engines.md](engines.md), and [roadmap.md](roadmap.md).
> Current state / blockers / next steps: [STATUS.md](STATUS.md).
> Project orientation: [../CLAUDE.md](../CLAUDE.md).
>
> **Name note.** "GroundLoop" is the **integrated system**; absorbed source charters that say
> "KnowledgeLoop" mean GroundLoop. The `knowledgeLoop` repo is the migration **source engine** (a
> separate live repo); `bfl` / "Bug-Fixing-Loop" is the loop-agent sibling fix-loop experiment. Absorbed
> from [../../loop-agent/docs/knowledgeloop-background-and-requirements.md](../../loop-agent/docs/knowledgeloop-background-and-requirements.md).

---

## 1. Mission & the real problem

Android in-vehicle infotainment (IVI / Android Automotive, "AAOS") software for a single vehicle
program is spread across **130+ code repositories** with overlapping module relationships (apps,
framework, HALs, vendor middleware, AIDL/HIDL interfaces, native libraries, build/config), hosted on
**Gerrit** via `repo` manifests with `Change-Id` trailers.

When a tester finds a defect they file a **JIRA Bug ticket** with a description, repro steps, and —
most importantly — **failure logs** (logcat, Java/Kotlin stack traces, native `#00 pc …` backtraces,
ANRs, tombstones). Nearly every ticket carries logs, so **logs are the primary evidence** for the two
decisions that follow: **ownership** (which repo owns the defect) and **root cause** (which code path).
Today this is manual — a senior engineer reads ticket + logs, guesses which of the 130+ repos owns it,
then hunts the code: slow, experience-dependent, and prone to mis-routing.

**Mission.** An automated, traceable **closed loop** from a **JIRA defect ticket + failure logs** to a
**code fix** across the full 130+‑repo estate:

```
ticket + logs → MATCH owning repo → localize → fix → bind (JIRA ↔ commit)
```

The problem is **not** JIRA synchronization. It is building the ticket → repo → code → fix → binding
loop, with **ticket‑to‑repo matching as the core objective**. Downstream stages have practical value
only against tickets whose owning repo was identified correctly.

**One system, two uses — bridged by a hidden oracle.** GroundLoop is at once a **pipeline** (a real fix
attempt on a ticket) and a **benchmark** (the *same* loop instrumented so each stage — above all Stage‑1
match accuracy and cost — is scored over labeled data as A/B‑able arms). The bridge is the **hidden
oracle**: the loop never sees ground truth; an offline `grade(record, oracle)` pass reads it *afterward*,
so one run is both a fix attempt and a scored eval case.

**Load-bearing invariant.** The owning repo is a **predicted output + hidden-oracle field, never a loop
input.** This supersedes `bfl`'s `repo.json` (which handed the owning repo *in* as an input) — GroundLoop
predicts it and grades against a hidden oracle the loop never sees. See §4.

GroundLoop realizes this as a hexagonal control plane: the deterministic Python `run_ticket`
(`groundloop/core/`) sequences the stages; the LLM never owns control flow. Full design in
[architecture.md](architecture.md).

## 2. The four stages

`run_ticket` stages, in order: **intake → extract → match → materialize → localize → fix → submit →
bind.** These map onto four objective stages:

| Stage | Takes | Produces | Priority |
|---|---|---|---|
| **1 — Repo MATCH** | ticket text + extracted signals + fleet catalog | owning repo, **top‑k with confidence** (`rank_repos → [RepoScore]`, top‑1 = prediction) | **PRIMARY / now** |
| 2 — Localization | matched repo work-tree + signals | suspicious files / functions / APIs / call chains | Next |
| 3 — Fix assistance | localized repo + ticket | candidate fix (patch) | Later |
| 4 — Binding & tracking | commit/PR + ticket | append‑only auditable chain (discovery → logs → repo → localization → fix → PR/commit ↔ ticket) | Later |

**Stage‑1 is the gate** — downstream stages are pursued only against correctly‑matched tickets. Stage 3
today is a **`CannedFixEngine` stub** (design provenance: [fix-loop.md](fix-loop.md)).

## 3. Requirements catalog

Numbering is load-bearing — [evaluation.md](evaluation.md) cites these
by number.

### 3.1 Functional requirements

- **FR-1 Ticket ingestion.** Ingest a defect ticket (description, metadata, comments) **and its log
  attachments**. JIRA is **mocked** initially (real enterprise JIRA/Gerrit integration is out of current
  scope); the mock must faithfully carry real log payloads. *(Adapter: `adapters/mock/` MockJira.)*
- **FR-2 Log parsing & signal extraction. — SHIPPED.** Parse Android failure logs (logcat, Java/Kotlin
  stack traces, native `#00 pc …` backtraces, ANR/tombstone fragments) into **structured signals**:
  exception/error types, stack frames, fully‑qualified package/class/method names, process/module names,
  shared‑library (`.so`) names, error codes. *Shipped as `domains/android_ivi/signal_extractor.py`
  (`AndroidSignalExtractor`, the `SignalExtractor` port).*
- **FR-3 Repo matching (core).** Rank the **owning repo** among the fleet from ticket text + extracted
  signals, returning **top‑k with confidence**. The owning repo is a **predicted output, never an input**
  to the matcher. *(Port: `CodeIndex.rank_repos`; real adapter: `AtlasIndex` FTS5 matcher over an
  atlas.db.)*
- **FR-4 Code localization.** Within the matched repo, localize suspicious files / functions / APIs /
  call chains, reusing the grounded localization + retrieval machinery. *(Port: `CodeIndex.retrieve`.)*
- **FR-5 Root‑cause assistance & fix proposal.** Assist analysis and emit a candidate fix (patch).
  *(Port: `FixEngine.propose`; current adapter: `CannedFixEngine` stub.)*
- **FR-6 Binding & traceability.** On commit/PR, bind the fix to the originating ticket and persist an
  append‑only, auditable chain (discovery → logs → repo → localization → fix → PR/commit).
  *(Port: `ChangeSink.submit` + `ChangeSink.bind`.)*
- **FR-7 Evaluation / benchmark.** Measure each stage — especially **repo‑match accuracy and cost** —
  over labeled data, as A/B‑able arms, with per‑repo breakdowns. *(Offline `grade(record, oracle) →
  Scores` in `groundloop/grade/grader.py` — a function, not a port; the loop never sees it.)*
- **FR-8 Repo‑fleet management.** Register, index, and keep fresh a fleet of many repos (pilot: an OSS
  IVI proxy fleet; target: the 130+ vehicle repos) to match against. *(Ports: `RepoEstate`; build path:
  `gloop index`. See [build-setup.md](build-setup.md).)*

### 3.2 Non‑functional requirements

- **NFR-1 Grounding over narrative.** Every automated decision is backed by reality‑verifiable signals
  (a matched symbol must actually exist in the repo; a cited file must resolve). The loop **never sees the
  grading oracle**; grading is a separate offline pass. Unverifiable LLM prose is the thing to distrust.
- **NFR-2 Model portability & cost‑awareness.** Provider‑agnostic (see §8). Cost is a first‑class metric —
  report `$/solved` and `$/ticket‑matched`; optimize quality per dollar.
- **NFR-3 Scale.** Matching + indexing scale toward **130+ repos** (millions of symbols) with acceptable
  latency/memory; the first‑stage filter must not depend on an O(all‑units) scan.
- **NFR-4 Anti‑leakage.** Benchmark integrity: the base premise is `fix^` with the fix and **all** later
  history scrubbed; fix‑added tests kept out of the loop's repo; the **owning repo and answer must not
  appear in the ticket** the loop reads (they live only in the hidden oracle). Locked by
  `tests/test_invariants.py`.
- **NFR-5 Traceability / auditability.** Append‑only event log; every graded artifact is grounded and
  reproducible; the ticket ↔ fix chain is queryable.
- **NFR-6 Determinism of control flow.** Sequencing, state, and termination are deterministic Python
  (control plane, `core/run_ticket`); the LLM (cognition plane) never owns control flow.
- **NFR-7 Security & privacy.** Redact PII/secrets from ingested logs; never commit credentials, tokens,
  LAN IPs, or internal endpoints; respect enterprise data boundaries. (`.env` gitignored; config env‑only.)
- **NFR-8 Reproducibility.** Pinned repo SHAs; hermetic, no‑network test suite (Type‑1); live tests gated
  on credentials (Type‑2). See [evaluation.md](evaluation.md).

## 4. Success metrics & integrity

**Stage‑1 (primary).** Repo‑match **Recall@1** and **Recall@k**, **MRR** over a labeled
(ticket+logs → owning‑repo) set; **cost per matched ticket** (`$/ticket‑matched`); and a triage‑effort
proxy (rank of the correct repo).

**Downstream.** Localization **file‑recall@k**, **resolved rate**, and **`$/solved`**.

**Integrity — the anti-leak contract.** Metrics are measured only on **genuinely‑buggy, non‑leaking**
cases (real premises at the pinned SHA; owning repo hidden). Definitions:

- **Hidden oracle.** Ground truth (owning repo + fix) used only by the offline grader, never seen by the
  loop.
- **No leakage.** Owning repo / answer absent from the ticket the loop reads; base = `fix^` with fix and
  later history scrubbed (NFR-4).
- **Grounded refusal.** A confident wrong guess is worse than an honest "insufficient evidence." **A
  metric that rewards guessing over grounded refusal is considered broken.**

## 5. Data & test-material strategy

Real enterprise JIRA tickets and AAOS platform code are **not available** on the dev box, so the pilot
uses a **proxy fleet of popular, well‑maintained open‑source Android‑IVI repos** — spanning the real IVI
function map (media, navigation, camera/graphics, audio, automotive middleware) — with **mock JIRA
tickets derived from those repos' real GitHub issues**. The dev‑box‑proxy vs production split — and why
proxy numbers flatter the mechanism (tag every efficacy number `[proxy]`/`[production]`) — is canonical
in [environments.md](environments.md). Verified signal counts (2026‑07‑04, from the absorbed charter):

- **The signal is real.** GitHub issues on these repos carry stack traces whose frames **name the owning
  repo's namespace** — `androidx/media` has **367** issues quoting `at androidx.media3.…`; `organicmaps`
  has **57** issues with native backtraces referencing `storage::Storage::…` /
  `organicmaps/.../jni_helper.cpp`. This is exactly the ticket→repo signal FR-3 exploits.
- **Ground truth is free.** An issue filed in repo R is owned by R; the fix commit's changed‑file list
  gives the downstream localization oracle.
- **Caveats.** Issue **bodies** (the logs) live on GitHub → require a network fetch or synthesis; some
  proxy repos are shallow/archived and need full‑history clones for mining; a handful of repos makes
  matching trivial, so a **diverse multi‑repo fleet + hard negatives** is required (FR-8).

## 6. Fleet-layer reconciliation

These are **different layers, not a contradiction**; the eval fleet **grows by requirement**.

| Layer | Membership | Purpose |
|---|---|---|
| **Target (production goal)** | **130+** AAOS vehicle repos on Gerrit/JIRA | the real estate GroundLoop must scale to (NFR-3) |
| **Charter pilot** | **~11** OSS IVI repos (androidx/media, google/ExoPlayer, TeamNewPipe/NewPipe, AntennaPod, google/oboe, organicmaps, osmandapp/OsmAnd, natario1/CameraView, wysaid/android-gpuimage-plus, android/car-samples, COVESA/dlt-daemon) | GitHub‑issue‑derived proxy tickets + hard negatives; **finalized eval fleet (9) → [`evaluation.md`](evaluation.md) §3.1** (drops ExoPlayer→absorbed into media3, car-samples→0 linkage) |
| **Built corpora** | **3** at pinned SHAs — android-gpuimage-plus, libxcam, ndk-samples (`/mnt/x/code/corpora/corpus.toml`, a sibling dir — not in-repo) | real atlas.db substrate for Type‑2 live eval |
| **Hermetic GL‑M1 fixture** | **4** repos (hand-built fixture atlas.db) | Type‑1 no‑network matcher tests |

## 7. Why the matching premise holds — evidence

> Distilled from [../../knowledgeLoop/docs/concept-evaluation.md](../../knowledgeLoop/docs/concept-evaluation.md)
> and [../../knowledgeLoop/docs/token-cost-demonstration-findings.md](../../knowledgeLoop/docs/token-cost-demonstration-findings.md).
> All numbers below are **directional, proxy-side** (`[proxy]` — OSS corpora, N≈15, small task families,
> single-model laps): not settled measurement, not production efficacy. Read accordingly.

The matcher's bet is that **cross-repo grounding surfaces knowledge an agent cannot reach itself.** The
concept evaluation isolates exactly this, and the split is clean in both directions:

- **Null intra-repo.** On single‑repo tasks the agent's own `grep` is already optimal — every arm
  (including the no‑KB control) scored ~100%; the grounded retriever was **redundant with grep**. On its
  home turf the substrate adds nothing.
- **Large, real cross-repo lift.** When the needed symbol is *structurally un‑greppable from the task's
  repo* (it lives in a sibling repo absent from the work‑tree), value appears: on 15 non‑guessable
  cross‑repo helpers across two codebases (libxcam, gpuimage), the no‑KB control succeeded **1/15 (7%)**
  while the agent shown the un‑greppable prior art used the exact helper **10/15 (67%)** — a **+60pp**
  ceiling. With realistic adoption the lift was **+40pp**.

**Why this validates GroundLoop's Stage‑1.** Ticket→repo matching over 130+ repos *is* the cross‑repo
regime by construction: the owning repo is one of many, and the discriminating signal lives outside the
ticket's local context. The evidence says grounding pays off precisely where GroundLoop operates — and
that the lift should be **roughly capability‑invariant** (no amount of reasoning conjures a repo the model
has never seen).

**One cost line** (token-cost demonstration, libxcam, N=9 common tasks): injected cross‑repo context
lifts **every** model off a near‑zero floor — Haiku **0→44%**, Sonnet **22→78%** — so *context is the
dominant lever, not model tier.* (The per‑`$` figures in that doc used a biased token estimate and are
**retracted**; only the success figures stand.)

## 8. Model matrix

Provider‑agnostic by design (NFR-2). Three model roles, decoupled:

| Role | GroundLoop default | Notes |
|---|---|---|
| **Generation** (produce / cognition) | **`deepseek-chat`** | Live‑validated default. The environment's gateway serves DeepSeek + Qwen + embedders (no OpenAI). The migrated produce stack's model is configurable via `MAIN_MODEL` (code default `claude-sonnet-4`, fallback `glm-4p5`); `deepseek-chat` is the gateway‑validated working default here. `deepseek-reasoner` also available. |
| **Embedding** (matcher retrieval) | **`bge-m3`** (`KLOOP_EMBED_MODEL`) | Pinned — see integrity constraint below. |
| **Measured agent** (portability) | DeepSeek default · **Qwen gated** · **Claude gated** | Qwen is a portability target; Claude needs a real key. Live model testing here is DeepSeek‑primary. |

**Integrity constraint — the bge-m3 reuse contract.** The query‑time embedder **MUST equal** the
index‑time embedder, because the vectors table stores **raw** embeddings — a mismatch silently corrupts
cosine ranking. `bge-m3` is pinned at both index and query time; changing it forces a **full re‑index**.
Together with stable repo names, pinned SHAs, a shared atlas.db path, and an unchanged store schema, this
keeps an atlas.db shareable. Engine operations: [engines.md](engines.md).

## 9. Glossary

- **Owning repo** — the repository that contains the defect (and where the fix lands). Stage‑1 prediction
  target; a predicted output + hidden‑oracle field, **never a loop input**.
- **Repo‑atlas / atlas.db** — the cross‑repo SQLite index of code units; every hit is tagged with its
  owning repo (the core matching primitive). Built by `gloop index`.
- **Fleet** — the set of N candidate repos the matcher ranks against (see §6).
- **Signals** — structured discriminators extracted from logs (FR-2): exception types, stack frames,
  package/class/method names, process/module names, `.so` names, error codes.
- **Grounding** — verifying a claim against reality (code, tests, logs) rather than trusting LLM prose.
- **Oracle** — hidden ground truth used only by the offline grader, never seen by the loop.
- **CBM** — Codebase-Memory (`codebase-memory-mcp==0.8.1`), the code‑graph backend behind localization.
- **Type‑1 / Type‑2** — hermetic no‑network tests / live‑eval with real models + real atlas.db.

## 10. Non-goals & YAGNI

- Real enterprise JIRA and Gerrit integration (handled elsewhere; only a **mock** JIRA/Gerrit layer here).
- The **full 130+-repo fleet** — a curated, confusable OSS pilot proves the pipeline before scale (§6).
- Autonomous agent frameworks that own control flow (**rejected** — code‑driven sequencing owns it,
  NFR-6).
- Full AOSP build/test execution as the primary grader for the pilot (a deferred sub‑project).
- A production UI / ticketing workflow.
- A multi‑domain plugin framework — the domain seam (`domains/`) exists, but no plugin machinery yet
  (YAGNI).
- `gloop mine` and a two‑stage matcher are **forward‑looking** — tracked in [roadmap.md](roadmap.md),
  not built.

---

*Milestone note:* GroundLoop milestones are **GL‑M0** (walking skeleton, landed) and **GL‑M1** (real
`AtlasIndex` + `gloop index`/`produce`/`doctor`, landed). The loop-agent fix-loop track (**BFL‑M0..M9**)
and the repo-matching integration **spec M1–M5** are separate tracks — never a bare "M1".
