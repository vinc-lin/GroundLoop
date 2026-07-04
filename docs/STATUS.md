# GroundLoop — Status

**As of 2026-07-04.** Read this first when resuming; see `CLAUDE.md` for durable project context.

## Done

### M0 — walking skeleton
Deterministic ticket → repo → fix → bind loop over the mock adapters + `TokenIndex` stub + offline
grader. Hermetic vertical slice green.

### M1 — real index (consume + build)  ·  17 tasks, final review PASS
Migrated the full index engine from knowledgeLoop behind the ports:
- `engines/atlas` (Store — schema unchanged; chunk/symbol_source/source_probe; embed/retrieve/registry;
  index_repo/build_units), `engines/lore` (CBM graph client/nodes/forward, bridge/schema NodeRecord,
  deploy launch-spec, wiki loader; `_resolve_repo_head` extracted — `server.py` NOT migrated),
  `engines/produce` (CodeWiki generation, 86 files).
- `AtlasIndex` (CodeIndex port) = FTS5 unit-membership `rank_repos` over a real atlas.db; discriminates
  the owner from hard negatives (hermetic-tested on a hand-built fixture db).
- CLI: `gloop index` (build atlas.db from a registry), `gloop produce` (wiki), `gloop doctor`
  (readiness). `gloop run --index-db` swaps `AtlasIndex` for `TokenIndex` at the composition root —
  `core/` untouched.
- Reuse contract honored: `embed_model` pinned `bge-m3`; store schema migrated unchanged.
- CBM packaging: **Level-1 default hard dep** (`mcp` + `codebase-memory-mcp==0.8.1` + produce stack in
  base `[project.dependencies]`; launched as the installed binary, not `uvx`).
- Detail: `docs/m1-index-build.md`.

### Testing environment
- **Type-1 (hermetic)** — `tests/conftest.py` (shared fixtures: `case`, `harness`, `atlas_harness`,
  prebuilt atlas.db, canned model) + `tests/test_invariants.py` (the anti-leak §2.3 red-tests — the
  design already honored them; these lock it in). **Suite: 55 passed / 3 skipped, ruff clean.**
- **Type-2 (live eval) — prepped + de-risked** (`.env` gitignored / `.env.example` /
  `/mnt/x/code/corpora/atlas.toml` / `docs/type2-eval-setup.md`):
  - ✅ **CBM validated live** on android-gpuimage-plus: 31,552 nodes / 41,191 edges, symbols in 3.3s.
  - ✅ **produce validated live** (deepseek-chat) → wiki generated; the pydantic-ai 1.x→2.x compat
    shim WORKS end-to-end (the M1 "latent risk" is now cleared).
  - ✅ Fixed: CBM launches the bare `codebase-memory-mcp` binary, so `.venv/bin` must be on `PATH`
    (now exported in `.env`).

## Current blocker
❌ **The pinned `bge-m3` embedding host is DOWN.** The LiteLLM gateway *lists* bge-m3 (+
mxbai-embed-large, deepseek-chat/reasoner, qwen3) but `/embeddings` hangs → HTTP `000` (GPU/Ollama
backend down; same mode as qwen3). `deepseek-chat` (produce LLM, cloud-routed) is **up**. The full
`gloop index` build (produce → CBM → embed → atlas.db) and the 2 gated live tests wait on this host.
Gate check (prints `200` when healthy): see `docs/type2-eval-setup.md` → "Embedding-host gate".

## Next steps
1. **When bge-m3 → 200:** `gloop produce` + `gloop index` over `/mnt/x/code/corpora/atlas.toml` →
   build `~/.groundloop/atlas.db`; `gloop doctor`; then run the gated live tests (`tests/e2e/`) with
   `KLOOP_EMBED_API_KEY` + `KLOOP_CBM_READY=1` + `KLOOP_PRODUCE_READY=1`. Runbook:
   `docs/type2-eval-setup.md`.
2. **Symbol filtering** before scaling the fleet — android-gpuimage-plus yields ~31k symbols because it
   vendors ffmpeg headers; drop vendored `ffmpeg/**` to cut embedding cost + noise. (Small follow-up.)
3. **Grow the eval fleet** — uncomment `libxcam` / `ndk-samples` in `corpora/atlas.toml`; a meaningful
   Stage-1 match needs several confusable repos so a `1/N` guess scores far below a real match.
4. **Real `AgentFixEngine`** (the fix stage), then `bfl mine` (mined tickets + logs), ANN vector index,
   Tier-3 grading.

## Services / environment
- **LiteLLM gateway** — creds in the gitignored `/mnt/x/code/loop-agent/.env`, reused by
  `GroundLoop/.env`. Serves: `deepseek-chat`/`deepseek-reasoner` (UP), `bge-m3` + `mxbai-embed-large`
  + `qwen3` (GPU/Ollama-backed — DOWN at last check).
- **Corpora** — `/mnt/x/code/corpora/` at pinned SHAs (`corpus.toml`): android-gpuimage-plus, libxcam,
  ndk-samples. Registry: `corpora/atlas.toml`. Built atlas.db target: `~/.groundloop/atlas.db`.
- **Git** — HEAD `d7a3b90` at the time of writing; `master` branch; no remote configured yet.
