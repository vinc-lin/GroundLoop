# GroundLoop — Roadmap

Forward plan for Stage-1 (ticket→repo matching) and the data substrate beneath it. Absorbs the
repo-matching integration design and the fix-loop precedent, re-skinned to GroundLoop conventions.
For the live state read [STATUS.md](STATUS.md) first; for the frozen contracts see
[charter.md](charter.md), [architecture.md](architecture.md), [engines.md](engines.md), and
[fix-loop.md](fix-loop.md).

Source designs (reference, not copied): the integration spec
[`../../loop-agent/docs/superpowers/specs/2026-07-04-knowledgeloop-repo-matching-integration-design.md`](../../loop-agent/docs/superpowers/specs/2026-07-04-knowledgeloop-repo-matching-integration-design.md)
and the fix-loop roadmap [`../../loop-agent/docs/roadmap.md`](../../loop-agent/docs/roadmap.md). The
integration spec calls the integrated system "KnowledgeLoop" — that IS GroundLoop.

## 1. Where we are

**GL-M0 (walking skeleton) and GL-M1 (real `AtlasIndex` + `gloop index/produce/doctor`) have LANDED.**
The deterministic `run_ticket` control plane (intake → extract → match → materialize → localize → fix →
submit → bind) runs green over the hermetic substrate; the `match` stage now ranks over a real
FTS5-backed atlas.db via the `CodeIndex` port (`AtlasIndex.rank_repos`), discriminating the owning repo
from hard negatives on a hand-built fixture db. Reuse contract honored: `bge-m3` pinned at index +
query time, store schema unchanged. Full build/consume detail: [build-setup.md](build-setup.md).

Live state, blockers, and next steps live in [STATUS.md](STATUS.md) (authoritative over this section);
the dev-box-vs-production split and the `[proxy]`/`[production]` result tags are in [environments.md](environments.md).

> **Status update (2026-07-11) — much of this forward plan has shipped.** Beyond GL-M0/M1: `gloop mine`
> (+ `mine-affinity`) and the `groundloop/eval/` harness (`gloop eval` / `funceval` / `faulteval`), semantic
> retrieval + **RRF fusion**, real materialization (`GitFixtureEstate` / `CheckoutEstate`), the real fix
> engine `ModelPatchEngine` (via `gloop fixeval` / `gloop run --fixer model`), and self-scoring (`gloop run
> --out` → `gloop grade-run`). New matcher **arms** that post-date this doc — **component-routing,
> functional-bug, fault-routing** — are the current Stage-1 frontier. **[STATUS.md](STATUS.md) +
> [results-log.md](results-log.md) are authoritative for state + measured numbers; `CLAUDE.md` for the
> current CLI.** The sections below are kept for design rationale — read any "aspirational / forward /
> not-built" wording against this note.

## 2. Pilot fleet & log-richness

Stage-1 only becomes non-trivial when the fleet is large and lexically confusable, so a `1/N` guess
scores far below a real match. The layers (distinct concerns, not a contradiction):

- **Target** — 130+ AAOS in-vehicle repos (the production goal).
- **Charter pilot** — ~11 OSS Android-IVI repos spanning the IVI function map (see [charter.md](charter.md)).
  The **finalized Type-2 eval fleet (9 repos)** — after a feasibility sweep dropping ExoPlayer + car-samples
  — is defined in [evaluation.md](evaluation.md) §3.1.
- **Built corpora** — 3 repos at pinned SHAs in `corpora/corpus.toml`: `android-gpuimage-plus`,
  `libxcam`, `ndk-samples`.
- **Hermetic GL-M1 fixture** — 4 repos in the Type-1 substrate (see
  [evaluation.md](evaluation.md)).

Proposed pilot (verified live 2026-07-04; final membership confirmable), chosen for lexically distinct
namespaces so repo selection is genuinely hard:

| Function | Repos |
|---|---|
| Media / audio | `androidx/media`, `google/ExoPlayer`, `TeamNewPipe/NewPipe`, `AntennaPod`, `google/oboe` |
| Navigation | `organicmaps/organicmaps`, `osmandapp/OsmAnd` |
| Camera / graphics | `natario1/CameraView`, `wysaid/android-gpuimage-plus` |
| Automotive authenticity | `android/car-samples`, `COVESA/dlt-daemon` |

