# Type-2 Atlas Build — Findings & Fixes (portable across environments)

> Recorded 2026-07-05 while trying to build the full 9-repo live `atlas.db` for the Type-2 eval.
> These are **substrate-build blockers**, not code defects in the harness (E1-A..E3 pass 122 tests).
> They will recur on any machine building the atlas, so fixes belong in the tooling, not one-off ops.

## Context
- Fleet: the 9 IVI repos (`docs/type2-evaluation.md` §3.1), all cloned at `/mnt/x/code/corpora/<name>`.
- Substrate = `atlas.db` built by `gloop build-atlas` = `produce` (CodeWiki via DeepSeek) → `index`
  (CBM symbols + bge-m3 embed) → `doctor`.

## ✅ CONFIRMED ROOT CAUSE & FIX (2026-07-05, supersedes the theories in Findings 3 & 5)

The "CBM hang" is a **30-second timeout tripping a minutes-long call**. Proven with a direct probe
(`enumerate` returns 31,745 real nodes for gpuimage in **13 s** on native ext4; the same op hangs on
the `/mnt/x` mount / under contention). Mechanism:

1. `index_repo` builds the whole symbol graph via `forward.index_repository` →
   `CBMClient.call_tool_with_restart` → `call_tool(read_timeout_seconds=call_timeout)`.
2. `CBMClient`'s default `call_timeout` is **30 s** and `index_repo` never overrode it. A **cold**
   `index_repository` graph build takes seconds on fast disk but **minutes** on the `/mnt/x` v9fs mount
   (or under contention from a second index).
3. At 30 s the call raises → `call_tool_with_restart` runs `_restart` = `aclose()` + `start()` **on a
   still-indexing subprocess**. The mcp stdio client is then left blocked in `poll()` **forever**
   (`wchan: do_sys_poll`, state S) — no error, no progress. CBM keeps building its cache in the
   background (hence the orphaned 54–58 MB `~/.cache/codebase-memory-mcp/*.db` files), but the client
   is dead-hung and stores **0 units**.

**Two independent amplifiers, one trigger:**
- **Slow FS:** the `/mnt/x` v9fs Windows-drive mount makes cold CBM builds minutes-long (they are ~5 s
  on native ext4). **Fix: build the atlas from a native-ext4 copy of the repos**, not `/mnt/x`.
- **Contention:** concurrent `gloop index` jobs slow each other past 30 s. This kept recurring because
  **process-liveness checks were wrong** (see Finding 6) so "reaped" orphans were still alive.

**THE CODE FIX (landed, portable — carry this to every environment):** give the index call a generous,
env-configurable timeout instead of 30 s.
- `Settings.cbm_index_timeout` (env `KLOOP_CBM_INDEX_TIMEOUT`, default **1800 s**; invalid/≤0 → default).
- `index_all`/`index_repo` take `call_timeout=`; `cli/_run_index` passes `settings.cbm_index_timeout`;
  `index_repo` constructs `CBMClient(..., call_timeout=call_timeout)`. Query calls return in ms so the
  high ceiling never bites them. (`groundloop/engines/atlas/index.py`, `config/settings.py`,
  `cli/__init__.py`; tests in `tests/test_settings.py`.)

## Finding 6 — process-liveness checks must not use `ps -C` (the load-bearing ops gotcha)
- The `gloop` entry-point process has `comm=gloop` (**not** `python`), and `codebase-memory-mcp` is
  truncated to `comm=codebase-memory` (Linux 15-char `comm` limit). So `ps -C python | grep 'gloop
  index'` and `ps -C codebase-memory-mcp` **never match** — every "nothing running" check read clean
  while a 38-minute orphan was still indexing, and every comm-scoped "reap" killed nothing. This is why
  the contention in Finding 5 kept coming back.
- **Fix:** check/kill with full-arg matching: `pgrep -fa 'gloop index'`, `pgrep -fa 'codebase-memory'`
  (guard against matching your own shell). Confirm zero before starting a build; kill by PID.

