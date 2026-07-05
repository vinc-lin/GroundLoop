# Type-2 Atlas Build — Findings & Fixes (portable across environments)

> Recorded 2026-07-05 while trying to build the full 9-repo live `atlas.db` for the Type-2 eval.
> These are **substrate-build blockers**, not code defects in the harness (E1-A..E3 pass 122 tests).
> They will recur on any machine building the atlas, so fixes belong in the tooling, not one-off ops.

## Context
- Fleet: the 9 IVI repos (`docs/type2-evaluation.md` §3.1), all cloned at `/mnt/x/code/corpora/<name>`.
- Substrate = `atlas.db` built by `gloop build-atlas` = `produce` (CodeWiki via DeepSeek) → `index`
  (CBM symbols + bge-m3 embed) → `doctor`.

## Finding 1 — `produce` is impractically slow and crashes on large repos
- **Symptom:** `gloop build-atlas --jobs 3 --concurrency 4` ran ~2h and completed **zero** wikis. The
  non-giant repos accreted docs at **~0.5 docs/min/repo**; CPU time was ~25s over ~45min elapsed → the
  produce subprocesses are **~99% I/O-wait on the DeepSeek gateway** (each module doc is a slow LLM
  round-trip; `concurrency` does not help because the gateway is the serialization point).
- **Crash on giants:** `osmand` (3,975 source files) and `organicmaps` (2,381) produce an **empty
  `module_tree.json` (`{}`) and no `metadata.json`, then exit** — the CodeWiki clustering step chokes at
  that scale. `media3` (2,595) is the third giant and follows.
- **Consequence:** `build_atlas` is **fail-fast on the produce stage** (`groundloop/build/atlas_build.py`
  — any repo with produce status "failed" aborts before `index`), so the whole build ends
  `FAILED at stage: produce` and **never indexes**. No atlas is produced.
- **Fixes (pick per goal):**
  1. **Symbol-only atlas (fast, recommended for E1):** skip `produce`; run `gloop index` directly. Symbol
     units (CBM) carry the package/class/method/`.so` tokens the Stage-1 matcher keys on, AND get bge-m3
     vectors (so E2 works too). Doc units (produce) only add prose for the E2 semantic arm and are not
     required. **Blocked by Finding 2 — must be fixed first.**
  2. **Make `build_atlas` produce-tolerant:** index the repos whose produce succeeded + all CBM symbols,
     and REPORT the produce failures instead of aborting the whole build.
  3. **Large-repo produce:** a per-repo file-count cap or module-tree chunking so the clustering step
     doesn't choke on 2k–4k-file repos (a produce-engine change; larger scope).

## Finding 2 — `gloop index` cannot build a symbol-only atlas (load_wiki hard-requires a wiki)
- **Symptom:** `index_repo` (`groundloop/engines/atlas/index.py`) calls `load_wiki(entry.wiki_dir)`
  **unconditionally**, and `load_wiki` (`groundloop/engines/lore/wiki/loader.py`):
  - `raise FileNotFoundError` if `wiki_dir` is missing (repos never produced: oboe, cameraview,
    dlt-daemon, media3), and
  - `open(module_tree.json)` + `open(metadata.json)` unconditionally — so a repo with a partial/empty
    wiki (`module_tree.json` present but **no `metadata.json`** — i.e. every repo produce touched but
    didn't finalize: gpuimage, antennapod, newpipe, osmand, organicmaps) also raises.
- **Consequence:** with **no repo currently having `metadata.json`**, `gloop index` fails on **every**
  repo — you cannot build a symbol-only atlas without first producing wikis (which Finding 1 makes
  impractical). Deadlock.
- **Fix (recommended):** make the index path tolerate a missing/incomplete wiki — return an empty
  `WikiData` (0 doc units) instead of raising, so index proceeds with **CBM symbols only**. Two options:
  1. **Non-engine (preferred, respects the migrate-as-is convention):** a `groundloop/build` helper
     `ensure_indexable_wiki(wiki_dir)` that writes a minimal valid wiki
     (`module_tree.json={}`, `metadata.json={"files_generated": [<existing *.md>]}`) when absent, and
     have `build-atlas` (or a new `--symbols-only` / `gloop index` pre-step) call it per repo. Listing
     existing `*.md` in `files_generated` also salvages any partial produce docs as doc units.
  2. **Engine tweak:** `load_wiki` returns an empty `WikiData` on a missing dir / missing metadata
     instead of raising (touches the migrated `lore` engine).
- **Interim manual unblock** (what was used to test): write `{}` → `module_tree.json` and
  `{"files_generated": []}` → `metadata.json` into each repo's `_wiki/<name>/` before `gloop index`.

## Finding 3 — CBM (`codebase-memory-mcp`) indexing is very slow in this environment
- **Symptom:** `gloop index` on a single small repo (`dlt-daemon`, C, 8 MB) with a stub wiki logs CBM
  startup (`level=info msg=mem.init budget_mb=24086 total_ram_mb=48172`) then **sits at that init for
  >2 min with no symbol-enumeration progress and a schema-only (0-unit) atlas.db** — CBM index/enumerate
  latency, not a config error (launch spec resolves: `command=['codebase-memory-mcp']`, `KLOOP_CBM_READY=1`).
- **Implication:** even symbol-only indexing of the fleet is slow; the **giants** (osmand 3,975 /
  organicmaps 2,381 / media3 2,595 files) will be far worse. This is the SAME class of blocker as
  produce (Finding 1) — the substrate build is infra-latency-bound in this environment.
- **Fixes / mitigations (portable):**
  1. Add a **per-repo timeout + progress logging** to the index path so a slow/hung CBM on one repo
     doesn't stall the whole build silently, and the operator sees which repo is churning.
  2. **Index a confusable subset first** (the 6 non-giant repos) for a runnable atlas quickly; add the
     giants when the environment/CBM is faster.
  3. **Bypass CBM for a test atlas:** a lightweight source-scan symbol extractor (walk source for
     `package`/`class` decls + `.so`/native symbols → symbol units → bge-m3 embed → `Store.reindex_repo`)
     produces a real, matchable atlas deterministically in minutes without CBM or produce. Legitimate as
     a TEST substrate (the eval doesn't care how units were produced, only that they exist + match).

## Finding 4 — orphaned CBM servers accumulate across sessions (cleanup needed)
- **Symptom:** 5 `codebase-memory-mcp` server processes (+ their `uv tool uvx` launchers) were found
  running **6–9 days old**, left over from prior index/produce sessions. NOT a memory problem here
  (each has a 24 GB *budget* but actual RSS was small — total used ~10 GB of 48 GB), but they are a
  process leak and a potential source of contention/confusion.
- **Fix:** the CBM client lifecycle should reap its server on exit (`CBMClient.aclose`), and the build
  tooling should offer a `--reap-cbm` / pre-run cleanup (`ps -C codebase-memory-mcp` → kill) since
  interrupted runs (Ctrl-C, tool timeouts) orphan the server. Portable cleanup:
  `kill -9 $(ps -C codebase-memory-mcp -o pid=)` before a fresh build.

## Recommended path to a runnable full atlas
1. Fix Finding 2 (make index wiki-tolerant) — the true unblock.
2. Resolve Finding 3 (confirm CBM completes per repo; add per-repo timeout/progress if slow).
3. Run `gloop index` over the 9-repo registry → symbol-only (+ partial doc) `atlas.db`; `gloop doctor`.
4. `gloop mine` the fleet + `gloop eval` → the real benchmark scorecard.