Distinct namespaces (`androidx.media3.*`, `net.osmand.*`, `org.wysaid.*`, `androidx.car.app.*`, …) yield
clean positive / hard-negative pairs. Distractor slots are reserved for scaling toward 130+.

**Log-richness (confirmed):** `androidx/media` has **367 stack-trace issues**; `organicmaps` has **57
native-backtrace issues**. `NewPipe`, `OsmAnd`, and `CameraView` are to be sampled before final
lock-in. Log-rich repos are prioritized because logs are the signal that makes matching learnable.

## 3. Mining pipeline — `gloop mine`

**SHIPPED** — `gloop mine` (+ `gloop mine-affinity` for the component→repo prior) is built; this section is
its design rationale. It produces benchmark entries from real GitHub issues, offline-groundable where
possible, each carrying a **hidden `owning_repo`**. (Full current CLI: `CLAUDE.md`.)

1. **Fetch full history** — ensure a full or blobless bare mirror per fleet repo (`corpora/.mirrors/<repo>.git`).
   Never mutate the shared working checkout used to materialize `@base`; the mined corpus is never depth-1.
2. **Link issue ↔ fix commit ↔ files** — scan commit messages for `fix #N` / `issue #N` / issue URLs;
   record `(issue_number, fix_commit, base=fix^, changed_source_files)`. The changed files are the
   localization oracle. Filter to genuine code fixes touching 1–3 source files.
3. **Fetch the issue body** (network) — title, body, comments, labels: the logs / stack traces / repro
   steps. Store raw under `<KEY>/logs/`. Fallback: synthesize a symptom-only description (clearly
   flagged synthetic) where issue bodies are unavailable.
4. **Redact** — strip PII/secrets from logs before persisting (secret hygiene / NFR-7).
5. **Emit entry** — a `Ticket` (description = symptom text; `attachments` reference `logs/` files; the
   owning repo is **NOT** written into the ticket) and a hidden `Oracle` (`owning_repo`,
   `localization.expected_files` = changed files, `fix_patch`, `issue` provenance). Update the
   candidate catalog + a subset manifest.

**Anti-leakage:** the owning repo lives only in the oracle; `@base` is a single-commit scrub of the fix
and all later history; test files are excluded from `@base`. This is the load-bearing invariant — **the
owning repo is a predicted output + hidden oracle field, never a loop input.** (This supersedes the
fix-loop precedent's `repo.json`, which supplied the owning repo as an *input*.) These invariants are
locked in as Type-1 red-tests today (`tests/test_invariants.py`).

## 4. The two-stage matcher

Given `ticket + logs`, the `match` stage of `run_ticket` produces a ranked list of candidate repos with
confidence via `CodeIndex.rank_repos(signals, catalog) -> [RepoScore]` (top-1 = predicted owning repo).
GL-M1 shipped stage (a) below; stage (b) (semantic rerank + RRF fusion) has since LANDED in the
matcher-arm family (the `--semantic` arm + RRF in the fault-routing / component-prior arms).

**Domain signal extraction (SHIPPED).** `AndroidSignalExtractor`
(`domains/android_ivi/signal_extractor.py`, the FR-2 `SignalExtractor` port) parses logcat / Java-Kotlin
stack traces / native backtraces / ANR fragments into structured signals: exception types,
fully-qualified frames (package/class/method), process/module names, `.so`/library names, error codes.

(a) **First-stage repo-membership shortlist (indexed, scalable — LANDED as `AtlasIndex`).** For each
extracted identifier, query the atlas **FTS5** unit index (`units_fts`, whose rows carry `u.repo`) — the
indexed, repo-tagged path that scales toward 130+ (~O(k·log n)) with no O(all-units) scan. Aggregate
hits **grouped by owning `repo`** → a candidate shortlist. A full-source token walk is precomputed per
indexed SHA (never per query); single-repo symbol existence is used only to *verify* membership inside
the shortlist, not for fleet-wide search.

(b) **Second-stage semantic rerank + RRF fusion — LANDED (in the arm family).** Semantic retrieval (the
`--semantic` eval arm) and **Reciprocal Rank Fusion (RRF)** shipped and are load-bearing in the
fault-routing and component-prior matcher arms. The originally-designed form: wire the atlas semantic
retrieve (`find_related`) behind `CodeIndex.retrieve` — replacing today's FTS5-keyword `retrieve` (a
within-repo keyword search via `store.keyword_search`) — restrict it with the shortlist as a `u.repo IN
(…)` filter (query = ticket text + top signals; every hit carries its `repo`), and fuse exact-membership +
semantic evidence via RRF into a per-repo score → top-k owning repos; materialize top-1 (or explore top-k)
downstream.