## Finding 7 — embedding is the real time cost, not CBM (once the hang is fixed)
- With CBM fixed, `index_repo`'s long pole is `GatewayEmbedder.embed`: it POSTs the bge-m3 gateway in
  batches of 64, and each symbol unit's text is source-enriched (large). gpuimage alone = **31,745
  units ≈ ~500 gateway round-trips**; the giants (organicmaps 600 MB, media3 518 MB source) will be
  much larger. A full-fleet index is **tens of minutes to a few hours**, dominated by embedding.
- **Consequence / ops:** run the full index **detached** (never under a short foreground tool timeout —
  a SIGTERM mid-embed orphans CBM again) and let it fill the atlas repo-by-repo (`reindex_repo` is
  per-repo, so partial progress is durable). Small repos first → a usable multi-repo atlas early.
- **Later (optional):** filter trivial symbol kinds (Fields) or drop source-enrichment to cut embed
  volume; both are quality trade-offs, not needed for Stage-1 matching. YAGNI for now.

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

## Finding 3 — CBM is SLOW, not hung; premature timeouts/kills faked the "hangs" (PARTIAL — see CONFIRMED ROOT CAUSE above)
- **Initial misread:** `gloop index` logs CBM startup (`level=info msg=mem.init budget_mb=24086
  total_ram_mb=48172`) then appears to "sit" there for minutes with a 0-unit atlas.db, so it looked hung.
- **Actual root cause (proven on disk):** `mem.init` is only an EARLY log line; CBM then works **silently**
  for minutes, building a **per-project cache db** at `~/.cache/codebase-memory-mcp/<path-slug>.db`. Those
  dbs are large and real — `mnt-x-code-corpora-android-gpuimage-plus.db` grew to **54 MB**, `antennapod`
  46 MB, `newpipe` 39 MB, `oboe` 32 MB — i.e. **CBM WAS indexing the whole time**. `gloop index` only
  prints `indexed <repo>: <n>` AFTER `enumerate_all_nodes` finishes, so the atlas shows 0 units until a
  repo fully completes. dlt-daemon (8 MB db) completes in ~2.5 min; a 54 MB gpuimage db needs ~15-20 min.
- **What actually broke it:** applying **240s/420s per-repo timeouts and `kill -9`** cut CBM off
  mid-build. Not memory (33 GB free, no leaked `/dev/shm` / SysV segments) — just impatience. And the
  hard kills left partial/locked project dbs behind, compounding the confusion.
