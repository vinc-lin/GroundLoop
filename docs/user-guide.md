# GroundLoop — Deployment & Migration User Guide

How to set up GroundLoop, build the oracle (the graded ground truth), and deploy each pipeline stage in a
real-world environment. Every command is copy-paste-ready with **placeholders** for hosts/keys — never
commit real endpoints or tokens. Where a capability is a **seam not yet built**, it is flagged inline; a
consolidated list is in [§10](#10-known-seams--limitations).

> **Conventions.** `$GL_DATA` = a directory on **real ext4** (see [§2.3](#23-the-v9fsext4-rule)) that holds
> `atlas.db` + datasets. Placeholders: `<GATEWAY_HOST>` (LiteLLM chat), `<EMBED_HOST>` (bge-m3), `<API_KEY>`,
> `<GH_TOKEN>`, `<JIRA_TOKEN>`, `<repo-slug>`.

---

## 1. What you are deploying

GroundLoop runs a deterministic closed loop over a fleet of repos:

```
JIRA ticket + failure logs
  → intake → extract(signals) → MATCH(ticket→repo) → materialize → LOCALIZE(files) → FIX(patch) → submit → bind(JIRA↔commit)
```

- **Control plane** (`groundloop/core/`, **FROZEN**): `run_ticket` orchestrates the 8 events above by calling
  **7 ports** (Protocols). Core imports no concrete adapter.
- **Adapters** implement the ports. Each port has a hermetic dev adapter and (mostly) a real one; deployment
  = swapping dev→prod adapters **only at the composition root** (`groundloop/cli/__init__.py`), never in `core/`.
- **The oracle is never a loop input.** The owning repo + expected files are hidden ground truth used only by
  an **offline** grading pass.

The measured headline capability today is **Stage-1 match** (ticket→repo); localize is strong but unscored;
fix/submit/bind and the dev-experience KB are wired but their live quality is gated. See
`docs/2026-07-06-first-evaluation.md`.

---

## 2. Prerequisites & infrastructure

### 2.1 Service topology
GroundLoop is a **client** to three backends; every endpoint is env-configured (no hardcoded hosts):

```
 gloop ──► LiteLLM gateway <GATEWAY_HOST>
 │           ├─ chat model (default deepseek-chat)   ← produce / LLM-judge arm / fix loop
 │           └─ /embeddings → bge-m3 embed server <EMBED_HOST> (GPU-backed)
 └───────► CBM (codebase-memory-mcp==0.8.1) — LOCAL subprocess over MCP stdio (atlas build only)
```

| Backend | Purpose | Required for |
|---|---|---|
| **bge-m3 embed** (OpenAI-compat `/v1/embeddings`) | vectorizes code units + queries | building the atlas; semantic match arm; KB skill rerank |
| **chat gateway** (OpenAI-compat `/v1/chat/completions`, default `deepseek-chat`) | LLM propose/judge | the live fix loop; `--judge` arm; CodeWiki `produce` |
| **CBM** (local subprocess) | extracts symbol units per repo | building the atlas (`gloop index`) only — **not** needed to run eval/fixeval |

The same LiteLLM host can front both chat and embed; they remain independently configurable.

### 2.2 Resource requirements
- **`atlas.db` is multi-GB** (9-repo AAOS fleet ≈ 475k units, ~12.5 GB) → must live on **fast ext4**. A 187-case
  eval went from **>14 min (v9fs, unfinished) → 70 s (ext4)**.
- **GPU for the embed server** (bge-m3, single serialization lock). Embedding dominates index time — a full-fleet
  index is **tens of minutes to a few hours**.
- **Disk for fleet clones** (giants: organicmaps ~600 MB, media3 ~518 MB) + per-project CBM caches at
  `~/.cache/codebase-memory-mcp/<slug>.db`. CBM budgets ~24 GB RAM per running server.

### 2.3 The v9fs/ext4 rule (load-bearing)
Run **atlas builds AND sqlite eval off real ext4**, never a v9fs/9p network mount.
- On this host `/home/vinc/code` is a **symlink to `/mnt/x/code`** (v9fs) — real ext4 is `/home/vinc` *directly*,
  `/var/tmp`, or `/dev/shm`. Verify before running:
  ```bash
  df -T "$GL_DATA" | awk 'NR>1{print $2}'      # want: ext4  (not 9p)
  realpath "$GL_DATA/atlas.db"                  # must NOT resolve under a v9fs mount
  ```

---

## 3. Project setup

Python **3.12**, `uv`-managed `.venv`. The `gloop` console entry point = `groundloop.cli:main`.

```bash
cd <repo-root>
uv sync --extra dev      # base deps + pytest/ruff   (plain `uv sync` omits test tooling)
```
Base deps already include the two "default" heavy stacks: **CBM** (`mcp` + `codebase-memory-mcp==0.8.1`) and
the **CodeWiki `produce`** stack (litellm, tree-sitter grammars, GitPython, …).

### 3.1 Environment (`KLOOP_*`)
Config is env-only. `.env` is **gitignored** (only `.env.example` is committed, placeholders); it is **not
auto-loaded** — source it manually:
```bash
set -a; . ./.env; set +a
```

**Env vars read by `config/settings.py`** (the primary surface):

| Var | Default | Configures |
|---|---|---|
| `KLOOP_ATLAS_DB` | `""` | path to `atlas.db` (put on ext4) |
| `KLOOP_REGISTRY` | `""` | path to the repo registry `atlas.toml` |
| `KLOOP_EMBED_MODEL` | `bge-m3` | embed model — **pinned** (index == query) |
| `KLOOP_EMBED_BASE_URL` / `KLOOP_EMBED_API_KEY` | `""` | embeddings endpoint + key |
| `KLOOP_EMBED_BATCH` / `KLOOP_EMBED_MAX_CHARS` | `128` / `2000` | request batch size / per-input truncation (guard HTTP 413) |
| `KLOOP_PRODUCE_BASE_URL` / `KLOOP_PRODUCE_API_KEY` | `""` (key falls back to `OPENAI_API_KEY`) | chat gateway + key |
| `KLOOP_PRODUCE_MAIN_MODEL` | `deepseek-chat` | chat model id |
| `KLOOP_CBM_INDEX_TIMEOUT` | `1800.0` | per-CBM-call ceiling (covers a cold graph build) |
| `KLOOP_DATA_DIR` / `KLOOP_DOMAIN` / `KLOOP_MODEL` | `./data` / `android_ivi` / `canned` | data dir / domain pack / model id (`canned`=hermetic) |

> **Caveat (doc-vs-code):** `settings.py` is *called* "the single env surface," but `cli/__init__.py` also reads
> `KLOOP_PRODUCE_{CLUSTER,FALLBACK}_MODEL`, `KLOOP_PRODUCE_PROVIDER`, `KLOOP_PRODUCE_AWS_REGION`,
> `KLOOP_PRODUCE_CONCURRENCY`, and `KLOOP_CBM_READY` straight from `os.environ`. `KLOOP_PRODUCE_API_KEY` doubles
> as the **live/hermetic switch** — unset → the fix loop uses a canned model that abstains. (`.env.example`'s
> `KLOOP_PRODUCE_READY` has no code consumer — documentation-only.)

### 3.2 Verify the install (hermetic — no infra)
```bash
.venv/bin/python -m pytest -q            # Type-1 hermetic tests (no network/LLM)
.venv/bin/ruff check groundloop tests    # line length 110
.venv/bin/gloop doctor                   # readiness (atlas.db hard gate; embed/CBM advisory)
```

---

## 4. Building the oracle

"The oracle" = the graded benchmark: **(a)** an **atlas** (the fleet index the match is scored over) plus
**(b)** a **dataset** of cases, each with a hidden `_oracle/` (owning repo + expected files) mined from real
merged fixes, optionally **(c)** synth-log augmented.

### 4.1 Build the atlas (the fleet index)

**Two config files** (a registry + an optional corpus), joined by `name`:

`atlas.toml` (registry — one `[[repo]]` per fleet repo):
```toml
[[repo]]
name = "<repo-name>"                              # stable MATCH label = the oracle target
repo_path = "$GL_DATA/corpora/<repo-name>"        # local checkout CBM indexes
wiki_dir  = "$GL_DATA/corpora/_wiki/<repo-name>"  # CodeWiki dir (may be a stub)
# entity_map optional (defaults "")
```
`corpus.toml` (optional — only drives the *clone* stage of `build-atlas`):
```toml
[[repo]]
name = "<repo-name>"                    # join key = registry name
url  = "https://github.com/<slug>.git"  # a repo without a url is skipped
sha  = "PIN_AT_CLONE"                   # "" or PIN_AT_CLONE → clone HEAD, pin the resolved SHA afterward
```

**Recommended build = symbol-only, `gloop index` directly** (the `produce`/CodeWiki stage is impractical at
fleet scale — see [§10](#10-known-seams--limitations)):
```bash
export KLOOP_ATLAS_DB="$GL_DATA/atlas.db"          # ext4
export KLOOP_REGISTRY="$GL_DATA/corpora/atlas.toml"
export KLOOP_EMBED_BASE_URL="http://<EMBED_HOST>/v1"; export KLOOP_EMBED_API_KEY="<API_KEY>"
export KLOOP_CBM_READY=1; export KLOOP_CBM_INDEX_TIMEOUT=1800

# exclude tests + vendored 3party first (improves ownership signal + avoids CBM restart loops):
rsync -a --exclude=test --exclude=tests --exclude=androidTest --exclude='*_tests' --exclude=3party \
  <src-checkout>/ "$GL_DATA/corpora/<repo-name>/"

.venv/bin/gloop index --registry "$KLOOP_REGISTRY"   # run DETACHED; one at a time; progress is per-repo durable
.venv/bin/gloop doctor --atlas-db "$KLOOP_ATLAS_DB"  # repos>0, units>0
```
`gloop build-atlas --registry … --corpus … [--jobs 3 --concurrency 4 --force]` orchestrates
clone→produce→index→doctor but is **fail-fast on the produce stage**; prefer `gloop index`.

**Reuse contract** — an `atlas.db` is shareable/portable only if these stay pinned (drift corrupts ranking
**silently**): embed model `bge-m3` at index **and** query time · stable repo `name`s · the indexed `repo_head`
SHAs (materialize downstream at the same SHA) · one `atlas.db` path · `codebase-memory-mcp==0.8.1` · the SQLite
schema (no version guard — any change forces a full re-index).

### 4.2 Mine the dataset + oracle

**Prerequisite:** GitHub CLI auth (`gh auth login`, or `GH_TOKEN`/`GITHUB_TOKEN` in env). The miner shells
`gh api graphql` to find, per closed issue, a **same-repo merged closing PR** (the non-negotiable positive link).

```bash
.venv/bin/gloop mine \
  --slug <owner>/<name> --repo-name <repo-name> \
  --out "$GL_DATA/dataset" \
  --index-db "$KLOOP_ATLAS_DB" \        # enables the CLOSED-LOOP leak reject (strongly recommended)
  --limit 200 --max-files 5 \           # positives cap; single-concern PR file cap
  --holdout-frac 0.0 \                  # frac → out_of_fleet negatives
  --coverage-cutoff "" \                # ISO date → cases merged after become coverage_gap negatives
  --not-a-defect-limit 0                # >0 → harvest label-based not_a_defect negatives
```
Run once per fleet repo (the fleet name list comes from `KLOOP_REGISTRY`).

**Per-case on-disk layout** (owner-free `case_id`; all owner-bearing data hidden under `_oracle/`):
```
$GL_DATA/dataset/catalog.json          # loop-visible fleet candidate list
$GL_DATA/dataset/<case_id>/
  ticket.json     # LOOP-VISIBLE: id, summary, description, component="", logs:[{path,kind}]
  logs/000.txt …  # LOOP-VISIBLE sanitized log blocks
  catalog.json    # per-case candidate list (OOF holdout only — owner removed)
  _oracle/oracle.json      # HIDDEN ground truth (schema below)
  _oracle/provenance.json  # HIDDEN issue/PR/merge_commit_sha
  _oracle/{leakage.json, raw/issue.json, raw/pr_files.json}  # HIDDEN
```
`_oracle/oracle.json`: `owning_repo` (short name, or `"__NOT_A_DEFECT__"`) · `expected_files` (production paths
the merged PR changed) · `required_apis` (**always `[]`** in the mined path — a seam) · `owning_repo_sha` (the
fix-inclusive merge SHA the atlas indexed) · `is_answerable` · `negative_class`.

**Leak safety (why `--index-db` matters).** Each case is run through a per-case deterministic **scrubber** (redacts
owner namespaces/slugs/`.so`/expected-file tokens), then a deterministic **admit gate** that re-runs the real
`AndroidSignalExtractor` over the sanitized text and rejects any surviving owner-unique token. With `--index-db`,
a **closed-loop reject** additionally feeds the sanitized ticket through the *real `AtlasIndex` matcher* — if the
true owner still ranks top-1, the case is dropped. **Without `--index-db` this closed-loop gate is OFF** (the CLI
warns); ship with it on.

**Typed honest-refusal negatives** (for the anti-hallucination metric): `insufficient_signal` (prose-only, still
answerable), `coverage_gap` (merged after `--coverage-cutoff`), `out_of_fleet` (owner held out of the per-case
catalog → abstaining is correct), `not_a_defect` (label-harvested, `owning_repo="__NOT_A_DEFECT__"`).

### 4.3 Synth-log augmentation (optional; library only — no CLI)
Mined tickets are ~87% prose lacking crash signal. `groundloop.synth.dataset.build_synth_dataset(src_root,
atlas_db, dest_root, catalog_names)` rewrites each case with a deterministic AAOS failure log naming the owner's
**real** crash-site symbols pulled from the atlas (native SIGSEGV backtrace for native repos, else a FATAL
EXCEPTION logcat). This is grounded signal (matched against the atlas, never the repo name) and raised Stage-1
recall@1 from ~0.02 (real prose logs) to **0.60**. There is **no `gloop synth` subcommand** — call it
programmatically. It stays decoupled from `groundloop.mine.*` by design.

---

## 5. Run the pipeline

### 5.1 End-to-end smoke (`gloop run`)
Exercises the whole loop on one case (real match/localize via `AtlasIndex`; **fix here is still the
`CannedFixEngine` stub** — the real fix engine lives in `gloop fixeval`):
```bash
.venv/bin/gloop run --case <case_id> \
  --dataset "$GL_DATA/dataset" --catalog "$GL_DATA/dataset/catalog.json" \
  --work /var/tmp/gl-work --changes /var/tmp/gl-changes.jsonl \
  --index-db "$KLOOP_ATLAS_DB"           # or --index <token_index.json> for the hermetic M0 stub
# prints: case=<id> matched=<repo> change=<change-id>
```

### 5.2 Stage-1 match benchmark (`gloop eval`)
```bash
.venv/bin/gloop eval \
  --dataset "$GL_DATA/dataset" --catalog "$GL_DATA/dataset/catalog.json" \
  --index-db "$KLOOP_ATLAS_DB" --out "$GL_DATA/scorecard.json" \
  --tau-margin 1.0 --tau-score 1.0 [--semantic] [--judge]
```
Writes `scorecard.json` + `.md` + `scorecard.predictions.jsonl` (per case×arm: predicted repo, oracle rank,
recall@1, …). Arms: `membership+{text,logs}` always; `--semantic` adds bge-m3 arms (needs embed gateway);
`--judge` adds LLM-rerank arms (needs chat gateway). Membership-only eval is **hermetic** (FTS5, no model).

### 5.3 Fix-loop benchmark (`gloop fixeval`) + `compare`
```bash
.venv/bin/gloop fixeval \
  --dataset "$GL_DATA/dataset" --catalog "$GL_DATA/dataset/catalog.json" \
  --index-db "$KLOOP_ATLAS_DB" --repos "$GL_DATA/repos" \
  --out "$GL_DATA/fix-scorecard.json" \
  --skills {none|mock|kb|placebo} [--skills-seed <TOML>]
.venv/bin/gloop compare --base <base.json> --head <head.json> [--arm A] [--cost-budget F]
```
`--repos` = fleet repos as **real git checkouts** (`GitFixtureEstate` materializes `@base`). With
`KLOOP_PRODUCE_API_KEY` set → real `ModelPatchEngine`+`GatewayModel`; **unset → canned model, all cases abstain
at fix**. `--skills`: `none` baseline · `mock` = SP3 4-playbook seed · `kb` = the 12-skill corpus
(`groundloop/kb/data/aaos_kb_seed.toml`) · `placebo` = matched control. Metrics: `file_recall@k`,
`patch_apply_rate`, `required_api_pass_rate`, `resolved_rate` (proxy — no test execution), `fabrication_rate`
(Bucket-1 negatives), `phi_c`, cost. `compare` is a hermetic JSON diff → `newly_solved`/`newly_broken` + a
two-sided `accept` verdict.

> The KB A/B (`groundloop/kb/ab.run_ab` + `accept.strengthened_accept`, which adds a Φ_c-sweep + Wilson lower
> bound) is **library-only — no `gloop ab` subcommand yet**. Note also `file_recall@1` is **skill-invariant**
> (localize runs before fix), so grade KB lift on `resolved_rate`/`patch`/`fabrication_rate`.

---

## 6. Deploy each stage (adapter swap map)

`run_ticket` receives already-constructed port objects. **Swap dev→prod only at the composition root**
(`groundloop/cli/__init__.py`): the `run` handler, `_run_eval`, `_run_fixeval`. Never edit `core/`.

| Stage | Port · method | Dev (hermetic) | Prod (real) | Needs |
|---|---|---|---|---|
| **intake** | `IssueSource.fetch/post_comment/transition` | `MockJira` (reads `ticket.json`) | **SEAM — NOT BUILT** (write a JIRA REST adapter) | JIRA base URL + `<JIRA_TOKEN>` |
| **extract** | `SignalExtractor.extract` | `AndroidSignalExtractor` | *same* (domain adapter = prod) | none |
| **match** | `CodeIndex.rank_repos` | `TokenIndex` (M0 stub) | `AtlasIndex` (FTS5) · `SemanticAtlasIndex` (bge-m3) · `LLMJudgeIndex` | atlas.db on ext4; gateways for semantic/judge |
| **catalog+materialize** | `RepoEstate.catalog/materialize` | `MockEstate` | `GitFixtureEstate` (git worktree @SHA); **full 130-repo live estate = seam** | git checkouts |
| **localize** | `CodeIndex.retrieve` | `TokenIndex` stub | `AtlasIndex`/`SemanticAtlasIndex` (same object as match) | atlas.db (+embedder) |
| **fix** | `FixEngine.propose` | `CannedFixEngine` | `ModelPatchEngine` | the `Model` port |
| **fix — Model** | `Model.complete` | `CannedModel` | `GatewayModel` | chat gateway + key |
| **submit / bind** | `ChangeSink.submit/bind` | `MockGerrit` (JSONL ledger) | **SEAM — NOT BUILT** (write a Gerrit/PR adapter) | Gerrit REST / `gh` + `<GH_TOKEN>` |

**To deploy for real** you must additionally build: a real **`IssueSource`** (JIRA), a real **`ChangeSink`**
(Gerrit/GitHub PR), and wire a **live fleet estate** into `run`. Match/localize/fix are built; extract is the
domain adapter.

---

## 7. Hermetic vs gated-live (what runs where)

- **Hermetic** (no LLM/embed network, but still needs a pre-built `atlas.db`): `gloop eval` without
  `--semantic`/`--judge`; `gloop fixeval --skills none` without `KLOOP_PRODUCE_API_KEY` (abstains at fix);
  `gloop compare`; `pytest`.
- **Gated-live** (need the gateways + assets): `gloop eval --semantic` (embed) / `--judge` (chat); `gloop
  fixeval` with real patches (`KLOOP_PRODUCE_API_KEY` + `--repos` git checkouts + embed for KB rerank); and
  **building the atlas itself** (`gloop index` needs CBM + embed).

---

## 8. Operational gotchas (atlas build)

- **CBM timeout = 1800 s** (`KLOOP_CBM_INDEX_TIMEOUT`). The old 30 s default tripped a cold graph build → the
  client restarted a still-indexing subprocess and dead-hung, storing **0 units, no error**. Keep it high.
- **One index at a time.** Concurrent `gloop index` jobs contend (each spawns a ~24 GB CBM) and stall past any
  timeout. Verify none running first.
- **Process checks: `pgrep -fa`, not `ps -C`.** The entry point has `comm=gloop`; CBM truncates to
  `comm=codebase-memory` — `ps -C python`/`ps -C codebase-memory-mcp` never match:
  ```bash
  pgrep -fa 'gloop index'; pgrep -fa 'codebase-memory'   # must be empty before a build
  ```
- **Never `kill -9` CBM** mid-index (leaves a locked project db). For a clean rebuild:
  `rm ~/.cache/codebase-memory-mcp/<slug>.db`.
- **Run the full index detached** (a SIGTERM mid-embed orphans CBM); progress is per-repo durable — small repos first.
- **Embed 413:** a batch over `BGE_MAX_BATCH` or an input over `BGE_MAX_CHARS` returns HTTP 413 (a 4xx, **not
  retried** → aborts the index). Defaults `KLOOP_EMBED_BATCH=128`, `KLOOP_EMBED_MAX_CHARS=2000` are safe.
- **Embedding is the real time cost** (not CBM) once the hang is fixed.

---

## 9. Migration checklist (new environment)

1. **Provision infra:** a LiteLLM chat gateway (chat model), a GPU-backed bge-m3 embed server, and
   `codebase-memory-mcp==0.8.1` on PATH. Pick an **ext4** `$GL_DATA`.
2. **Install:** `uv sync --extra dev`; write `.env` (from `.env.example`) with your `KLOOP_*`; `set -a; . ./.env; set +a`.
3. **Verify:** `pytest -q` green; embed `/embeddings` returns 200; `gloop doctor` clean.
4. **Clone the fleet** to `repo_path`s (exclude `test*`/`3party`); write `atlas.toml` (+ optional `corpus.toml`).
5. **Build the atlas** (`gloop index`, detached, one at a time, off ext4); pin the reuse-contract values;
   `gloop doctor` shows `repos>0 units>0`.
6. **Mine the dataset** (`gloop mine … --index-db $KLOOP_ATLAS_DB` per repo; needs `gh` auth); optionally
   synth-augment.
7. **Baseline benchmark:** `gloop eval` → `scorecard.{json,md}` + predictions.
8. **Downstream:** stand up `--repos` git checkouts; `gloop fixeval --skills none|kb`; `gloop compare`.
9. **For production intake/submit:** implement the real `IssueSource` (JIRA) and `ChangeSink` (Gerrit/PR)
   adapters and wire them at the composition root; wire a live fleet estate into `run`.

---

## 10. Known seams & limitations

Be honest about these when deploying — they are **not yet built**:

- **Real intake/submit adapters** — only `MockJira` / `MockGerrit` exist. A production loop needs a real JIRA
  `IssueSource` and a real Gerrit/GitHub-PR `ChangeSink`.
- **`gloop run` fix is a stub** (`CannedFixEngine`); the real `ModelPatchEngine` fix loop is only in `gloop fixeval`.
- **Live full-fleet estate** — `GitFixtureEstate` handles curated checkouts, not a live 130-repo clone inside `run`.
- **Atlas is symbol-only** — `produce`/CodeWiki is impractical at fleet scale (I/O-bound, crashes on giants);
  doc units (only used by the semantic arm) are largely absent.
- **`Store.vector_search` is brute-force** (full scan over JSON vectors) — a real ANN index (sqlite-vss/faiss) is
  needed for scale.
- **`rank_repos` size-bias is unfixed** (big repos win rank-1; recall@1 0.60 vs recall@3 0.80). Changing
  `rank_repos` also affects the miner's closed-loop reject — coordinate.
- **`required_apis` is always `[]`** from the miner; the diff-derived class/method redaction and the
  `expected_files`-exist-at-SHA check are dormant.
- **SHA pinning** — `corpus.toml` may still carry `PIN_AT_CLONE`; resolve and pin back for a reproducible atlas.
- **Named calib/eval/holdout splits are not materialized**; the KB A/B (`run_ab`) has no CLI subcommand;
  honest-refusal negatives are not yet mined into the shipped eval datasets.

---

*See also: `docs/architecture.md` (ports & adapters), `docs/type2-evaluation.md` (dataset/scorecard canonical),
`docs/m1-index-build.md` + `docs/type2-atlas-build-findings.md` (atlas build + gotchas),
`docs/skill-kb-migration.md` (KB), `docs/2026-07-06-first-evaluation.md` (measured status).*