The embedder is pinned `bge-m3` and the **query-time embedder must equal the index-time embedder** — the
vectors table stores raw embeddings, so a mismatch silently corrupts cosine ranking and any change forces
a full re-index. Before the fleet grows large, an ANN backend (sqlite-vec / faiss) replaces the cosine
scan. (`Embedder` is an engine-internal Protocol in `engines/atlas/embed.py`, not a core port.)

## 5. Additive Ticket / Oracle schema

Additive only; existing single-repo entries stay valid.

- **`Ticket`** — `attachments` reference structured **log objects**
  (`{path, kind:'logcat'|'stacktrace'|'native'|'anr'|'other', content}`) under `<KEY>/logs/`; add an
  optional `extracted_signals` cache (populated by the FR-2 extractor). **Do not** store the owning repo
  on the ticket.
- **`Oracle`** — add `owning_repo: str` (hidden ground truth) and `issue: {number, url, fix_commit}`
  provenance; keep `localization.expected_files`, `fix_patch`, `rubric`, `base`.
- **Catalog** — a candidate-repo catalog (fleet snapshot the matcher ranks against), decoupled from any
  per-entry repo field. This is the `catalog` argument to `rank_repos`.

## 6. Matching metrics & A/B arms

**Metrics (new):** `repo_recall@1`, `repo_recall@k`, `repo_mrr`, per-repo confusion, and **cost per
matched ticket**. GroundLoop's current scorer is `grade(record, oracle) -> Scores` in
`groundloop/grade/grader.py` (today emitting `repo_recall_at_1` / `repo_rank` / `localization_recall` /
`bound`); the `@k` / `mrr` / `ndcg` metrics are the forward extension of it, ported from knowledgeLoop's
offline IR harness (`eval/offline/metrics.py` + `harness.py` — success@k / recall@k / ndcg@k / mrr plus
the per-repo aggregation grouped by `hit['repo']`), applied to ranked repos. **That harness is now
migrated** — `groundloop/eval/` (`metrics.py` / `scorecard.py` / `runner.py`), driving `gloop eval` /
`funceval` / `faulteval`. Grading stays a separate offline pass — the loop never sees the oracle.

**Arms** (matching strategy and signal set are measured, not assumed):

1. **exact-membership-only** (baseline) → **+ semantic rerank** → **+ LLM-judge**.
2. **text-only** vs **+logs** — to quantify how much the logs actually help (a cost/benefit question,
   NFR-2).

This mirrors the fix-loop discipline from [`../../loop-agent/docs/roadmap.md`](../../loop-agent/docs/roadmap.md):
each added mechanism lands as a **measured eval arm**; keep only what verifiably improves the headline
metric over its cost. Grounded precedent from that track worth carrying forward:

- A retrieval arm (grep vs none) came in **~25% cheaper with no loss of localization** on a real-sized
  repo — retrieval is a cost lever, and worth measuring as an arm rather than adopting on faith. The
  richer embeddings retriever is adopted *only if its arm beats the cheaper baseline*.
- On a **synthetic** seed the benchmark can *reward confident guessing and penalize honest grounding*
  (an investigate-then-refuse arm scored lower than an unverified-guess arm precisely because the bugs
  were fabricated). The lesson for Stage-1: **integrity requires a fleet large and diverse enough that
  guessing ≠ winning**, and reporting only over non-leaking entries with the owning repo hidden — else
  the numbers measure the seed, not the matcher.

## 7. Downstream phasing

Stage-1 feeds the existing localize → propose-fix pipeline; the stages after `match` harden in order:

