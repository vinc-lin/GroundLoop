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
