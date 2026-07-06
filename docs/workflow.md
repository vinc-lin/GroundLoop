# GroundLoop Workflow — How the Loop Works

An introduction to the GroundLoop pipeline: the deterministic closed loop that turns a **JIRA defect ticket +
failure logs** into a **repo-scoped code fix**, stage by stage, with real examples. This is the *conceptual*
companion to the [User Guide](user-guide.md) (how to operate it) and [architecture.md](architecture.md) (the
ports & adapters design).

---

## The closed loop

`groundloop/core/workflow.py::run_ticket` is a deterministic control plane that fires **8 events** by calling
**7 ports** (Protocols). It imports no concrete adapter — behavior is chosen at the composition root.

```
   intake       extract        match          materialize     localize       fix         submit       bind
 IssueSource  SignalExtractor  CodeIndex        RepoEstate     CodeIndex   FixEngine    ChangeSink   ChangeSink
   .fetch       .extract      .rank_repos    .materialize     .retrieve   .propose      .submit       .bind
     │             │              │               │               │           │            │            │
  Ticket ──────► Signals ────► RepoScore[] ──► WorkTree ──► locations[] ──► Patch ──► Change ──► JIRA↔commit
                              (top-1 = the                                (Model port
                             predicted owner)                            injected here)
```

Two ports each span two stages: **`CodeIndex`** does both *match* (cross-repo ranking) and *localize*
(in-repo file retrieval); **`RepoEstate`** does *catalog* (candidate fleet) and *materialize* (work-tree).

**The owning repo is a predicted output, never a loop input.** The ground-truth oracle is hidden; the loop
runs blind, and grading happens later, offline.

---

## Stage by stage

We thread one real case — **`oboe-2103`** (a native crash) — through all 8 stages, contrasting with
`newpipe-12489` (a Java crash, a match win) and `cameraview-26` (a match *miss*, showing the cascade).

### 1. Intake — `IssueSource.fetch(ticket_id) → Ticket`
The ticket is fetched (dev: `MockJira` reads `ticket.json`; prod: a JIRA adapter — a seam to build). It carries
only **loop-visible** fields: `summary`, `description`, and attached `logs` — never the owner.

> `oboe-2103`: summary *“OboeTester: add Intent for Dynamic CPU Load test”* + an attached native crash log.

### 2. Extract — `SignalExtractor.extract(logs, ticket) → Signals`
The domain pack (`AndroidSignalExtractor`) runs regexes over the log + ticket text to pull typed signals:
exception classes, `package.Class.method` frames, native symbols, and `lib*.so` names.

> `oboe-2103` → `libraries={liboboe.so}`, `symbols={DynamicWorkloadActivity::run, MainActivity::EnableAudioApiUI, …}`.
> `newpipe-12489` → `classes={org.schabi.newpipe.player.PlayerService, …}`, `errors={IllegalArgumentException}`.

### 3. Match — `CodeIndex.rank_repos(signals, catalog) → RepoScore[]`  ← the core objective
Each signal token is searched across the whole fleet over the **atlas** (a SQLite FTS5 index of code units).
A repo scores by the count of *distinct signal tokens that hit at least one unit* in it. The list is sorted;
**`ranked[0]` is the predicted owning repo.**

> `oboe-2103` → **oboe 4.0** vs android-gpuimage-plus 2.0 → predicted **oboe** ✓ (`liboboe.so` is unique to oboe).
> `newpipe-12489` → **newpipe 11.0** vs media3 9.0 → predicted **newpipe** ✓ (a narrow, size-tax margin).
> `cameraview-26` → **media3 9.0** vs osmand 9.0 vs cameraview 7.0 → predicted **media3 ✗** (the real owner,
> cameraview, is rank 3 — the *size-bias*: a small repo loses rank-1 to larger repos whose generic tokens
> accrue competing evidence).

### 4. Materialize — `RepoEstate.materialize(chosen) → WorkTree`
A work-tree for the chosen repo is provisioned (dev: an empty dir; prod: a git checkout at the indexed SHA via
`GitFixtureEstate`).

### 5. Localize — `CodeIndex.retrieve(chosen, query) → locations[]`
Retrieval, **restricted to the chosen repo**, returns the top candidate files for the fix. Localization is
strong *given the right repo* (file_recall ≈ 0.85@1) — but it runs on whatever match chose, so a match error
propagates.

> `oboe-2103` → 9 candidate files, **including the expected fix file** ✓.
> `cameraview-26` → localizes inside **media3** (the wrong repo) → the expected cameraview file cannot appear ✗.

### 6. Fix — `FixEngine.propose(worktree, ticket, locations) → Patch`
A patch is proposed over the candidate files. Prod: `ModelPatchEngine` asks the `Model` port (`GatewayModel`,
default `deepseek-chat`) for a unified diff. Dev / `gloop run`: `CannedFixEngine` emits a template diff. The
dev-experience **KB** can inject applicable playbooks into this prompt (see below).

