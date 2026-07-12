# Build & Setup — atlas.db runbook

Operational runbook for the `atlas.db` substrate: pointing GroundLoop at a prebuilt index, building a
new one (`gloop index` / `build-atlas`), standing up the gated live-eval environment, and the
atlas-build gotchas that recur on any machine. For the dev-box-vs-production split (what a `[proxy]`
number means vs a `[production]` one), see [environments.md](environments.md); GroundLoop's own
milestone track (GL-M0/M1) is in [roadmap.md](roadmap.md), where `AtlasIndex` fits the control plane is
[architecture.md](architecture.md).

An `atlas.db` is a portable "build once, ship it" artifact — a SQLite DB of FTS5-indexed code units
(CBM symbol units + CodeWiki doc units, both bge-m3-embedded). Preprocessing is the slow, expensive
step; its outputs (`atlas.db`, per-repo `wiki_dir/`, `entity_map.json`) are reusable **as-is** by the
downstream consumer, but only if the reuse contract below is pinned — reuse breaks silently, not
loudly, if it drifts.

## Pointing GroundLoop at a prebuilt atlas.db

Set `KLOOP_ATLAS_DB` to the absolute path, then pass `--index-db` to `gloop run`:

```
export KLOOP_ATLAS_DB=/shared/indexes/atlas.db

gloop run \
  --case GP-352 \
  --dataset /data/bugs.jsonl \
  --catalog /data/catalog.json \
  --index-db "$KLOOP_ATLAS_DB" \
  --work /tmp/work \
  --changes /tmp/changes.jsonl
```

`--index-db` and `--index` (GL-M0 token-index stub) are mutually exclusive; exactly one is required.
With `--index-db`, `AtlasIndex` is used; otherwise `TokenIndex` (GL-M0 fallback).

`gloop doctor` checks readiness without running a ticket — prints per-repo unit counts and (if
configured) pings the embed gateway + resolves/validates the CBM launch spec:

```
gloop doctor --atlas-db "$KLOOP_ATLAS_DB"
```

## Reuse contract

Pin these or an `atlas.db` stops being shareable and reruns over it stop being reproducible — the same reuse
contract as [environments.md](environments.md), which keeps the atlas *shape* stable across environments,
**not** proxy-vs-production *scores* comparable:

| constraint | value | env var |
|---|---|---|
| embed model | `bge-m3` (pinned default) | `KLOOP_EMBED_MODEL` |
| atlas.db path | shared, stable path | `KLOOP_ATLAS_DB` |
| repo names | match the preprocessing registry exactly | `KLOOP_REGISTRY` |
| repo HEAD SHAs | must match what CBM indexed | set by `gloop index` at build time |
| CBM version | pinned `codebase-memory-mcp==0.8.1` | (a base dependency) |

- **Why the embed pin is load-bearing.** The `vectors` table stores **raw embeddings**. With the
  (gated) vector-rerank path enabled, cosine similarity is computed against those stored vectors at
  query time, so the query-time embedder MUST equal the index-time embedder — else you compare vectors
  from two different models and ranking is **silently corrupted** (no error, wrong scores). `bge-m3` is
  the pinned default both ends; override `KLOOP_EMBED_MODEL` and you MUST re-run `gloop index`.
- **Stable names + pinned SHAs.** Every unit is tagged with repo `name` + checkout SHA. The consumer
  must reuse the same names and materialize each repo at the same SHA, or ticket→repo matches won't
  align to what is materialized.
- **Incremental / idempotent.** `produce` diffs against the stored `commit_id` (unchanged repo →
  regenerates nothing); `index` reindexes per repo (`Store.reindex_repo`) in place, leaving other repos
  untouched. An `entity_map.json` (wiki module → code file+line) travels with each `wiki_dir/` and is
  the doc-unit ↔ source back-reference used downstream during localize.
