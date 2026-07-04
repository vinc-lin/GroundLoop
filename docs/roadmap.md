# GroundLoop — Roadmap

Forward plan for Stage-1 (ticket→repo matching) and the data substrate beneath it. Absorbs the
repo-matching integration design and the fix-loop precedent, re-skinned to GroundLoop conventions.
For the live state read [STATUS.md](STATUS.md) first; for the frozen contracts see
[charter.md](charter.md), [architecture.md](architecture.md), [engines.md](engines.md), and
[downstream-fix-loop.md](downstream-fix-loop.md).

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
query time, store schema unchanged. Full build/consume detail: [m1-index-build.md](m1-index-build.md).

Live state, the current blocker (the pinned `bge-m3` embedding host is down), and the immediate next
steps are tracked in [STATUS.md](STATUS.md) — that file is authoritative over this section.

## 2. Pilot fleet & log-richness

Stage-1 only becomes non-trivial when the fleet is large and lexically confusable, so a `1/N` guess
scores far below a real match. The layers (distinct concerns, not a contradiction):

- **Target** — 130+ AAOS in-vehicle repos (the production goal).
- **Charter pilot** — ~11 OSS Android-IVI repos spanning the IVI function map (see [charter.md](charter.md)).
- **Built corpora** — 3 repos at pinned SHAs in `corpora/corpus.toml`: `android-gpuimage-plus`,
  `libxcam`, `ndk-samples`.
- **Hermetic GL-M1 fixture** — 4 repos in the Type-1 substrate (see
  [groundloop-testing-strategy.md](groundloop-testing-strategy.md)).

Proposed pilot (verified live 2026-07-04; final membership confirmable), chosen for lexically distinct
namespaces so repo selection is genuinely hard:

| Function | Repos |
|---|---|
| Media / audio | `androidx/media`, `google/ExoPlayer`, `TeamNewPipe/NewPipe`, `AntennaPod`, `google/oboe` |
| Navigation | `organicmaps/organicmaps`, `osmandapp/OsmAnd` |
| Camera / graphics | `natario1/CameraView`, `wysaid/android-gpuimage-plus` |
| Automotive authenticity | `android/car-samples`, `COVESA/dlt-daemon` |

Distinct namespaces (`androidx.media3.*`, `org.schabi.newpipe.*`, `app.organicmaps.*`, `net.osmand.*`,
`com.otaliastudios.cameraview.*`, `org.wysaid.*`, `androidx.car.app.*`, …) yield clean positive /
hard-negative pairs. Distractor slots are reserved for scaling toward 130+.

**Log-richness (confirmed):** `androidx/media` has **367 stack-trace issues**; `organicmaps` has **57
native-backtrace issues**. `NewPipe`, `OsmAnd`, and `CameraView` are to be sampled before final
lock-in. Log-rich repos are prioritized because logs are the signal that makes matching learnable.

## 3. Mining pipeline — `gloop mine` (NOT built yet)

**Aspirational: there is no `gloop mine` subcommand today** (the CLI is `gloop {run, index, produce,
doctor}` only). This is the design for it. It produces benchmark entries from real GitHub issues,
offline-groundable where possible, each carrying a **hidden `owning_repo`**.

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
GL-M1 shipped stage (a) below; stage (b) is the forward work.

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

(b) **Second-stage semantic rerank (FORWARD).** The second stage will wire the atlas semantic retrieve
(`find_related`) behind `CodeIndex.retrieve` — replacing today's FTS5-keyword `retrieve` (a within-repo
keyword search via `store.keyword_search`) — restricting it with the shortlist as a `u.repo IN (…)`
filter; query = ticket text + top signals; every hit carries its `repo`. **Fuse the exact-membership and
semantic evidence with Reciprocal Rank Fusion (RRF)** into a per-repo score → top-k owning repos. The
pipeline materializes the top-1 (or explores top-k) downstream.

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
the per-repo aggregation grouped by `hit['repo']`), applied to ranked repos. That harness is not yet
migrated into GroundLoop. Grading stays a separate offline pass — the loop never sees the oracle.

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

- **Real `RepoEstate`** — materialize the top-1 (or top-k) predicted repo at `@base` for localization
  (today `MockEstate`).
- **Real `AgentFixEngine`** — the `fix` stage is currently a `CannedFixEngine` stub; the real agentic
  fix engine is the largest downstream item. Design provenance and the localize/fix/grade contracts live
  in [downstream-fix-loop.md](downstream-fix-loop.md).
- **Eval-env harness** — the Type-2 live-eval surface (real models + a real atlas.db) over the grown
  fleet; runbook in [type2-eval-setup.md](type2-eval-setup.md). Follow-ons: ANN vector index, PR/JIRA
  binding scaffold (Stage-4), and Tier-3 build/test grading.

Immediate gating item (from [STATUS.md](STATUS.md)): the pinned `bge-m3` host must return healthy before
the full `gloop index` build and the gated live tests can run. Then the eval fleet grows by uncommenting
the additional built corpora so a real match is clearly separable from a `1/N` guess.

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
  semantic rerank), M4 the matching benchmark, M5 downstream reuse. Its "M3" is the matcher, unrelated to
  any GroundLoop or bfl M3.
- **BFL-M0…M9** belong to the loop-agent fix-loop track and are done there; GroundLoop reuses its lessons
  (§6) and its localize→fix machinery ([downstream-fix-loop.md](downstream-fix-loop.md)), not its
  milestone numbers.

See [charter.md](charter.md) for the mission and FR/NFR catalog, [architecture.md](architecture.md) for
the ports & adapters seam, and [../CLAUDE.md](../CLAUDE.md) for durable project orientation.