> `oboe-2103` → a patch touching `…/oboetester/MainActivity.java`.

### 7. Submit — `ChangeSink.submit(repo, patch, ticket) → Change`
The patch becomes a change (dev: `MockGerrit` fabricates a Change-Id + appends a JSONL ledger; prod: a Gerrit /
GitHub-PR adapter — a seam to build).

> `oboe-2103` → change `I9bd268e9…`.

### 8. Bind — `ChangeSink.bind(change, ticket)`
The JIRA↔commit chain is written (dev: `MockJira` ledger + status transition). The loop completes:
`bound = True`.

All three example cases fire **all 8 events** and end `bound=True` — the difference is *correctness*, which is
graded separately.

---

## Under the hood: the atlas index & embedding

Stages 3 (match) and 5 (localize) both run over the **atlas** — a SQLite database of *code units*, each stored
in two searchable forms: an **FTS5 full-text row** (keyword search) and a **bge-m3 vector** (semantic search).
Understanding what gets embedded, and how, explains the two matching modes.

### What is a "unit", and what text is embedded

The atlas holds two kinds of unit (`groundloop/engines/atlas/index.py::build_units`):

- **Symbol units** — one per code symbol (class / method / function / …), enumerated by **CBM**
  (`codebase-memory-mcp`) from the repo's symbol graph. The text that gets indexed **and embedded** is *not*
  the raw file; it is a compact identity string (`_symbol_unit`):

  ```
  unit.text = "<name> <label> <qualified_name> <file_path>"        # e.g. "run Method oboe::DynamicWorkloadActivity::run  src/.../DynamicWorkloadActivity.cpp"
             + "\n<source snippet>"                                 # optionally: the symbol's own source lines
  ```
  i.e. GroundLoop embeds **symbol identity + location (+ its source)**, which is exactly the shape a crash-log
  signal (`package.Class.method`, a `.so` name) can match against.
- **Doc units** — chunks of generated CodeWiki markdown (optional; the shipped fleet atlas is largely
  *symbol-only* because CodeWiki `produce` is impractical at fleet scale, so doc units mostly feed the semantic
  arm when present).

Each unit also records its `repo`, `kind`, `file`, `qualified_name`, and the indexed **`repo_head` SHA**.

### How index-time embedding works

