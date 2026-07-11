# GroundLoop — Engines (produce / lore / CBM / atlas)

Operational knowledge for the four engines GroundLoop **migrated as-is** from the knowledgeLoop
source (`/mnt/x/code/knowledgeLoop/knowledgeloop/`) into `groundloop/engines/`. Migration =
copy the file, rewire `knowledgeloop.*` → `groundloop.engines.*`, preserve logic verbatim (only the
import rewire + the `_envcompat` shim). This doc re-skins the commands to **`gloop`**, the config to
**`KLOOP_*`**, and the system name to **GroundLoop**; it is the hands-on companion to
[architecture.md](architecture.md). For the deepest per-engine reference (generation provider matrix,
the full consume spec, deploy design), link out to the source docs under `../../knowledgeLoop/docs/`
— do not copy them.

> **Naming.** The source docs call the integrated system "knowledgeLoop" and use a `kl`/`repo_atlas`
> CLI plus `REPO_MEMORY_*` env. That system **is GroundLoop**. The GroundLoop CLI is **`gloop`**
> (`run` · `index` · `produce` · `doctor`) — there is no `kl`, `kloop`, or `bfl`. The migration
> **source** engine still lives at `/mnt/x/code/knowledgeLoop` (a separate live repo; do not rename).

---

## 1. Provenance & capabilities

The engines implement one pipeline — **produce → bridge → consume**, extended by a **cross-repo
atlas** — that GroundLoop consumes as a library behind the `CodeIndex` port and the `gloop`
subcommands (it does **not** re-expose the knowledgeLoop standalone MCP servers as `gloop`
subcommands; see the per-engine notes).

```
  PRODUCE                 BRIDGE                  CONSUME                 CROSS-REPO ATLAS
  produce/ (CodeWiki) →   lore/bridge/         →  lore/ facade        +   atlas/  (one SQLite
  a wiki bundle           entity_map.json         (wiki + CBM graph)      store over many repos)
  (*.md + module_tree)    module → files+syms     freshness-aware Q&A     FTS5 keyword ⊕ vector, RRF
```

- **`produce/`** — CodeWiki: parses a repo with **tree-sitter (~9 grammars pinned in
  `pyproject.toml`: python, java, javascript, typescript, c, cpp, c-sharp, php, kotlin)**, clusters
  components into a module tree, runs a per-module agent loop, and emits a Markdown/Mermaid/HTML wiki
  plus `module_tree.json` / `metadata.json`. Exposed as **`gloop produce`**.
- **`lore/`** — the bridge + grounded-facade design. `lore/bridge/` joins wiki modules to real CBM
  graph nodes (`entity_map.json`); `lore/graph/` forwards CBM's read surface; `lore/deploy.py`
  resolves how CBM is launched; `lore/repo_head.py` resolves the freshness anchor. The consume
  facade's **12-tool contract** (below) is preserved as design provenance — **note: the MCP server
  entrypoint `server.py` was not migrated**, so those tools are not served as a `gloop` command
  today; GroundLoop uses the migrated `lore/graph` + `lore/bridge` pieces as libraries under the
  `AtlasIndex` adapter.
- **CBM** — Codebase-Memory-MCP, an **unmodified pinned dependency** (`codebase-memory-mcp==0.8.1`,
  a Level-1 default hard dep) spawned as a long-lived stdio subprocess. It supplies the code graph
  (real files, symbols, call paths).
- **`atlas/`** — indexes wiki-doc + symbol "units" from every registered repo into one SQLite store
  (FTS5 keyword + vector cosine, fused with RRF). Built by **`gloop index`**; queried through the
  `AtlasIndex` adapter's `rank_repos` + `retrieve`.

### Freshness envelope (design provenance — the source docs repeat this table 4×)

Every consume-side response carries a freshness enum; precedence is **graph > wiki**. This
grounding/freshness layer is part of the consume-facade **`server.py`, which was NOT migrated** — the
table is **design provenance** (from the source consume spec), not a live GroundLoop code path today:

