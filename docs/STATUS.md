# GroundLoop — Status

**As of 2026-07-04** (blocker re-checked & cleared 2026-07-05). Read this first when resuming; see
`CLAUDE.md` for durable project context.

**Docs are now the single source of truth** (consolidated 2026-07-04 from `../loop-agent` +
`../knowledgeLoop`, which now carry "canonical → GroundLoop" banners): [`charter.md`](charter.md)
(mission + FR/NFR), [`application-guide.md`](application-guide.md) (how it's applied + scenarios),
[`architecture.md`](architecture.md) (7-port hexagonal), [`engines.md`](engines.md)
(produce/lore/CBM/atlas ops), [`roadmap.md`](roadmap.md) (mining + two-stage matcher),
[`downstream-fix-loop.md`](downstream-fix-loop.md) (fix-stage design provenance). Milestone tracks are
namespaced **GL-M0/GL-M1** (GroundLoop) vs **BFL-M0..M9** vs spec **M1–M5** — never a bare "M1".

## Done

### GL-M0 — walking skeleton
Deterministic ticket → repo → fix → bind loop over the mock adapters + `TokenIndex` stub + offline
grader. Hermetic vertical slice green.

### GL-M1 — real index (consume + build)  ·  17 tasks, final review PASS
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
    shim WORKS end-to-end (the M1 "latent risk" is now cleared). The `gloop produce` model default is
    now **`deepseek-chat`** (was `gpt-4o-mini` — unusable here: the gateway has no OpenAI backend).
  - ✅ Fixed: CBM launches the bare `codebase-memory-mcp` binary, so `.venv/bin` must be on `PATH`
    (now exported in `.env`).
  - ✅ **Test 2 (Type-2) live acceptance GREEN (2026-07-05):** both gated `tests/e2e/` tests pass live
    (`test_index_build_live` = produce→CBM→bge-m3 embed→atlas.db, 2:13; `test_produce_live` = wiki gen).
    First-ever execution surfaced + fixed two issues: a **missing `groundloop/cli/__main__.py`** (the
    tests invoke `python -m groundloop.cli`, which had no runnable entry) and the produce smoke's fragile
    asserts (retargeted to produce's real deliverable — `metadata.json` + a per-module `*.md`; `overview.md`
    / a non-empty `module_tree.json` are not reliably emitted for tiny repos).

## Current blocker — CLEARED ✅ (2026-07-05)
The pinned `bge-m3` embedding host is **back UP** — re-checked 2026-07-05: `/embeddings` → HTTP `200`,
returns a valid 1024-dim non-zero vector. The prior `000`/hung state (GPU/Ollama backend down) is
resolved. **No open blocker.** The full `gloop index` build (produce → CBM → embed → atlas.db) and the
2 gated live tests (`tests/e2e/`) are now unblocked. `deepseek-chat` (produce LLM) remains up.
Gate check (prints `200` when healthy): see `docs/type2-eval-setup.md` → "Embedding-host gate".

## Next steps
1. **Now unblocked (bge-m3 up 2026-07-05) — run the GL-M1 live acceptance:** `gloop produce` +
   `gloop index` over `/mnt/x/code/corpora/atlas.toml` → build `~/.groundloop/atlas.db`; `gloop doctor`;
   then run the gated live tests (`tests/e2e/`) with `KLOOP_EMBED_API_KEY` + `KLOOP_CBM_READY=1` +
   `KLOOP_PRODUCE_READY=1`. Runbook: `docs/type2-eval-setup.md`.
2. **Symbol filtering** before scaling the fleet — android-gpuimage-plus yields ~31k symbols because it
   vendors ffmpeg headers; drop vendored `ffmpeg/**` to cut embedding cost + noise. (Small follow-up.)
3. **Grow the eval fleet** — uncomment `libxcam` / `ndk-samples` in `corpora/atlas.toml`; a meaningful
   Stage-1 match needs several confusable repos so a `1/N` guess scores far below a real match.
4. **Real `AgentFixEngine`** (the fix stage), then `gloop mine` (mined tickets + logs; aspirational — not
   built yet), ANN vector index,
   Tier-3 grading.

## Services / environment
- **LiteLLM gateway** — creds in the gitignored `/mnt/x/code/loop-agent/.env`, reused by
  `GroundLoop/.env`. Serves: `deepseek-chat`/`deepseek-reasoner` (UP), `bge-m3` (**UP** as of 2026-07-05,
  1024-dim) + `mxbai-embed-large` + `qwen3` (GPU/Ollama-backed — `qwen3` DOWN at last check).
- **Corpora** — `/mnt/x/code/corpora/` at pinned SHAs (`corpus.toml`): android-gpuimage-plus, libxcam,
  ndk-samples. Registry: `corpora/atlas.toml`. Built atlas.db target: `~/.groundloop/atlas.db`.
- **Git** — HEAD `d7a3b90` at the time of writing; `master` branch; no remote configured yet.