- **Repo-set is requirement-driven.** `atlas.toml` (one `[[repo]]` each) evolves by requirement — it is
  not a fixed fleet. The 130+ AAOS repos are the production target, distinct from the charter pilot
  (~11 OSS repos), the built corpora (pinned SHAs), and the hermetic fixture (4 repos); see
  [charter.md](charter.md).
- **Schema note.** The schema (`units` / `units_fts` FTS5 / `vectors` / `repos`) is migrated
  byte-identical from knowledgeloop with **no schema-version guard** — altering it forces a full
  re-index of every repo.

## Environment variable reference

All GroundLoop config is env-only under `KLOOP_*`. **Exception:** the CBM *launch overrides* read as
`KNOWLEDGELOOP_CBM_*` / `REPO_MEMORY_CBM_*` via the `_envcompat` shim (not `KLOOP_CBM_*`), and raw CBM
knobs (e.g. `CBM_CACHE_DIR`) are intentionally un-prefixed. `KLOOP_CBM_READY` is a GroundLoop-level
*gate flag* (enables the CBM check in `gloop doctor` + live index build), **not** a CBM launch override.

| variable | purpose | default |
|---|---|---|
| `KLOOP_ATLAS_DB` | path to atlas.db (consume + build) | `""` (required for `AtlasIndex`) |
| `KLOOP_REGISTRY` | path to atlas.toml registry | `""` (required for `gloop index`) |
| `KLOOP_EMBED_MODEL` | embedding model name (reuse contract) | `bge-m3` |
| `KLOOP_EMBED_BASE_URL` | embedding gateway base URL | `""` |
| `KLOOP_EMBED_API_KEY` | embedding gateway API key | `""` |
| `KLOOP_CBM_READY` | gate flag: non-empty enables CBM in `gloop doctor` / live build | `""` |
| `KLOOP_CBM_INDEX_TIMEOUT` | CBM per-repo index-call timeout, seconds (invalid/≤0 → default) | `1800` |
| `KLOOP_PRODUCE_READY` | gate for the live produce acceptance test | `""` |
| `KLOOP_PRODUCE_API_KEY` | LLM API key for CodeWiki generation | `""` |
| `KLOOP_PRODUCE_BASE_URL` | LLM base URL for CodeWiki generation | `""` |
| `KLOOP_PRODUCE_MAIN_MODEL` | primary model for wiki generation | `deepseek-chat` (working default here) |
| `KLOOP_DATA_DIR` | local data directory | `./data` |
| `KLOOP_DOMAIN` | signal extractor domain | `android_ivi` |
| `KNOWLEDGELOOP_CBM_*` / `REPO_MEMORY_CBM_*` | CBM launch overrides (via `_envcompat` shim) | (see [architecture.md](architecture.md) migration section) |

The gateway in this environment serves `deepseek-chat` / `deepseek-reasoner` plus the embedding models
(`bge-m3` / mxbai / qwen3); there is no OpenAI backend. Produce is live-validated on **`deepseek-chat`**
— the migrated code's historical `gpt-4o-mini` default does not work here and is corrected.

## Building a new atlas.db with gloop index

Prerequisites: a running embed gateway (`KLOOP_EMBED_BASE_URL`, `KLOOP_EMBED_API_KEY`), CBM
(`codebase-memory-mcp==0.8.1`) as a binary on `PATH` (launched from `.venv/bin`, not `uvx`; launch
overrides via the `_envcompat` shim), and an LLM provider for CodeWiki produce (`KLOOP_PRODUCE_API_KEY`,
`KLOOP_PRODUCE_BASE_URL`).