| State | Meaning |
|---|---|
| `fresh` | wiki + graph both aligned with `repo_head` (HEAD). |
| `stale-wiki` | only the wiki docs are behind HEAD (`wiki_commit != HEAD`); a stale wiki **never blocks** a read. |
| `stale-graph` | `graph_commit != HEAD`, **or** an entry failed verify-on-access. |
| `unverified` | can't tell — no CBM, or `repo_head` / `entity_map.graph_commit` unknown. |

Recovery from `stale-graph`/`unverified` is `refresh_index` (re-index the graph + rebuild
`entity_map.json` with `graph_commit = repo_head`). It **does not** regenerate wiki docs, so a stale
wiki stays `stale-wiki` after a refresh — that requires a produce `--update` re-run.

---

## 2. Produce ops (CodeWiki)

`gloop produce --repo <path> --out <wiki_dir>` generates a wiki for one repo. Run it with an
**absolute `--out`** (a relative path can land inside a read-only corpus checkout). Output lands in
`<wiki_dir>`: per-module `<Module>.md` (Mermaid fenced inline), `overview.md`, `module_tree.json`
(the canonical live tree) + `first_module_tree.json` (cached clustering), and `metadata.json`.
`metadata.generation_info.commit_id` is the **freshness anchor** the bridge/atlas layers read.

> **Artifact reliability (verified 2026-07-05).** The **reliable** evidence that produce succeeded is the
> per-module `<Module>.md` docs plus `metadata.json` — assert on those. On a small single-module repo,
> produce can succeed (exit 0, a real per-module doc written) while `overview.md` is **listed in
> `metadata.files_generated` but not written to disk** and `module_tree.json` is **`{}`** (empty). So do
> **not** treat `overview.md`'s existence or a non-empty `module_tree.json` as a produce-success check —
> the Type-2 `tests/e2e/test_produce_live.py` originally did and failed on a trivial repo; it now asserts
> on `metadata.json` + a per-module `*.md`.

### Model config surface (env-driven; **deepseek-chat** is the working default)

GroundLoop's gateway serves **deepseek-chat / deepseek-reasoner + bge-m3 / mxbai / qwen3** — there is
**no OpenAI access here**. Produce is live-validated on **`deepseek-chat`**; the old code default
`gpt-4o-mini` is **corrected** to deepseek-chat and is not usable in this environment. `gloop produce`
reads its config from `KLOOP_PRODUCE_*` env (no persisted `config set` step in the `gloop` path):

| Env var | Default | Purpose |
|---|---|---|
| `KLOOP_PRODUCE_MAIN_MODEL` | `deepseek-chat` | per-module doc-generation model |
| `KLOOP_PRODUCE_CLUSTER_MODEL` | `deepseek-chat` | module-clustering model |
| `KLOOP_PRODUCE_FALLBACK_MODEL` | `deepseek-chat` | fallback model |
| `KLOOP_PRODUCE_BASE_URL` | `""` | OpenAI-compatible gateway base URL |
| `KLOOP_PRODUCE_API_KEY` | `$OPENAI_API_KEY` | gateway key |
| `KLOOP_PRODUCE_PROVIDER` | `openai-compatible` | provider mode |
| `KLOOP_PRODUCE_AWS_REGION` | `us-east-1` | bedrock region (unused for the gateway) |

### The ModelProfile framework (`engines/produce/src/be/model_profiles.py`)

Per-model operational parameters are **declarative**, not hand-tuned. A `ModelProfile` (output cap,
request budget, granularity, token-param style, max depth, temperature) is resolved from provider
defaults + a per-model registry + overrides. The load-bearing heuristics:

- **Granularity is derived from the output cap** — don't guess: `leaf ≈ cap × 0.85`,
  `cluster ≈ cap × 1.4`. Too-large granularity → a first doc-write overflows the output cap → a lost
  doc. Small-output models (e.g. deepseek-chat, ~8K cap) get finer granularity so modules split.
