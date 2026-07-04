# GL-M1 Index Build: consume + build an atlas.db

GroundLoop GL-M1 replaces the GL-M0 `TokenIndex` stub with a real `AtlasIndex` backed by a
genuine `atlas.db` — a SQLite database of FTS5-indexed code units (symbols + doc units)
produced by CBM (codebase-memory-mcp) and CodeWiki. The `AtlasIndex` adapter provides the
`CodeIndex` port's `rank_repos` (the ticket→repo MATCH) + `retrieve`; see
[architecture.md](architecture.md) for where this sits in the control/cognition planes and
its migration section for the migrated atlas / produce / CBM engine operations.

## Status (GL-M1 — landed)

All GL-M1 capabilities are present and tested:

- **CONSUME path** (Phases A + B): migrate the atlas read engine (Store, embed, retrieve,
  registry), `AtlasIndex` adapter, and the FTS5 membership-based `rank_repos` + `retrieve`.
  The hermetic test suite (`tests/test_atlas_index.py`, `tests/test_e2e_real_index.py`)
  runs with a hand-built `atlas.db` fixture — no external services required for CI.
- **BUILD path** (Phase C): `gloop index` builds an `atlas.db` from a registry file
  (atlas.toml) by running CodeWiki produce (wiki doc units) + CBM symbol extraction + the
  embedding gateway. `gloop produce` generates a CodeWiki wiki directory for a single repo.
  The full real-build acceptance (`tests/e2e/test_index_build_live.py`) is gated on
  `KLOOP_EMBED_API_KEY + KLOOP_CBM_READY + KLOOP_PRODUCE_READY` and validates that both
  `doc` and `symbol` units land in `atlas.db` end-to-end.
- **CLI** (`gloop run`, `gloop index`, `gloop produce`, `gloop doctor`): all subcommands
  wired and hermetically tested.

## Pointing GroundLoop at a preprocessed atlas.db

Set `KLOOP_ATLAS_DB` to the absolute path of the atlas.db produced by your preprocessing
pipeline (or by `gloop index`), then pass `--index-db` to `gloop run`:

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

`--index-db` and `--index` (GL-M0 token-index stub) are mutually exclusive; exactly one is
required. When `--index-db` is given, `AtlasIndex` is used; otherwise `TokenIndex` (GL-M0
fallback) is used.

`gloop doctor` checks atlas.db readiness without running a ticket:

```
gloop doctor --atlas-db "$KLOOP_ATLAS_DB"
```

It prints per-repo unit counts and (if configured) pings the embed gateway and
resolves/validates the CBM launch spec.

## Reuse contract

An `atlas.db` is a portable "build once, ship it" artifact: preprocessing is the slow,
expensive step, and its outputs (per-repo `wiki_dir/`, `entity_map.json`, and the shared
`atlas.db`) are reusable by the downstream consumer **as-is** — but only if the parameters
below are pinned. Reuse breaks silently, not loudly, if they drift.

| constraint | value | env var |
|---|---|---|
| embed model | `bge-m3` (pinned default) | `KLOOP_EMBED_MODEL` |
| atlas.db path | shared, stable path | `KLOOP_ATLAS_DB` |
| repo names | match the preprocessing registry exactly | `KLOOP_REGISTRY` |
| repo HEAD SHAs | must match what CBM indexed | set by `gloop index` at build time |
| CBM version | pinned `codebase-memory-mcp==0.8.1` | (a base dependency) |

### Mechanism: why the embed pin is load-bearing

The `vectors` table stores **raw embeddings**. When the (gated) vector-rerank path is
enabled, cosine similarity is computed directly against those stored vectors at query time,
so the query-time embedder MUST equal the index-time embedder — otherwise you are comparing
vectors from two different models and the ranking is **silently corrupted** (no error, just
wrong scores). `bge-m3` is the pinned default at both index time and query time. The
`embed_model` field in `Settings` defaults to `"bge-m3"` and is read from
`KLOOP_EMBED_MODEL`; if you override it you MUST re-run `gloop index` to produce a
compatible `atlas.db`.

### Stable names + pinned SHAs

Every unit is tagged with the repo `name` + the checkout SHA. The downstream consumer must
reuse the same repo names and materialize each repo at the same SHA the index was built
against, or ticket→repo matches will not align to what is actually materialized.

### Incremental / idempotent reindex

Both stages are incremental and idempotent, so re-running as repos update is cheap:

- **produce** diffs against the stored `commit_id` — an unchanged repo regenerates nothing.
- **index** reindexes per repo (`Store.reindex_repo`), replacing that repo's units in place;
  other repos in the `atlas.db` are untouched.

An `entity_map.json` (wiki module → code file+line) is built per repo from the wiki + CBM
during preprocessing and travels with the `wiki_dir/`; it is the doc-unit ↔ source
back-reference used downstream during localize.

### Repo-set vs fleet reconciliation

The `atlas.toml` registry (one `[[repo]]` per repo) is **requirement-driven and evolves — it
is not a fixed fleet**. The eval repo set grows by requirement; the **130+ AAOS repos** are
the *production target*, distinct from the charter pilot (~11 OSS repos), the built corpora
(3 at pinned SHAs), and the hermetic fixture (4 repos). See the fleet-layers section of
[charter.md](charter.md) for the full reconciliation.