```
# 1. Generate a wiki for each repo (doc units) — host-independent, can run before the embed host is up:
gloop produce --repo /repos/my-repo --out /wikis/my-repo

# 2. Write an atlas.toml registry pointing at the wikis + repo paths, then build atlas.db
#    (symbol units via CBM + doc units + embed):
export KLOOP_ATLAS_DB=/shared/indexes/atlas.db
export KLOOP_REGISTRY=/shared/indexes/atlas.toml
export KLOOP_EMBED_BASE_URL=http://embed-gateway:8080
export KLOOP_EMBED_API_KEY=...

gloop index --registry "$KLOOP_REGISTRY"

# 3. verify:
gloop doctor        # repos > 0, units > 0, embed gateway OK, CBM OK
```

`gloop index` calls `index_all` (`groundloop.engines.atlas.index`), which per registry entry runs
`load_wiki` (doc units) + CBM symbol extraction via `enumerate_all_nodes` (symbol units) +
`GatewayEmbedder` to embed both, then stores via `Store.reindex_repo`. `gloop build-atlas` wraps
produce → index → doctor as one fleet build (fail-fast on produce — see gotcha 1).

**Not in GL-M1 (several shipped since):** the real fix engine `ModelPatchEngine` landed later (via `gloop
fixeval` / `gloop run --fixer model`; `gloop run`'s default is still the `CannedFixEngine` stub — see
[fix-loop.md](fix-loop.md)); the gated **vector-rerank** arm shipped as `SemanticAtlasIndex` (`--semantic`,
with `GatewayEmbedder` now wired live). Still pending: an **ANN** index (`store.vector_search` is a
brute-force scan), a full-fleet parallel worker pool, and Tier-2/3 grading.

## Gated live-eval setup

Stand up the live evaluation substrate: a real `atlas.db` over the pinned corpora so `AtlasIndex`
matches over real code and the gated `tests/e2e/` run. Type-1 hermetic tests need none of this (see
[evaluation.md](evaluation.md) for the two-surface split).

**Prerequisites (verified 2026-07-04):** CBM `codebase-memory-mcp 0.8.1` in `.venv`; produce LLM
`deepseek-chat` via the LiteLLM gateway (HTTP 200); **bge-m3 embeddings** on the same gateway but
GPU/Ollama-backed — **must be up** (see gate); corpora at `/mnt/x/code/corpora/` at pinned SHAs
(`corpus.toml`), registry `corpora/atlas.toml`.

**Config.** Copy `.env.example` → `.env` (gitignored), or use the provided `.env` (reuses the gateway
creds from `loop-agent/.env`). Source it before every `gloop` call:

```
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a
```

Key vars: `KLOOP_EMBED_{BASE_URL,API_KEY,MODEL=bge-m3}`, `KLOOP_ATLAS_DB`, `KLOOP_REGISTRY`,
`KLOOP_PRODUCE_{BASE_URL,API_KEY,MAIN_MODEL,...,READY=1}`, `KLOOP_CBM_READY=1`.

> **Known-benign warning.** `gloop produce` prints `python-dotenv could not parse statement starting at
> line 6`. **Harmless** (produce exits 0). This `.env` is intentionally a *shell script* — it `source`s
> `loop-agent/.env` and maps `BFL_LLM_*` → `KLOOP_*` to avoid duplicating the secret — so it holds shell
> statements python-dotenv (auto-loaded from cwd by the produce stack) trips on. To silence: run `gloop`
> from a directory without a shell-style `.env`, or keep `.env` a flat `KEY=VALUE` file.

**Embedding-host gate.** The build's embed step needs the bge-m3 backend. Check it (prints `200` when
up, `000` while the GPU/Ollama host is down):

```
set -a; . ./.env; set +a
curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 "${KLOOP_EMBED_BASE_URL%/}/embeddings" \
  -H "Authorization: Bearer $KLOOP_EMBED_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","input":"hi"}'
```

**Build (once the gate reads 200):**