- **Budgets are intentionally fail-fast.** A stuck sub-module agent should bail quickly, because the
  **parent module agent back-fills the missing doc afterward** (parent-recovery) — so **warnings ≠
  gaps**; most failures self-heal, and a deterministic missing-doc sweep fills the rest. **Do not
  "fix" failures by raising the request limit** (50→200 wastes ~7–8 min per stuck module for an
  identical outcome).

### Main failure modes

| Failure | Root cause / handling |
|---|---|
| Input overflow (~1M tokens) | Clustering skipped → whole-repo mode reads everything into one context. Fixed by forcing clustering (granularity-from-cap makes this automatic). |
| Request-limit pre-write loop | Agent exhausts its budget before writing any file. A true gap needs *(a sub-module that never wrote) × (a parent already finished)* — otherwise parent-recovery heals it. |
| Output-cap overflow | A single doc-write larger than the model's output cap is rejected. `ModelProfile.decompose_on_overflow` (default on) retries in *decompose* mode instead of dropping the doc. |

**Honest limit:** the output cap is a hard quality ceiling — the framework makes overflow *graceful*
(split + recovery), not absent. The one-line remedy is a larger-output model; within this gateway,
deepseek-chat + the profile is the practical best (~95% on the reference C-codebase run). Scope runs
tightly (`--exclude` vendored/test/generated dirs) — tighter scope = better signal, less cost. Full
generation flag matrix + provider details: `../../knowledgeLoop/docs/applying-to-a-new-repo.md`,
`../../knowledgeLoop/docs/CODEWIKI.md`, and the operational lessons in
`../../knowledgeLoop/docs/findings-and-practices.md`.

---

## 3. lore / CBM

The lore facade fuses the produce wiki (the *what/why*) with the CBM code graph (the verifiable
*where*) behind one freshness-aware endpoint. Its capability contract (provenance — the entrypoint
`server.py` was **not** migrated):

### The 12 tools (registration order; every response carries the freshness + provenance envelope)

| Tool | Backing | Purpose |
|---|---|---|
| `get_repo_overview` | Wiki | High-level repo overview (use FIRST) |
| `list_modules` | Wiki | List wiki module names / boundaries |
| `search_wiki` | Wiki | Keyword (substring) search over module docs |
| `get_module_doc` | Wiki | One module's doc + path + components |
| `get_related_files` | Bridge | Map a wiki module → real files+symbols (graph-verified); also returns `unmatched` |
| `search_code_graph` | Graph | Structural symbol search (`name`/`label`/`file`, `limit=200`) |
| `trace_symbol` | Graph | Caller/callee call-path trace (`direction="both"`, `depth=3`) |
| `get_code_snippet` | Graph | Source for a symbol by `qualified_name` |
| `get_architecture` | Graph | Graph-level architecture summary |
| `explain_with_sources` | Hybrid | How/why answer with graph-verified evidence (read-only; never blocks) |
| `assess_impact` | Hybrid | Fail-closed blast-radius — the **only** gating tool |
| `refresh_index` | Recovery | Re-index graph + rebuild the Wiki↔Graph map (NOT wiki regen) |

Graceful degradation is pervasive: CBM spawn failure → `state.cbm = None` and wiki-only tools keep
answering; graph/hybrid tools that need the repo indexed degrade with `repo not indexed in CBM (run
refresh_index)` rather than crashing. Only `assess_impact` fail-closes on `require_fresh` (True only
if `cbm is not None` **and** `repo_head` is set **and** `entity_map.graph_commit == repo_head`).

### entity_map confidence tiers (`lore/bridge/`)

The bridge grades each wiki-component → graph-node match:

| Tier | Confidence |
|---|---|
| `exact` | 1.0 |
| `qualified_suffix` | 0.85 |
| `file_only` | 0.5 |
| `unmatched` | 0.0 |

`get_related_files` returns the average entry confidence as the envelope's `confidence` field, and
the unresolved components under `unmatched`.

### CBM deploy (`lore/deploy.py`)

