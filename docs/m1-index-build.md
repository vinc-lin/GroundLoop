# M1 Index Build: consume + build an atlas.db

GroundLoop M1 replaces the M0 `TokenIndex` stub with a real `AtlasIndex` backed by a
genuine `atlas.db` — a SQLite database of FTS5-indexed code units (symbols + doc units)
produced by CBM (codebase-memory-mcp) and CodeWiki.

## Status (M1 — landed)

All M1 capabilities are present and tested:

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

`--index-db` and `--index` (M0 token-index stub) are mutually exclusive; exactly one is
required. When `--index-db` is given, `AtlasIndex` is used; otherwise `TokenIndex` (M0
fallback) is used.

`gloop doctor` checks atlas.db readiness without running a ticket:

```
gloop doctor --atlas-db "$KLOOP_ATLAS_DB"
```

It prints per-repo unit counts and (if configured) pings the embed gateway and CBM.

## Reuse contract

The query-time embed model MUST match the index-time embed model. Mismatched models silently
produce wrong rankings.

| constraint | value | env var |
|---|---|---|
| embed model | `bge-m3` (pinned default) | `KLOOP_EMBED_MODEL` |
| atlas.db path | shared, stable path | `KLOOP_ATLAS_DB` |
| repo names | match the preprocessing registry exactly | `KLOOP_REGISTRY` |
| repo HEAD SHAs | must match what CBM indexed | set by `gloop index` at build time |

`bge-m3` is the default and must not be changed without re-indexing. The `embed_model`
field in `Settings` defaults to `"bge-m3"` and is read from `KLOOP_EMBED_MODEL`; if you
override it you MUST re-run `gloop index` to produce a compatible `atlas.db`.

The SQLite schema (`units` / `units_fts` FTS5 / `vectors` / `repos`) is migrated
byte-identical from knowledgeloop and has no schema-version guard. Altering it forces a
full re-index of every repository.

## Building a new atlas.db with gloop index

Prerequisites: a running embed gateway (`KLOOP_EMBED_BASE_URL`, `KLOOP_EMBED_API_KEY`),
CBM installed and on `PATH` (or overridden via `KLOOP_CBM_*` env vars), and an LLM
provider for CodeWiki produce (`KLOOP_PRODUCE_API_KEY`, `KLOOP_PRODUCE_BASE_URL`).

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
extraction (symbol units) + `GatewayEmbedder` to embed both kinds, then stores all units
via `Store.reindex_repo`.

## Environment variable reference

| variable | purpose | default |
|---|---|---|
| `KLOOP_ATLAS_DB` | path to atlas.db (consume + build) | `""` (required for `AtlasIndex`) |
| `KLOOP_REGISTRY` | path to atlas.toml registry | `""` (required for `gloop index`) |
| `KLOOP_EMBED_MODEL` | embedding model name (reuse contract) | `bge-m3` |
| `KLOOP_EMBED_BASE_URL` | embedding gateway base URL | `""` |
| `KLOOP_EMBED_API_KEY` | embedding gateway API key | `""` |
| `KLOOP_CBM_READY` | set non-empty to enable CBM in `gloop doctor` | `""` |
| `KLOOP_PRODUCE_READY` | gate for the live produce acceptance test | `""` |
| `KLOOP_PRODUCE_API_KEY` | LLM API key for CodeWiki generation | `""` |
| `KLOOP_PRODUCE_BASE_URL` | LLM base URL for CodeWiki generation | `""` |
| `KLOOP_PRODUCE_MAIN_MODEL` | primary model for wiki generation | `gpt-4o-mini` |
| `KLOOP_DATA_DIR` | local data directory | `./data` |
| `KLOOP_DOMAIN` | signal extractor domain | `android_ivi` |

## What is NOT in M1

- Real `AgentFixEngine` (fix stage uses `CannedFixEngine` stub)
- The `bfl mine` pipeline
- Full fleet / parallel worker pool
- ANN / vector rerank (semantic rerank is scaffolded — `GatewayEmbedder` migrated — but the
  hermetic tests use FTS5 membership; a gated vector-rerank path is the next add-on)
- Tier-3 grading