- **Real `RepoEstate` (partially SHIPPED)** — `GitFixtureEstate` / `CheckoutEstate` materialize a predicted
  repo at a pinned SHA for `gloop fixeval` + `gloop run --repos`; the full `@base = fix^` history-scrub and a
  live 130-repo estate remain forward work. (Since the 2026-07-12 re-point, `gloop run --fixer model` — now
  the default — **requires** `--repos`/`CheckoutEstate` and fail-closes; `MockEstate` is hermetic-only.)
- **Real fix engine (SHIPPED + re-pointed to default)** — `ModelPatchEngine` is now the `gloop run` **default**
  fix stage (2026-07-12; fail-closed without creds/`--repos`), with `CannedFixEngine` demoted to the explicit
  hermetic Fixture. Remaining downstream: the live JIRA/Gerrit adapters (the traceable chain) + a Tier-2/3
  grader. Contracts: [fix-loop.md](fix-loop.md).
- **Dev-experience KB (a Candidate fix arm — PRODUCTION-GATED)** — the KB's fix-value verdict cannot be
  reached on the dev-box proxy: synth fires the KB but floors resolution at 0 (synthetic log ≠ the real fix),
  and the OSS fleet has only **~7–15** genuine crash-with-fix cases (2026-07-13 scout). It is
  AAOS-crash-specific, so a fair `resolved_rate` A/B needs real **production** AAOS crash+fix tickets. The
  harness is ready (`fixeval --skills-inject fix-only` + synth-planted `required_apis`); the A/B is spec'd as a
  production-side task ([`Phase 2 spec`](superpowers/specs/2026-07-13-kb-fair-eval-phase2-design.md)). Detail:
  [capabilities.md](capabilities.md) + [results-log.md](results-log.md) 2026-07-13.
- **Eval-env harness (SHIPPED)** — the Type-2 live-eval surface (real models + `atlas-9.db`) is built (`gloop
  eval` / `funceval` / `faulteval`); runbook in [build-setup.md](build-setup.md). Follow-ons: ANN vector
  index, PR/JIRA binding scaffold (Stage-4), Tier-3 build/test grading.

The former immediate blocker — the pinned `bge-m3` host being down — was **cleared 2026-07-05**; the full
`gloop index` build ran and the 9-repo `atlas-9.db` was produced. Growing the fleet toward 130+ (so a real
match is clearly separable from a `1/N` guess) is the standing scaling item; **production efficacy on the
real GEI corpus is the scoreboard** (see [environments.md](environments.md)).

## 8. Milestone-track reconciliation

Three **separate** milestone tracks share vocabulary but must never be conflated:

| Track | Numbering | Scope | State |
|---|---|---|---|
| **GroundLoop** | **GL-M0**, **GL-M1** | walking skeleton; real `AtlasIndex` + `gloop index/produce/doctor` | both **LANDED** |
| **Repo-matching integration spec** | **spec M1–M5** | shared substrate → mining → matcher → benchmark → downstream reuse | design (this doc absorbs it) |
| **Fix-loop (bfl) experiment** | **BFL-M0…M9** | the loop-agent sibling fix-loop MVP | separate repo, complete |

- **GL-M0/M1** are GroundLoop's own landed milestones — the only ones that describe *this* repo's built
  state. Always namespace them; never write a bare "M1".
- **spec M1–M5** is the integration design's internal numbering: M1 shared substrate (largely realized
  by GL-M1's shared atlas.db + registry), M2 mining, **M3 the matcher** (first-stage membership +
  semantic rerank), **M4 the matching benchmark** (specified in
  [evaluation.md](evaluation.md) — its eval-harness build stages E1–E3 are distinct from
  these milestone tracks), M5 downstream reuse. Its "M3" is the matcher, unrelated to
  any GroundLoop or bfl M3.
- **BFL-M0…M9** belong to the loop-agent fix-loop track and are done there; GroundLoop reuses its lessons
  (§6) and its localize→fix machinery ([fix-loop.md](fix-loop.md)), not its
  milestone numbers.

See [charter.md](charter.md) for the mission and FR/NFR catalog, [architecture.md](architecture.md) for
the ports & adapters seam, and [../CLAUDE.md](../CLAUDE.md) for durable project orientation.