CBM is spawned as one long-lived stdio subprocess. **In GroundLoop the Level-1 default launches the
installed binary `codebase-memory-mcp`** (it is a pinned dep on PATH via `.venv/bin`), **not `uvx`** —
no network fetch at launch. `DEFAULT_CBM_VERSION = "0.8.1"` is kept for reference/doctor checks.
`resolve_launch_spec(environ)` picks a profile and builds the command/env/cwd:

| Profile | Use | Requires cache dir | Sets |
|---|---|---|---|
| `dev` | local default | no | — |
| `ephemeral` | per-task sandbox | yes | `CBM_LOG_LEVEL=warn` |
| `shared` | long-lived warm index | yes | `CBM_SEMANTIC_ENABLED=1`, `CBM_SQLITE_MMAP_SIZE=1073741824` |
| `ci` | reproducible, restorable cache | yes | `CBM_LOG_LEVEL=warn` |

**Override env prefixes (verified in code — these are the exception to the `KLOOP_*` rule).** The
deploy knobs are read through the `_envcompat` shim (`getenv_compat(new, legacy)`): the **new** prefix
is **`KNOWLEDGELOOP_CBM_*`**, the **legacy** fallback is **`REPO_MEMORY_CBM_*`** (a deprecation
warning fires on the legacy name). They are **not** `KLOOP_CBM_*`:

| Knob | Env (new / legacy) |
|---|---|
| Full command override | `KNOWLEDGELOOP_CBM_COMMAND` / `REPO_MEMORY_CBM_COMMAND` |
| Profile | `KNOWLEDGELOOP_CBM_PROFILE` / `REPO_MEMORY_CBM_PROFILE` (default `dev`) |
| Subprocess cwd | `KNOWLEDGELOOP_CBM_CWD` / `REPO_MEMORY_CBM_CWD` |

Raw `CBM_*` knobs are **intentionally un-prefixed** and pass straight through (precedence:
profile env → environ knob → explicit `cache_dir`): `CBM_CACHE_DIR`, `CBM_WORKERS` (1–256, else
dropped), `CBM_LOG_LEVEL`, `CBM_DIAGNOSTICS`, `CBM_SEMANTIC_ENABLED`, `CBM_SEMANTIC_THRESHOLD`,
`CBM_LSP_DISABLED`, `CBM_SQLITE_MMAP_SIZE`. Separately, **`KLOOP_CBM_READY`** is a GroundLoop-level
gate flag (checked by `gloop doctor`), distinct from the launch overrides above.

**The clean-env / PRESERVE_ENV gotcha.** The MCP SDK merges the child env over a **clean**
`get_default_environment()`, not the parent's. `deploy.PRESERVE_ENV` re-injects the vars CBM needs if
present: `HOME, XDG_CONFIG_HOME, APPDATA, LOCALAPPDATA, PATH, TMP, TEMP, USERPROFILE`. If you bypass
`resolve_launch_spec` and build env yourself, include them or CBM may fail to find its cache/config.

**Why the `==0.8.1` pin.** Only `0.8.1` resolves on the package index — the CBM repo's `server.json`
says `0.7.0` and the latest git tag is `v0.8.0`, but neither resolves. It is pinned in `pyproject.toml`
as a hard dependency; the deploy default therefore runs the installed binary. Full deploy-profile
reference: `../../knowledgeLoop/docs/repo_memory-deploy.md`; the consume spec (12 tools, guarantees,
non-goals): `../../knowledgeLoop/docs/MVP.md` and `.../close-loop-workflow.md`. The feed-back arrow
(agents writing execution results back into the KB) remains **aspirational / not built**.

---

## 4. atlas ops (cross-repo retrieval)

Mental model: **produce → lore/bridge → atlas**. The atlas indexes wiki-doc + symbol units from many
registered repos into one SQLite store. CBM is touched only at **index** time (to enumerate symbols);
queries hit only SQLite. GroundLoop builds it with **`gloop index --registry <atlas.toml>`** and
consumes it through the `AtlasIndex` adapter (`rank_repos` for the ticket→repo match, `retrieve` for
localization). The knowledgeLoop `repo_atlas` MCP `serve`/`find_related` server and the
`UserPromptSubmit` adoption-nudge hook are **provenance / not exposed as `gloop` subcommands**.