`index_repo` builds the units for a repo, then embeds them in one call
(`vecs = embedder.embed([u.text for u in units])`) and stores `(unit, vector)` pairs
(`Store.reindex_repo`, per-repo idempotent — it replaces only that repo's rows, so partial progress is durable).

`GatewayEmbedder` (`groundloop/engines/atlas/embed.py`) does the embedding:

- **Endpoint:** an OpenAI-compatible `POST <KLOOP_EMBED_BASE_URL>/embeddings` with
  `{"model": "bge-m3", "input": [chunk…]}`. bge-m3 returns **1024-dimensional** vectors.
- **Batching:** inputs are chunked at `KLOOP_EMBED_BATCH` (default 128; the GPU server caps `BGE_MAX_BATCH=256`).
- **Truncation:** each input is cut to `KLOOP_EMBED_MAX_CHARS` (default 2000) — a batch or input over the server
  caps returns **HTTP 413, a 4xx that is *not* retried**, so one oversized unit would abort the whole index.
  Truncation is quality-free (bge-m3's window is ~8192 tokens, so a longer input is truncated by the model
  regardless).
- **Resilience:** transient **5xx / transport** errors are retried with backoff (a single gateway hiccup
  mid-index doesn't abort the run); a hard 4xx raises.
- **Storage:** the raw vector is written to the `vectors` table as JSON floats (alongside the `units_fts` FTS5
  row and a `repos` row tagging `repo_head`).

Embedding is the real time cost of a build (a repo of ~30k symbols is hundreds of gateway round-trips); run the
index **detached**, one repo at a time.

### How query-time embedding works

The **same** pinned `bge-m3` model embeds queries at run time (the reuse contract — a construction-time
**dimension guard** in `SemanticAtlasIndex` fails loudly if the query model's dim ≠ the indexed dim, rather than
silently scoring everything `-1`):

- **Semantic match** (`SemanticAtlasIndex.rank_repos`): embed the joined signal tokens
  (`" ".join(signals.tokens())`) → `Store.vector_search` cosines that query vector against stored unit vectors
  (restricted to the catalog) → **each repo scores by its single best (max-cosine) hit** → sort.
- **Semantic localize** (`.retrieve`): embed the query → `vector_search` within the chosen repo → dedup files.
- **KB skill rerank** (`MockSkillRegistry` with an embedder): each Skill's `guidance` is embedded **once** at
  load; at query the ticket context is embedded and cosine-ranked to pick the top-k applicable playbooks.

### Membership vs. semantic — where embedding does and doesn't matter

This is the key point: **the `membership` arm uses no embedding at all.** It is pure **FTS5 keyword search** —
each signal token is matched against the `units_fts` index, and a repo scores by the count of distinct tokens
that hit. That FTS path is the arm behind the **0.60** headline, and it runs fully offline (**$0, no GPU**).

**Embedding powers the complementary `semantic` arm** (bge-m3 cosine), which is what recovers signal on *real
prose logs* — recall@1 **0.23** where membership collapses to 0.02 — plus the KB skill rerank. So the two are a
division of labor: **keyword membership for signal-rich logs, semantic embedding for prose.**

> **Limitation:** `Store.vector_search` is **brute-force** — it reads and cosines *every* stored vector in Python
> (1024 floats × ~475k units), so semantic search is slow at fleet scale. A real ANN index (sqlite-vss / faiss)
> is the eventual fix; see [user-guide §10](user-guide.md#10-known-seams--limitations).

---

## Oracle-blindness & offline grading

The loop is constructed with only the 7 behavioral ports — no oracle, no grader. The hidden
`_oracle/oracle.json` (owning repo, expected files, `is_answerable`) is read **only** by the offline
`grade()`/scorecard pass, which compares:

- **match:** did `ranked[0]` equal the owning repo? (recall@1) — and at what rank? (`repo_rank`)
- **localize:** how many `expected_files` did `locations` recover? (file_recall)
- **honest refusal:** on an unanswerable (out-of-fleet) case, did the loop *abstain* instead of guessing?

This separation is the project’s spine: **the metric measures reality, and the loop can never peek at the
answer.**

---

## The evaluation workflow

The benchmark drives the same ports directly (bypassing submit/bind), one case × arm at a time:

- **`gloop eval`** — Stage-1 match. Writes a **scorecard** (recall@1/3/5, MRR, coverage, selective accuracy,
  Φ_c honest-refusal, per-`negative_class` abstain rates) plus a `predictions.jsonl` (predicted repo + oracle
  rank per case). **Arms** = strategy × signal: `membership` (FTS5) / `semantic` (bge-m3) / `judge` (LLM
  rerank) × `text` / `logs`. Membership-only is fully hermetic (no model).
- **`gloop fixeval`** — the downstream fix loop. Metrics: `file_recall@k`, `patch_apply_rate`,
  `required_api_pass_rate`, `resolved_rate` (a proxy — no test execution in-scope for AAOS), and
  `fabrication_rate` on the honest-refusal negatives.
- **`gloop compare --base --head`** — a two-sided Δ between two fix scorecards, naming `newly_solved` /
  `newly_broken` and returning an `accept` verdict (positive lift **and** no honesty regression).

Every headline number in [the first evaluation](2026-07-06-first-evaluation.md) comes from these commands over a
real `atlas.db`.

---

## The dev-experience KB (a measured arm, not a trusted input)

The KB is a corpus of leak-safe **crash-RCA playbooks** (`groundloop/kb/`) injected into the fix stage as
*“# Applicable playbooks.”* It is deployed as an **A/B arm** — `gloop fixeval --skills {none|kb|placebo}` — so
its effect is *measured*, never assumed: a Skill enters the KB only if it demonstrably lifts fix quality
**without** raising `fabrication_rate`. The design is a “retain loop” (apply → measure → distill the useful
part → **re-validate** → fold in), so knowledge is admitted only on a verified outcome. See
[skill-kb-migration.md](skill-kb-migration.md) and
[the KB design spec](superpowers/specs/2026-07-06-effectiveness-driven-distilled-kb-design.md).

> Note: because `localize` runs *before* the fix stage, a fix-stage Skill is `file_recall`-invariant — its lift
> shows up in `resolved_rate`/`patch_apply_rate`, not `file_recall`.

---

## Where each stage stands

| Stage | Adapter (prod) | Maturity |
|---|---|---|
| intake | *(JIRA adapter — seam)* | dev-mock only |
| extract | `AndroidSignalExtractor` | ✅ built (domain adapter = prod) |
| **match** | `AtlasIndex` / `SemanticAtlasIndex` | ✅ **built + measured** (the headline capability) |
| materialize | `GitFixtureEstate` | ✅ built (fixtures); live full-fleet estate = seam |
| localize | `AtlasIndex.retrieve` | ✅ built + strong, **not yet scored** by the harness |
| fix | `ModelPatchEngine` (+ `GatewayModel`) | ⚠️ built; live quality gated (proxy metric) |
| submit / bind | *(Gerrit/PR adapter — seam)* | dev-mock only |

To take the loop to production you implement the two seam adapters (JIRA `IssueSource`, Gerrit/PR `ChangeSink`)
and wire a live fleet estate — everything upstream of them (match → localize → fix) is built. Full deployment
steps: [user-guide.md](user-guide.md).