```
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a
mkdir -p "$HOME/.groundloop"

# 1. wikis (doc units) — host-independent, can run before the embed host is up:
.venv/bin/gloop produce --repo /mnt/x/code/corpora/android-gpuimage-plus \
                        --out  /mnt/x/code/corpora/_wiki/android-gpuimage-plus

# 2. build atlas.db = wiki doc units + CBM symbol units + bge-m3 vectors:
.venv/bin/gloop index --registry /mnt/x/code/corpora/atlas.toml

# 3. verify:
.venv/bin/gloop doctor        # repos > 0, units > 0, embed gateway OK, CBM OK
```

**Flip the gated live tests.** The two `skipif`-gated `tests/e2e/` run once services are declared
ready:

```
set -a; . ./.env; set +a
KLOOP_EMBED_API_KEY="$KLOOP_EMBED_API_KEY" KLOOP_CBM_READY=1 KLOOP_PRODUCE_READY=1 \
  .venv/bin/python -m pytest tests/e2e/ -q
```

`tests/e2e/test_index_build_live.py` is the M1 milestone acceptance (produce + CBM + embed → atlas.db
with both doc and symbol units; `AtlasIndex` retrieves a known symbol).

**Growing the fleet.** Uncomment `libxcam` / `ndk-samples` in `corpora/atlas.toml` and re-run produce +
index for each. A meaningful Stage-1 match needs several confusable repos so a 1/N guess scores far
below a real match.

## Atlas-build gotchas

Substrate-build blockers (not harness code defects) recorded 2026-07-05 while building the full 9-repo
live `atlas.db`. They recur on any build machine — fixes belong in the tooling. Substrate = `atlas.db`
built by `gloop build-atlas` = `produce` (CodeWiki via DeepSeek) → `index` (CBM symbols + bge-m3
embed) → `doctor`.

- **Confirmed root cause of the "CBM hang" = a 30 s timeout tripping a minutes-long call.** A cold
  `index_repository` graph build is seconds on fast disk but **minutes** under contention / on the
  `/mnt/x` v9fs mount. `CBMClient`'s old default `call_timeout` was 30 s; at 30 s the call raised →
  `call_tool_with_restart` `_restart`ed a still-indexing subprocess → the mcp stdio client blocked in
  `poll()` **forever** (state S), storing **0 units** while CBM kept building its background cache.
  **Fix (landed, portable):** `KLOOP_CBM_INDEX_TIMEOUT` (default **1800 s**; invalid/≤0 → default),
  threaded `call_timeout=` through `index_all`/`index_repo` → `cli/_run_index`; query calls return in ms
  so the high ceiling never bites them.
- **1 — produce is impractically slow + crashes on giants.** ~99% I/O-wait on the DeepSeek gateway
  (concurrency doesn't help — the gateway serializes); giants (`osmand` 3,975 files, `organicmaps`
  2,381, `media3` 2,595) emit an empty `module_tree.json` and exit. `build_atlas` is **fail-fast on
  produce** → whole build aborts, no atlas. Fix: **symbol-only atlas** (skip produce, `gloop index`
  directly) — CBM symbol units carry the package/class/method/`.so` tokens the matcher keys on AND get
  bge-m3 vectors; doc units only add prose for the semantic arm. (Or make `build_atlas` produce-tolerant.)
- **2 — `gloop index` can't build a symbol-only atlas (`load_wiki` hard-requires a wiki).** `index_repo`
  calls `load_wiki` unconditionally; it raises on a missing `wiki_dir` OR a partial wiki (no
  `metadata.json`). Interim unblock: write `{}` → `module_tree.json` and `{"files_generated": []}` →
  `metadata.json` into each `_wiki/<name>/` before `gloop index`. Fix: make the index path tolerate a
  missing/incomplete wiki (return empty `WikiData`, proceed with CBM symbols only).