### Retrieval — FTS5 keyword ⊕ vector, fused with RRF

Each query runs an FTS5 keyword search and a vector-cosine search over a (kind-filtered) unit pool,
then fuses the two ranked lists with **Reciprocal Rank Fusion** (`rrf_fuse`, `k0 = 60`:
`score += 1 / (k0 + rank + 1)`).

### Registry schema (`atlas.toml`)

`load_registry` reads a TOML with a `[[repo]]` array; `name`, `repo_path`, `wiki_dir` are **required**
per entry, `entity_map` is **optional** (carried for future use — the current index/retrieve path uses
the wiki docs + a fresh CBM enumeration, not the entity_map):

```toml
[[repo]]
name = "android-gpuimage-plus"
repo_path = "/mnt/x/code/corpora/android-gpuimage-plus"
wiki_dir  = "/abs/scratch/android-gpuimage-plus/docs"
entity_map = "/abs/scratch/android-gpuimage-plus/entity_map.json"  # optional
```

Per-repo freshness (`repo_freshness`) is `unindexed` / `fresh` / `stale` (indexed head vs current
HEAD). Re-indexing is per-repo idempotent. The `atlas.db` is large (**~0.8–1.4 GB for 3 mid-size
repos**) and machine-specific — git-ignored. The three built corpora at pinned SHAs
(android-gpuimage-plus, libxcam, ndk-samples) live in `/mnt/x/code/corpora/corpus.toml` (absolute path).

### The bge-m3 reuse invariant

The embedder is an **engine-internal Protocol** (`engines/atlas/embed.py`) — **not** a core port. The
embed model is pinned **`bge-m3`** (`KLOOP_EMBED_MODEL` default) and **the query-time embedder MUST
equal the index-time embedder**, or cosine ranking is silently corrupted (the vectors table stores
**raw** embeddings). Changing it forces a full re-index. Index-side env: `KLOOP_ATLAS_DB`,
`KLOOP_REGISTRY`, `KLOOP_EMBED_BASE_URL`, `KLOOP_EMBED_API_KEY`, `KLOOP_EMBED_MODEL` (see
[settings.py](../groundloop/config/settings.py)).

### Gotchas that actually bite

- **Run produce from the target repo's cwd** — the repo is `cwd`-derived, not a flag.
- **Use an absolute `--out` / `--registry` path** — a relative path can write inside a read-only
  corpus tree.
- **Keep `CBM_CACHE_DIR` (and the atlas DB) on a local FS**, off 9p/v9fs mounts — CBM writes
  SQLite/WAL. On v9fs, `git status` shows every file modified (filemode bits only); use
  `git -c core.fileMode=false status` to see real content changes.

---

## See also

- [architecture.md](architecture.md) — hexagonal ports & adapters, `run_ticket`, migration strategy.
- [build-setup.md](build-setup.md) — the GL-M1 `gloop index` build (consume + build an atlas.db).
- [build-setup.md](build-setup.md) — Type-2 live-eval runbook (real models + a real atlas.db).
- [evaluation.md](evaluation.md) — Type-1 hermetic + Type-2 surfaces.
- [charter.md](charter.md) · [roadmap.md](roadmap.md) · [environments.md](environments.md) · [../CLAUDE.md](../CLAUDE.md) — mission, forward plan, dev-box vs production, orientation.
- Source (reference, do not copy): `../../knowledgeLoop/docs/SETUP.md`, `.../applying-to-a-new-repo.md`,
  `.../close-loop-workflow.md`, `.../CODEWIKI.md`, `.../DEVELOPMENT.md`, `.../MVP.md`,
  `.../repo_memory-deploy.md`, `.../findings-and-practices.md`.