### Schema note

The SQLite schema (`units` / `units_fts` FTS5 / `vectors` / `repos`) is migrated
byte-identical from knowledgeloop and has **no schema-version guard**. Altering it forces a
full re-index of every repository.

## Building a new atlas.db with gloop index

Prerequisites: a running embed gateway (`KLOOP_EMBED_BASE_URL`, `KLOOP_EMBED_API_KEY`),
CBM (`codebase-memory-mcp==0.8.1`) installed as the binary on `PATH` (launched from
`.venv/bin`, not via `uvx`; launch overrides read `KNOWLEDGELOOP_CBM_*` / `REPO_MEMORY_CBM_*`
via the `_envcompat` shim — see below), and an LLM provider for CodeWiki produce
(`KLOOP_PRODUCE_API_KEY`, `KLOOP_PRODUCE_BASE_URL`).

```
# 1. Generate a wiki for each repo (doc units)
gloop produce --repo /repos/my-repo --out /wikis/my-repo

# 2. Write an atlas.toml registry pointing at the wikis and repo paths,
#    then build atlas.db (symbol units via CBM + doc units + embed):
export KLOOP_ATLAS_DB=/shared/indexes/atlas.db
export KLOOP_REGISTRY=/shared/indexes/atlas.toml
export KLOOP_EMBED_BASE_URL=http://embed-gateway:8080
export KLOOP_EMBED_API_KEY=...

gloop index --registry "$KLOOP_REGISTRY"
```

`gloop index` calls `index_all` from `groundloop.engines.atlas.index`, which for each
registry entry runs: `load_wiki` (doc units from the wiki directory) + CBM symbol
extraction via `enumerate_all_nodes` (symbol units) + `GatewayEmbedder` to embed both kinds,
then stores all units via `Store.reindex_repo`.

## Environment variable reference

All GroundLoop config is env-only under the `KLOOP_*` prefix. **Exception:** the CBM *launch
overrides* are read as `KNOWLEDGELOOP_CBM_*` / `REPO_MEMORY_CBM_*` through the `_envcompat`
shim (preserved from the migration, not `KLOOP_CBM_*`), and raw CBM knobs (e.g.
`CBM_CACHE_DIR`) are intentionally un-prefixed. `KLOOP_CBM_READY` is a separate
GroundLoop-level *gate flag* — it enables the CBM check in `gloop doctor` and the live index
build; it is **not** a CBM launch override.

| variable | purpose | default |
|---|---|---|
| `KLOOP_ATLAS_DB` | path to atlas.db (consume + build) | `""` (required for `AtlasIndex`) |
| `KLOOP_REGISTRY` | path to atlas.toml registry | `""` (required for `gloop index`) |
| `KLOOP_EMBED_MODEL` | embedding model name (reuse contract) | `bge-m3` |
| `KLOOP_EMBED_BASE_URL` | embedding gateway base URL | `""` |
| `KLOOP_EMBED_API_KEY` | embedding gateway API key | `""` |
| `KLOOP_CBM_READY` | GroundLoop gate flag: set non-empty to enable CBM in `gloop doctor` / live build | `""` |
| `KLOOP_PRODUCE_READY` | gate for the live produce acceptance test | `""` |
| `KLOOP_PRODUCE_API_KEY` | LLM API key for CodeWiki generation | `""` |
| `KLOOP_PRODUCE_BASE_URL` | LLM base URL for CodeWiki generation | `""` |
| `KLOOP_PRODUCE_MAIN_MODEL` | primary model for wiki generation | `deepseek-chat` (working default on this gateway) |
| `KLOOP_DATA_DIR` | local data directory | `./data` |
| `KLOOP_DOMAIN` | signal extractor domain | `android_ivi` |
| `KNOWLEDGELOOP_CBM_*` / `REPO_MEMORY_CBM_*` | CBM launch overrides (via `_envcompat` shim) | (see [architecture.md](architecture.md) migration section) |

The gateway in this environment serves `deepseek-chat` / `deepseek-reasoner` plus the
embedding models (`bge-m3` / mxbai / qwen3); there is no OpenAI backend. Produce is
live-validated on **`deepseek-chat`** — the migrated code's historical `gpt-4o-mini` default
does not work here and is corrected to `deepseek-chat`.

## What is NOT in GL-M1

- Real `AgentFixEngine` (fix stage uses `CannedFixEngine` stub; see
  [downstream-fix-loop.md](downstream-fix-loop.md))
- A `gloop mine` mining pipeline — **not built yet**; aspirational. (The GroundLoop CLI is
  `gloop {run, index, produce, doctor}` only.)
- Full fleet / parallel worker pool
- ANN / vector rerank (semantic rerank is scaffolded — `GatewayEmbedder` migrated — but the
  hermetic tests use FTS5 membership; a gated vector-rerank path is the next add-on)
- Tier-3 grading

---

Deep source references (link, do not copy): the migration-source preprocessing template at
[../../knowledgeLoop/docs/preprocessing/README.md](../../knowledgeLoop/docs/preprocessing/README.md).