- **3 — CBM is SLOW, not hung; don't kill it.** `mem.init` is an early log line; CBM then works
  silently for minutes building `~/.cache/codebase-memory-mcp/<slug>.db` (gpuimage grows to 54 MB). Watch
  that db **growing** as the true progress signal — not the atlas unit count (0 until a repo fully
  completes). Never `kill -9` (leaves a partial/locked project db); let the `finally` `aclose()` run;
  `rm` the project db for a clean rebuild after a hard kill. (`build/lite_index.py` exists as an
  emergency low-fidelity fallback — do NOT use it as the real substrate.)
- **4 — orphaned CBM servers accumulate across sessions.** Interrupted runs (Ctrl-C, tool timeouts)
  orphan the `codebase-memory-mcp` server. Reap before a fresh build; the client lifecycle should
  `aclose()` its server on exit.
- **5 — concurrent index jobs contend (an amplifier, not the root).** Multiple `gloop index` jobs slow
  each other past the old 30 s ceiling — reads as a hang. **Run exactly ONE `gloop index` at a time;**
  verify nothing is left before starting.
- **6 — process-liveness checks must not use `ps -C`.** The entry point has `comm=gloop` (not `python`)
  and CBM is truncated to `comm=codebase-memory` (Linux 15-char `comm` limit), so `ps -C python | grep
  'gloop index'` and `ps -C codebase-memory-mcp` **never match** — clean checks over live orphans. Use
  full-arg matching: `pgrep -fa 'gloop index'`, `pgrep -fa 'codebase-memory'` (guard against matching
  your own shell); kill by PID.
- **7 — embedding is the real time cost (once the hang is fixed).** `GatewayEmbedder.embed` POSTs bge-m3
  in batches of 64; gpuimage's 31,745 units ≈ ~500 round-trips, giants far more — a full-fleet index is
  tens of minutes to hours, dominated by embedding. Run the index **detached** (never under a short
  foreground timeout — a SIGTERM mid-embed orphans CBM again); `reindex_repo` is per-repo so partial
  progress is durable — do **small repos first** for a usable multi-repo atlas early.
- **8 — `/home/vinc/code` is a symlink to `/mnt/x/code` (v9fs); "native ext4" can be illusory.** Real
  ext4 is `/home/vinc` **directly** (`/dev/sdd`), `/var/tmp`, or `/dev/shm` — never a `/mnt/x` path
  (even symlinked). v9fs is the bottleneck for (a) sqlite random reads over the large atlas during
  `gloop eval` (187-case eval: >14 min unfinished on v9fs → **70 s** on ext4) and (b) large repos.
  Always stage `atlas.db` + the dataset on real ext4 for `gloop eval`; verify with `df -T <path>` (want
  `ext4`, not `9p`) and `realpath`.
- **9 — CBM CPU-churns (restart-loops) on huge single source files; exclude tests + `3party`.** `media3`
  (`ExoPlayerTest.java` 651 KB under `src/test/`) and `organicmaps` (`3party/GL/glext.h` 760 KB) 100%-CPU
  restart CBM (`futex_wait_queue`, content-specific, not the mount). Exclude test dirs (`test`, `tests`,
  `androidTest`, `testing`, `*_tests`) and vendored `3party` before indexing (`rsync -a --exclude=test
  --exclude=androidTest --exclude='*_tests' --exclude=3party …` to ext4) — removes the churn AND
  improves ownership signal (a defect is owned by `src/main`/`libs`, not tests or third-party libs).
- **10 — `gloop fixeval` materializes the WHOLE repo PER CASE; stage `--repos` on ext4 too.**
  `GitFixtureEstate.materialize` does `rmtree` → `copytree` → `git init/add/commit` per case with no
  caching; over v9fs that's minutes/case. Stage `--repos` on ext4 once (`cp -a
  /mnt/x/code/corpora-local/<repo> /home/vinc/gl-eval/corpora-fast/`) then point `gloop fixeval --repos`
  there → per-case materialization drops minutes → **~seconds**. Extends gotcha 8: for `gloop eval`
  stage atlas + dataset; for `gloop fixeval` **also** stage `--repos`.