- **The real fix (portable, and the one to carry to other environments):**
  1. **Be patient — no aggressive per-repo timeout.** Budget minutes-to-tens-of-minutes per repo (scales
     with the db size / file count; giants take longest). Watch the project db **growing** in
     `~/.cache/codebase-memory-mcp/` as the true progress signal, not the atlas unit count.
  2. **Never `kill -9` CBM.** `index_repo` already `aclose()`s the client gracefully in a `finally`; let
     it. A hard kill mid-index leaves a partial/locked project db.
  3. **Clean project dbs for a fresh build** (`rm ~/.cache/codebase-memory-mcp/<slug>.db`) if a prior run
     was hard-killed, so CBM rebuilds from a clean state.
  4. Optional ergonomics: add per-repo progress logging to the index path (log the db size / a heartbeat)
     so an operator sees CBM working rather than guessing it's hung. A **generous** watchdog (e.g. no
     growth for N minutes → warn) is fine; a short hard timeout is not.
  - NB: a lightweight source-scan indexer (`groundloop/build/lite_index.py`) exists as an emergency
    fallback, but it is LOW-FIDELITY (regex package/class/.so only; dlt-daemon → 21 units vs CBM's 4,565)
    and must NOT be used as the real substrate — CBM's symbol graph is the real thing.

## Finding 4 — orphaned CBM servers accumulate across sessions (cleanup needed)
- **Symptom:** 5 `codebase-memory-mcp` server processes (+ their `uv tool uvx` launchers) were found
  running **6–9 days old**, left over from prior index/produce sessions. NOT a memory problem here
  (each has a 24 GB *budget* but actual RSS was small — total used ~10 GB of 48 GB), but they are a
  process leak and a potential source of contention/confusion.
- **Fix:** the CBM client lifecycle should reap its server on exit (`CBMClient.aclose`), and the build
  tooling should offer a `--reap-cbm` / pre-run cleanup (`ps -C codebase-memory-mcp` → kill) since
  interrupted runs (Ctrl-C, tool timeouts) orphan the server. Portable cleanup:
  `kill -9 $(ps -C codebase-memory-mcp -o pid=)` before a fresh build.

## Finding 5 — concurrent index jobs contend (an AMPLIFIER, not the root — see CONFIRMED ROOT CAUSE above)
- **Symptom:** the *same* repo (dlt-daemon) that indexed cleanly in 2.5 min in isolation would "hang" in a
  later run. Looked non-deterministic.
- **Root cause:** during debugging, multiple `gloop index` jobs were left running at once (a full-fleet
  index + a per-repo retry loop + "fresh" attempts) because prior background jobs weren't fully killed.
  **Concurrent CBM indexes contend for the machine** (each spins up its own `codebase-memory-mcp` with a
  24 GB budget + heavy I/O over the slow `/mnt/x` v9fs), so every one stalls — reading as a hang. The
  ONE time CBM had the box to itself, it worked. This — not repo content, not memory, not cache
  corruption — was the dominant "flakiness."
- **Fix (the load-bearing operational rule):** run **exactly ONE `gloop index` at a time**. Before
  starting, verify nothing is left: `ps -C python,timeout,codebase-memory-mcp` shows no `gloop index` /
  `codebase-memory-mcp`. Kills must be comm-scoped (`ps -C python … | grep 'gloop index'`) so cleanup
  doesn't accidentally match the operator's own shell. Combined with Finding 3 (patience, no hard
  timeout) and Finding 4 (reap orphans, gracefully), a single clean sequential index builds the fleet.

## Finding 8 — `/home/vinc/code` is a symlink to `/mnt/x/code` (v9fs); "native ext4" was illusory
- **Discovery:** an eval worker's open fd resolved `/home/vinc/code/corpora-local/atlas.db` to
  **`/mnt/x/code/corpora-local/...`** — `ls -ld /home/vinc/code` → `-> /mnt/x/code`. So the entire
  `corpora-local` tree (repos, atlas.db, dataset) built under `/home/vinc/code/...` has been on the
  **9p/v9fs Windows-drive mount all along**, never real ext4. Real native ext4 is `/home/vinc`
  **directly** (`/dev/sdd`), or `/var/tmp`, or `/dev/shm` (tmpfs).
- **Correction to the CONFIRMED-ROOT-CAUSE section:** the CBM speedup earlier was **not** native-vs-v9fs;
  it was the **1800s timeout fix + killing orphan contention**. v9fs is NOT the CBM bottleneck for
  normal repos (small repos index fine on it). It IS a bottleneck for two things: (a) **`sqlite` random
  reads over the large atlas during `gloop eval`** — `wchan=p9_client_rpc`, state D; the 187-case eval
  went from >14 min (v9fs, unfinished) to **70 s** after copying atlas+dataset to real ext4; and (b)
  large repos where per-file 9p round-trips add up.
- **Fix (portable):** for `gloop eval`, always stage `atlas.db` + the dataset onto **real ext4**
  (`/home/vinc/gl-eval`, `/var/tmp`), never a `/mnt/x` path (even a symlinked one). Verify with
  `df -T <path>` (want `ext4`, not `9p`) and `realpath`.

## Finding 9 — CBM CPU-churns (restart-loops) on huge single source files; exclude tests + `3party`
- **Symptom:** repo 8 (`media3`) never produced a CBM cache after 30 min; the log showed **9 `mem.init`**
  (CBM restarts) and CBM at **100% CPU** (`futex_wait_queue`, not I/O-wait). `organicmaps` (repo 9) is
  the same shape. This is content-specific, **not** the mount.
- **Cause:** pathologically large source files blow up CBM's parser/AST. `media3`:
  `ExoPlayerTest.java` **651 KB**, `SimpleBasePlayerTest.java` 361 KB, several 200–300 KB test classes —
  all under `src/test/` / `src/androidTest/`. `organicmaps`: `3party/GL/glext.h` 760 KB,
  `geometry_tests/large_polygon.hpp` 420 KB, `3party/stb_image/stb_image.h` 272 KB.
- **Fix (also more correct for Stage-1 matching):** exclude **test dirs** (`test`, `tests`,
  `androidTest`, `testing`, `*_tests`) and **vendored `3party`** before indexing — a defect is owned by
  the repo's **own** `src/main`/`libs` code, not its tests or third-party libs, so this *improves*
  ownership signal while removing the churn. `rsync -a --exclude=test --exclude=androidTest
  --exclude='*_tests' --exclude=3party …` to real ext4, then `gloop index` those repos into the atlas.
  (Trade-off noted: the other 7 repos were indexed *with* tests — mixed handling, negligible for
  matching. A future `index_repository` exclude-glob would make this uniform.)

## Finding 10 — `gloop fixeval` materializes the WHOLE repo PER CASE; stage `--repos` on ext4 too
- **Symptom (2026-07-07):** every `gloop fixeval` on the v9fs `--repos` (`/mnt/x/code/corpora-local`)
  crawled — a 278-case run took hours, and short-timeout preview runs died mid-materialization (STAT `D`,
  I/O-wait) before making a single model call.
- **Cause:** `GitFixtureEstate.materialize` (`groundloop/adapters/estate.py`) does, **for every case**,
  `rmtree` → `shutil.copytree(<repo>)` from `--repos` → `git init/add -A/commit` — a full repo copy +
  commit with **no caching** (it re-copies every call). Over v9fs that is minutes per case (per-file 9p
  round-trips), repeated for all N cases.
- **Fix (portable, measured):** stage `--repos` on **real ext4** — `cp -a /mnt/x/code/corpora-local/<repo>
  /home/vinc/gl-eval/corpora-fast/` once (one v9fs read), then `gloop fixeval --repos
  /home/vinc/gl-eval/corpora-fast`. Per-case materialization drops from minutes to **~seconds**
  (antennapod 22 MB → 35 s copy; a 6-case A/B incl. extraction then ran in ~15 min). This EXTENDS Finding
  8: for `gloop eval` stage atlas + dataset on ext4; for `gloop fixeval` **also stage `--repos`**. (A
  caching materialize — reuse an existing work-tree instead of rmtree+recopy — would remove the per-case
  cost entirely; an adapter change, future.) See `docs/2026-07-07-claim-kb-preview-findings.md`.

## First real eval — matcher & dataset findings (Type-2, 2026-07-05)
Ran `gloop eval` on the mined GitHub-issue dataset over the real atlas (6-repo preview, 187 cases;
9-repo run pending the two excluded repos). The benchmark did its job — it exposed real weaknesses:
- **Dataset is signal-sparse.** Only **14% (27/187)** of mined GitHub issues contain any code signal
  (stack trace / FQ class / `.so`). 86% are user prose. The `AndroidSignalExtractor` is built for AAOS
  **logcat/stack** tickets and finds nothing in prose. → the mine should **filter for stack/log-bearing
  issues**, or the loop needs a prose-aware query.
- **Forced recall@1 = 0.03 is a tie-break artifact.** Empty signals → `rank_repos` ties → the tie-break
  deterministically picks the **alphabetically-first** repo (gpuimage) for all 160 tied cases → below
  random. The **selective/Φ_c** view (abstains on no-signal cases) is the honest lens; the loop should
  **abstain**, not force-pick, on empty signals.
- **On the 27 signal-bearing cases: recall@1 = 0.22, recall@3 = 0.81.** The matcher *does* retrieve the
  owning repo (top-3 81%), but a **size/density bias** in FTS costs rank@1 for small repos (antennapod
  6/8 correct; newpipe 0/12, cameraview 0/5, oboe 0/2 — top-3 but not #1). The bias **worsens as the
  fleet grows**: at 8 repos (osmand 147k + media3 71k units added) signal-bearing recall@1 fell to 0.17
  and recall@3 to 0.47 — the two biggest repos win their cases, the small repos get 0.
- **A naive IDF "size-normalization" fix was tried and REFUTED by the eval — reverted (grounding over
  narrative).** Scoring each matched token by `log(N/df)` (df = #repos with the token, via a no-top-k
  `token_repo_hits`) drove signal-bearing recall@1 **0.17 → 0.00** (recall@3 ~flat 0.47 → 0.50). Cause:
  `store._fts_query` OR-expands camelCase into generic sub-words (`PlayerService` → `Player`, `Service`),
  so nearly every signal token matches many repos → high df → idf ≈ 0 → all repos tie → the alphabetical
  tie-break is wrong. **Lesson:** the size-fix must account for the sub-word expansion — candidates to try
  *eval-driven* next: bm25-rank aggregation (already sub-word IDF at the unit level), exact-name/qualified-
  name df (no OR-expansion), or a mild `count / log(repo_units)` penalty. NB: `rank_repos` is the SP1b
  closed-loop-reject dependency — **coordinate before changing its behavior.**
- **All four arms key off the same sparse tokens.** `TextOnlyExtractor` = `AndroidSignalExtractor` on the
  description; `SemanticAtlasIndex._query` = `" ".join(signals.tokens())`. So the **semantic arm embeds
  tokens, not raw prose** — it does NOT rescue the signal-sparse cases. Prose-aware matching needs a new
  extractor that feeds raw text to the embedder (a change, not "as-is").
- **Perf note:** `Store.vector_search` is a **brute-force** full scan (reads every unit's 1024-float
  JSON vector, cosines in Python) — fine at small scale, slow over a 200k+-unit atlas. Only signal-
  bearing cases trigger it (empty-signal cases skip via `if q.strip()`). A vector index (sqlite-vss /
  faiss) is the eventual fix.

## Recommended path to a runnable full atlas
1. Fix Finding 2 (make index wiki-tolerant) — the true unblock.
2. Resolve Finding 3 (confirm CBM completes per repo; add per-repo timeout/progress if slow).
3. Run `gloop index` over the 9-repo registry → symbol-only (+ partial doc) `atlas.db`; `gloop doctor`.
4. `gloop mine` the fleet + `gloop eval` → the real benchmark scorecard.

## Real testing achieved — synthesized failure-log dataset (2026-07-05)
The GitHub-issue dataset is ~87% prose (only ~13% carry code signal), so the matcher measured 0.02
recall@1 — an artifact, not a test. Fix (`groundloop/synth/`): synthesize AAOS-realistic logcat /
native-backtrace tickets from each mined case's fix-commit changed files, naming the owner's REAL
crash-site symbols pulled from the atlas (the grounded signal a triager reads; matched via the atlas,
never the repo name; test files excluded). 212 cases from 261.
- **First MEANINGFUL scorecard:** `membership+logs` recall@1=**0.60**, mrr=0.73, coverage=0.79,
  Φ_1=**+0.31** (vs `membership+text`=0.02 — the description is still prose, so this also proves logs
  are the signal). recall@3=**0.80**.
- **Size-bias quantified precisely:** native repos with unique `.so` win outright (dlt-daemon 26/26,
  oboe 42/45); small Java repos have the answer but lose rank@1 to giants (newpipe 6/47 @1 but 25/47
  top-3; cameraview 1/11 @1 but 8/11 top-3). The recall@1→recall@3 gap (0.60→0.80) IS the size tax.
- **Unblocks the size-fix eval-driven** (target: close the gap, lift small-repo rank@1 without hurting
  the native/big repos) — the test the IDF attempt lacked. Coordinate on `rank_repos` (SP1b dep).
