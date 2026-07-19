# GroundLoop — Module Map (working map)

> **A personal working map, organized as a walk through the real JIRA-defect loop.** For each stage of
> `run_ticket`, this lists the modules that do the work, **where** they're wired, **how** they're used, and
> **how mature** they are. It is a **synthesis, NOT SSOT** — like `stages-concept.md` / `stakeholder-overview.md`.
> Canonical detail lives in [`architecture.md`](architecture.md) (ports & control plane),
> [`data-flow.md`](data-flow.md) (build/runtime planes), and [`capabilities.md`](capabilities.md) (the
> Core/Candidate governance registry). When those disagree with this file, they win.
>
> **Grounded** against the tree on 2026-07-19 (a read-only per-subsystem survey). Line numbers are anchors and
> will drift; the class names + file paths are the stable part.

## How to read — maturity legend

Every component carries one tag:

| tag | meaning |
|---|---|
| **[production]** | proven on real (GEI) data or exercised on the live production path |
| **Candidate** | reachable + opt-in, **unproven** (no `[production]` effectiveness read) — `reachable ≠ default` |
| **MOCK** | hermetic stub / dev fixture — never a real integration |
| **build-time** | off the JIRA loop; produces an artifact the runtime later reads |
| **labs** | eval / benchmark only; the loop never imports it (see §5) |

**Reality check (the honesty overlay).** The loop is *not* a delivered closed loop. **Match** is
`[production]`-validated; **localize**'s *floor* (`AtlasIndex.retrieve`) is `[production]`-validated, but its
run **default** (`atlas_rerank`) is Provisional-Core — safety-proven (degrades to the
`[production]` floor without judge creds — byte-identical with no `KLOOP_REGISTRY` doc-bridge, a rank-1-preserving
recall-superset with it), effectiveness still an open `[proxy]` A/B; **fix** is a real engine
but **unproven** (safety default = abstain);
**submit/bind are MOCK**, and `run_ticket` returns **`bound=True` as a hardcoded literal** (`core/workflow.py:42`)
— it is *not* derived from the `bind()` call (whose return is discarded at L39). A doc "structured by the
end-to-end workflow" must not read as if steps ⑦–⑧ are real. They aren't yet.

---

## §1 · Component-relationship diagram

`run_ticket` is the frozen control plane. It's injected with **6 collaborators** (one per port, *except* `Model`)
at the composition root `cli/__init__.py`. The `Model` port is **not** a `run_ticket` argument — it's injected
*into* the adapters that call an LLM (the fix engine, the localize/match judges).

```
   JIRA defect ticket ─┐
   (+ failure LOGS)    │
                       ▼
        ┌──────────────────────────────────────────────────────────────────┐
        │            core/workflow.py :: run_ticket()      [FROZEN]         │
        │   intake → extract → match → materialize → localize → fix →       │ ──► RunRecord
        │            submit → bind                                          │     bound=True  ◄─ HARDCODED
        └───┬────────┬─────────┬──────────┬──────────┬─────────┬───────────┘        (L42, not from bind())
   inject   │        │         │          │          │         │
   (comp.   ▼        ▼         ▼          ▼          ▼         ▼
    root)  IssueSource SignalExtractor CodeIndex  RepoEstate FixEngine ChangeSink
            │        │         │          │          │         │
         MockJira Android   AtlasIndex  MockEstate Planning  MockGerrit
         [MOCK]   Signal    [prod]      / Checkout FixEngine [MOCK]
                  Extractor  ▲          Estate     [Candidate] (submit+bind
                  [prod]     │          [MOCK/Cand] │           both mock)
                            (match arm  │           │
                   ┌─────────wraps it;  │           │
                   │   labs arms opt-in)│           │
                   │                    │     ┌─────┴──────────────────────┐
             ┌─────┴───────────────┐    │     │ Model port (NOT a run_ticket arg): │
             │  atlas.db           │    │     │ GatewayModel [Cand,live] / CannedModel [MOCK] │
             │  FTS5 + bge-m3      │    │     │ injected into FixEngine + judges (rerank/atlas_judge) │
             │  ◄─ built off-loop  │    │     └────────────────────────────┘
             │  (build/+codewiki/  │◄───┘ CodeIndex reads atlas.db for BOTH
             │   +engines/)        │       rank_repos (match) and retrieve (localize)
             └─────────────────────┘
```

The **7th port, `Model`**, is declared in `core/ports.py:44` (`complete(prompt) -> str`) but the control plane
never touches it — LLM use is an *adapter* concern. That's why the loop stays deterministic even though several
adapters call a model.

---

## §2 · The workflow spine — stage by stage

Signature: `run_ticket(ticket_id, *, issues, extractor, estate, index, fixer, changes) -> RunRecord`
(`core/workflow.py:19`). Eight named stages, nine concrete calls (submit + bind are distinct). Each stage below:
**port → concrete call → the adapter(s) behind it → where wired → maturity.**

### ① intake — `IssueSource.fetch` · [MOCK]
- **Call:** `issues.fetch(ticket_id) -> Ticket` (`workflow.py:24`).
- **Adapter:** `MockJira` (`adapters/mock/jira.py`) — FS-backed: reads `dataset/<id>/`, writes comment/transition
  back to a per-case `ledger.jsonl`. **[MOCK]** — the live JIRA `IssueSource` is a still-open Core gap.
- **Type:** `Ticket` (`core/types.py:13`) — `id`, `summary`, `description`, `component` *(comment: MUST NOT be
  the owning repo — oracle-blindness)*, `comments`, `logs: tuple[LogAttachment]`, `status`.

### ② extract — `SignalExtractor.extract` · [production]
- **Call:** `extractor.extract(ticket.logs, ticket) -> Signals` (`workflow.py:26`).
- **Adapter (product):** `AndroidSignalExtractor` (`domains/android_ivi/signal_extractor.py`) — regex-parses
  logcat / Java stack frames / native backtraces into repo-discriminative signals. Reads `log.content` + **only
  `ticket.description`** (not `summary`/`component`). Emits `Signals` (`core/types.py:24`): `packages`, `classes`,
  `methods`, `symbols` (native), `libraries` (`.so`), `errors` — each order-preserving-deduped. **[production]**
- **Decorator:** `RecordingExtractor` (`adapters/extractor_recording.py`) wraps the inner extractor in batch mode,
  caching `last_signals` so the run-record (and the opt-in KB) can read them. **[production]**
- **Labs alternatives** (paired with labs match arms): `FaultSignalExtractor`, `ComponentExtractor`,
  `FunctionalTextExtractor`, `DispatchExtractor` (all under `domains/android_ivi/`, lazy-imported). **Candidate.**

### ③ match — `CodeIndex.rank_repos` · [production] *(the crown result)*
- **Call:** `index.rank_repos(signals, estate.catalog()) -> [RepoScore]`; `chosen = ranked[0].repo`
  (`workflow.py:28,30`). **Top-1 = predicted owning repo.**
- **Core arm:** `AtlasIndex` (`adapters/index/atlas.py`) — `rank_repos` = FTS5 unit-membership over `atlas.db`
  grouped by owning repo (the `flood` baseline). **[production]** floor.
- **Default arm (wired):** `ComponentPriorIndex` (`adapters/index/labs/component_prior.py`) — RRF-fuses a mined
  **JIRA-component→repo affinity prior** onto `AtlasIndex` (recall@1 **0.10 → 0.50** on GEI). Selected
  `--match-arm component` (the Core-profile default, `cli/__init__.py:1382`); **no affinity artifact ⇒ warns +
  degrades to `flood`.** `[production]` GEI read; formally **Candidate** in governance (affinity data is prod-only).
- **Opt-in labs arms** (`adapters/index/labs/`, all **Candidate**; backed by the `atlas.db` store family but wired
  differently — `FaultRoutingIndex`/`ComponentPriorIndex` wrap an `AtlasIndex` instance, `SemanticAtlasIndex` reads
  `atlas.db` via `Store` directly, the functional arms sit on a separate text-profile db):
  `FaultRoutingIndex` (`fault_routing.py`, `--match-arm routing`, prod routing table ⊕ fault-scoped FTS);
  `SemanticAtlasIndex` (`atlas_semantic.py`, `semantic`, bge-m3 cosine — needs embedder);
  `FunctionalTextIndex` (`functional_text.py`, `functional`, prose↔repo-profile cosine);
  `DispatchIndex` (`functional_text.py`, `dispatch`, per-ticket routes prose→functional / crash→routing);
  `LLMJudgeIndex` (`atlas_judge.py`, the `+judge` match-rerank — **eval-only**, selected by `gloop eval --judge`,
  not a `--match-arm`).
- **Type:** `RepoScore` (`core/types.py:47`) — `repo`, `score`, `evidence`.

### ④ materialize — `RepoEstate.materialize` · [MOCK] / Candidate
- **Call:** `estate.materialize(chosen) -> WorkTree` (`workflow.py:31`). (`catalog()` also feeds ③.)
- **Adapters (all in `adapters/estate.py`):**
  - `MockEstate` — catalog from `catalog.json`, throwaway worktree dir, **no snapshot**. Default. **[MOCK]**
  - `CheckoutEstate` (subclass) — checks out `<fixtures_root>/<repo>` into a fresh git-inited tree; wired when
    `gloop run --repos` is given. **Candidate.**
  - `RecordingEstate` (decorator) — records `MaterializeOutcome(present, n_files)` per materialize for the offline
    grader (the "empty-worktree → honest abstain" signal). **[production]**
  - `GitFixtureEstate` — hermetic `@base` snapshot with single-commit `git init` (anti-leak); no snapshot ⇒ empty
    dir ⇒ honest abstain. **[MOCK]**
- **Type:** `WorkTree` (`core/types.py:54`) — `repo`, `path`.

### ⑤ localize — `CodeIndex.retrieve` · Provisional-Core default (`atlas_rerank`) over a [production] FTS5 floor (+ Candidate rerankers)
- **Call:** `index.retrieve(chosen, ticket.summary) -> [str]` (file paths) (`workflow.py:33`).
- **Core floor:** `AtlasIndex.retrieve` = FTS5 over `kind='symbol'` units within the chosen repo — plain keyword
  search. This is the **`[production]` 7/10 file@5** floor (`--localize atlas`) — no longer the run default (see
  below), but the explicit opt-out / fail-safe degrade target every reranker below falls back to. **[production]**
- **Run default (Provisional-Core, since 2026-07-19):** `--localize atlas_rerank` — `RerankLocalizeIndex`
  (`adapters/index/labs/rerank_localize.py`) composed via the `pool_index` seam over a **plain `AtlasIndex`**
  pool (no cascade, no embedder anywhere in the arm) and reordered by the rerank LLM file-judge. Fail-safe: with
  no gateway judge creds it returns the FTS5 pool order **byte-identical to `--localize atlas`** (with no
  `KLOOP_REGISTRY` doc-bridge; a rank-1-preserving recall-superset with it), so a
  credential-less run can't regress and — unlike `--localize rerank` — it never fail-closes on a missing
  embedder. Honest gap: *with* creds the judge can rank the true file below where raw FTS5 had it (a `file@1`
  regression vs `atlas`), unmeasured for this arm; the `[proxy]` file@1 A/B (`atlas` vs `atlas_rerank` vs
  `cascade_judge`) is an open resolver, not done. Admitted on the same fail-safe argument as Bug Plan Mode —
  see `docs/capabilities.md` §"Provisional-Core".
- **Opt-in rerankers** (`adapters/index/labs/`, wrapped in `SplitIndex` so localize is chosen independently of the
  match arm — all **Candidate**):
  - `SignalQueryIndex` (`signal_query.py`, `--localize tokens`) — rewrites the query to extracted CODE tokens.
  - `RerankLocalizeIndex` (`rerank_localize.py`, `--localize rerank`) — builds a candidate **pool** (hybrid
    `find_related_units`, or an injected `pool_index`), enriches with source + CodeWiki + live CBM, **LLM-reranks**
    grounded to real pool files. Exposes the **`pool_index` seam** + a `FileJudge` (live `GatewayFileJudge` /
    `StubFileJudge` MOCK). **Fails fast without an embedder.**
  - `CascadeLocalizeIndex` (`cascade_localize.py`, `--localize cascade`) — recall-first RRF union of the prose FTS
    floor + crash code-tokens + literal anchors + optional bge-m3 semantic tier.
  - **`cascade_judge`** (composed, `cli/__init__.py:1461`) — the CascadeLocalizeIndex passed as the `pool_index`
    to a RerankLocalizeIndex = cascade recall pool reordered by the LLM judge. **Best localize file@1 to date**
    (`[proxy]` 0.245/0.469 file@1/@5), leading Candidate — a richer pool than `atlas_rerank`'s, but needs an
    embedder, which is why `atlas_rerank` (zero-embedder + the degrade-to-`atlas` floor) is the run default
    instead of this higher-ceiling arm.

### ⑥ fix — `FixEngine.propose` · Candidate (unproven; abstains, never fabricates)
- **Call:** `fixer.propose(wt, ticket, locations) -> Patch` (`workflow.py:35`).
- **Adapters (`adapters/fix/`):**
  - `PlanningFixEngine` (`planning.py`, `--fixer plan`, **the default**) — two-phase PLAN → oracle-blind in-world
    gate → re-plan → **abstain** → ACT, with an anti-leak diff-scope check. Provisional-Core on a *safety*
    argument (`fabrication_rate = 0`); **effectiveness production-gated.** **Candidate.**
  - `ModelPatchEngine` (`model_patch.py`, `--fixer model`) — single-shot propose-patch over `@base` snippets.
    **Candidate.**
  - `CannedFixEngine` (`canned.py`, `--fixer canned`) — deterministic diff stub; **dev-gated**. **[MOCK]**
  - `KnowledgeInjectingFixEngine` (`kb/inject.py`, decorator) — opt-in `--kb-store`: injects validated KB
    playbooks as a fix-prompt preamble (reads `last_signals` from the RecordingExtractor); no-op fail-safe.
    **Candidate.**
- **Model dependency:** `model`/`plan`/`kb` all use `GatewayModel` (`adapters/model/gateway.py`, live LiteLLM,
  cost-tracked). **Fail-closed**: `--fixer model|plan` with no gateway key or an empty `--repos` **refuses to run**
  (returns 2) rather than fabricate.
- **Type:** `Patch` (`core/types.py:60`) — `diff`, `files`.

### ⑦ submit — `ChangeSink.submit` · [MOCK]
- **Call:** `changes.submit(chosen, patch, ticket) -> Change` (`workflow.py:37`).
- **Adapter:** `MockGerrit` (`adapters/mock/gerrit.py`) — synthesizes and returns a deterministic Change-Id (the
  ledger write happens in ⑧ bind, not here). **[MOCK]** — live Gerrit `ChangeSink` is a still-open Core gap.
- **Type:** `Change` (`core/types.py:66`) — `change_id`, `commit_subject`, `ticket_id`, `patch`.

### ⑧ bind — `ChangeSink.bind` · [MOCK] (`bound=True` hardcoded)
- **Call:** `changes.bind(change, ticket) -> None` (`workflow.py:39`) — **return discarded.**
- **Adapter:** `MockGerrit` — appends the change to the changes ledger, then binds by posting a JIRA comment +
  "Resolved" transition via the injected `IssueSource`. **[MOCK]**
- **The literal:** `RunRecord(..., bound=True, ...)` (`workflow.py:42`) — the traceable JIRA↔commit chain is
  **asserted, not measured**. `RunRecord` (defined in `workflow.py:8`, the only mutable dataclass): `ticket_id`,
  `ranked`, `chosen`, `locations`, `patch`, `change`, `bound`, `events`.

---

## §3 · Cross-cutting components

### The `Model` port — `adapters/model/`
- `GatewayModel` (`gateway.py`) — live `complete()` over the LiteLLM gateway (deepseek-chat, temp 0); tracks
  cumulative `cost_usd`/tokens/calls; swallows exceptions to `""` (never crashes an eval). **Candidate (live/gated).**
- `CannedModel` (`adapters/mock/model.py`) — scripted substring-keyed text. **[MOCK].**
- `cost.py` (`cost_of`/`PRICES`) — token→USD pricing helper for the live arms. **Candidate.**
- Injected into: the fix engines (⑥) and the localize/match judges (⑤/③). Not a `run_ticket` argument.

### `config/settings.py` — the single env surface (`Settings.load(env)`)
Reads only `KLOOP_*`: `KLOOP_DATA_DIR`, `KLOOP_DOMAIN` (`android_ivi`), `KLOOP_MODEL`, `KLOOP_ATLAS_DB`,
`KLOOP_REGISTRY`, `KLOOP_EMBED_{MODEL,BASE_URL,API_KEY}` (model pinned `bge-m3`), `KLOOP_PRODUCE_{BASE_URL,
API_KEY,MAIN_MODEL}` (key falls back to `OPENAI_API_KEY`; model default `deepseek-chat`), `KLOOP_CBM_INDEX_TIMEOUT`
(1800), `KLOOP_EMBED_{BATCH,MAX_CHARS}`, `KLOOP_INDEX_CAMELCASE` (opt-in), `KLOOP_KB_{STORE,TOPK}` (topk 2).
There is **no `dev`/`labs` field** in `Settings` — those gates live in the CLI + the import contract (§5).

### `run/` — the self-scoring pipeline (oracle-blind) · [production]
The batch/record/report half of `gloop run` — **product-runtime, oracle-free** (grading is a separate offline pass
in `grade/`, §4):
- `batch.py` `run_dataset()` — oracle-blind batch driver: runs frozen `run_ticket` per case, snapshots per-case
  cost, checks `patch_applies`, optional opt-in KB `mint` hook, persists a run-record. **[production]** (mint = Candidate).
- `record.py` `RunRecordIO` / `RunDoc` / `MaterializeOutcome` — oracle-blind RunRecord persistence (`ORACLE_KEYS`
  never written). **[production].**
- `report.py` `render_run_markdown()` — renders a scorecard dict to markdown (render-only). **[production].**
- `manifest.py` `write_manifest()` — provenance `manifest.json` (atlas identity, arms, model pins, affinity sha1,
  `change_sink=mock`). **[production].**
- `dataset.py` `CaseRef` / `load_cases()` / `case_catalog()` — oracle-free case loader (never reads `_oracle/`);
  the product-surface half split out of `eval/dataset.py`. **[production].**

### Composition root — `cli/__init__.py` (`gloop run`)
Wires every port from flags. **Core/Provisional-Core-aligned defaults:** match `component` · localize
`atlas_rerank` (Provisional-Core, since 2026-07-19 — `--localize atlas` is the opt-out) · fixer `plan`
(`_resolve_arms`, ~L1091). Key flags: `--match-arm {flood,routing,component,semantic,functional,dispatch}`,
`--localize {atlas,tokens,rerank,cascade,cascade_judge,atlas_rerank}`, `--fixer {canned,model,plan}`, `--repos`, `--index`/
`--index-db` (required, mutually-exclusive), `--profile {core,labs}`, `--affinity`, `--functional-profile`,
`--kb-store`/`--kb-topk`, hidden `--dev`. **Fail-closed** (returns 2, never fabricates): real fixer without
gateway creds or without repo snapshots; `semantic`/`functional`/`dispatch`/`rerank` without an embedder.
**`KLOOP_DEV` dev-gate** rejects the hermetic doubles (`--index` M0 stub, `--fixer canned`, `--case`) in
production. **`KLOOP_LABS` / `--profile labs`** only flips the *default* arm resolution (match → routing);
explicit arms always override. Labs arms load via **function-local lazy imports** — the sanctioned opt-in seam (§5).

---

## §4 · Off-loop / supporting modules

These never sit on the runtime JIRA path — they **build** the index the loop reads, or **measure** the loop.

### Build→runtime plane

```
BUILD-TIME  (off the JIRA loop)                          RUNTIME  (the loop)
──────────────────────────────                          ───────────────────
build/clone_fleet ─► repo checkouts (pinned SHAs, corpus.toml)
      │
      ├─ codewiki/ (gloop produce) ──► CodeWiki doc units ─┐
      │    CLIDocumentationGenerator                        │
      ├─ engines/lore CBM ────────────► symbol graph ───────┤   gloop index      atlas.db        AtlasIndex.rank_repos  ─► match ③
      │    (index_repository)                                ├──►(engines/atlas  ─►(FTS5 +   ─►
      └─ engines/atlas embed (bge-m3) ─► vectors ────────────┘   index_repo)       bge-m3)      AtlasIndex.retrieve    ─► localize ⑤

   build/atlas_build = clone → produce → index → doctor        (gloop build-atlas)
   build-textprofile ─► profile atlas.db ──► FunctionalTextIndex / DispatchIndex (labs match)
```

### `build/` — fleet orchestration · build-time
`atlas_build.py` `build_atlas()` (clone→produce→index→doctor; `symbol_only` skips produce; `gloop build-atlas`) ·
`produce_fleet.py` (bounded-parallel `gloop produce` per repo) · `clone_fleet.py` (shallow clone at pinned SHAs) ·
`corpus.py` (`corpus.toml` parse) · `wiki_stub.py` (minimal wiki so a symbol-only atlas loads) · `lite_index.py`
(fast regex symbol-only test atlas, no CBM/produce).

### `engines/atlas/` — the atlas store + index builder
`store.py` `Store`/`Unit`/`_fts_query` — the shared **`atlas.db`** (FTS5 `units_fts` + bge-m3 `vectors`); build
writes (`reindex_repo`), runtime reads (`keyword_search`/`vector_search`). **Do not alter the schema — no version
guard.** `index.py` `index_repo()`/`build_units()` — combines `load_wiki` docs + CBM symbols into units + embeds
(`gloop index`). `embed.py` `GatewayEmbedder` (bge-m3; `StubEmbedder` MOCK). `retrieve.py` `find_related_units`/
`rrf_fuse` — runtime keyword+vector RRF (feeds the rerank pool; **Candidate**). `registry.py` — the build registry TOML.

### `engines/lore/` — CBM code-graph + wiki + bridge · build-time
`graph/client.py` `CBMClient` (stdio-MCP to `codebase-memory-mcp==0.8.1`) · `graph/forward.py` (CBM 0.8.1 tool
wrappers) · `graph/nodes.py` `enumerate_all_nodes` (symbol source for index) · `wiki/loader.py` `load_wiki`/
`WikiData` (reads a CodeWiki dir — the produce↔atlas contract) · `bridge/build.py` `build_entity_map` (doc→source
`entity_map.json`; `gloop bridge`; CBM join is gated-live) · `deploy.py` (CBM launch spec).

### `codewiki/` — the CodeWiki doc-unit generator · build-time *(top-level, out of the product package — §5)*
`cli/adapters/doc_generator.py` `CLIDocumentationGenerator` — 5-stage pipeline (dependency graph → LLM module
clustering → per-module doc-gen → writes `module_tree.json` + `*.md` + `metadata.json`). `gloop produce`
(requires the `produce` extra; live-confirmed 2026-07-19). Output feeds `gloop index` (doc units) + `gloop bridge`.

### The Type-2 labs / eval stack · labs (see §5 — the loop cannot import these)
| package | measures / feeds | key entry | CLI |
|---|---|---|---|
| `eval/` | Stage-1 **match** (oracle-blind, recall@k, abstain) → scorecard | `EvalRunner`, `grade_all`, `EvalOracle` | `gloop eval`, `combine-oracle`, `label-bugkind` |
| `fixeval/` | whole loop **match→localize→fix** (file_recall/patch_applies/resolved_rate/fabrication_rate) | `FixEvalRunner`, `grade_fix_all`, `compare`/`accept_grounded` | `gloop fixeval`, `compare` |
| `funceval/` | **match** on no-crash functional tickets (+ dispatch, LOO affinity) | `run_funceval`, `build_functional_arms` | `gloop funceval`, `mine-affinity` |
| `faulteval/` | **attribution** + separate **fault-localization** over faultlogs | `run_faulteval`, `grade_fault_localization` | `gloop faulteval` |
| `mine/` | dataset: GH issue→merged-PR positives + honest-refusal negatives (leak-reject) | `mine()`, `harvest_repo`, `scrub` | `gloop mine` |
| `synth/` | synthetic match/fault/functional datasets (no repo-name leak) | `synth/logs.py`, `faultlog.py`, `functional.py` | `gloop synth --mode {failurelog,faultlog,functional}` |
| `kb/` + `skills/` | **fix**-prompt knowledge injection (distilled) | `KnowledgePlaybook`, `PlaybookRegistry`, `mint`/`attribute`, `MockSkillRegistry` | `gloop kb-seed`, `kb-ab`, `kb-attribute` |
| `grade/` | **offline** per-stage scorecard over a `gloop run --out` dir (sole oracle read) | `grade_run`, `compare_cards`, `promotion_notes` | `gloop grade-run` (`--compare`) |

Note: `kb/` injects distilled **Knowledge** (`--knowledge {none,candidate,validated}`); `skills/` is the raw
undistilled **Skill** feedstock baseline (`--skills {none,mock,kb,placebo}`). KB is **Candidate/unproven**.
`grade/grader.py`'s `grade()` (over `RunRecord`/`Oracle`/`Scores`) is a **test-only fixture**, not wired into
`gloop grade-run`.

---

## §5 · The Core/Labs boundary (structural, CI-enforced)

The product runtime **cannot eagerly import any labs package** — enforced by
`tests/architecture/test_import_boundary.py`, not just documented.

- **Product scope** (`PRODUCT_DIRS`): `core`, `config`, `adapters`, `domains`, `run`, `fix`, `engines/atlas`,
  `engines/lore` — **plus** `cli/__init__.py`, **minus** `adapters/index/labs/` (a labs subtree physically under a
  product dir, `EXCLUDE`d from the scan).
- **Forbidden (labs) prefixes:** `groundloop.{eval, fixeval, funceval, faulteval, synth, mine, kb, skills, grade,
  build}` + `groundloop.adapters.index.labs` + `codewiki`.
- **Rule:** no product-scope file may import a forbidden prefix at module level (or inside a top-level `if`/`try`/
  `with` — caught by the AST `_eager_imports` walk). **Function-local imports are the sanctioned opt-in seam** —
  exactly how the composition root reaches the labs index arms, the KB, `codewiki`, and the grade tooling on
  demand. A sanity-mutation test proves the guard bites.

This is why the labs arms above are *reachable* (opt-in flags) but never a silent product dependency, and why
`codewiki/` (§4) lives as a top-level package **outside** `groundloop/`.

---

## Cross-links
- Ports & the deterministic control plane → [`architecture.md`](architecture.md)
- Build vs runtime data planes (the two ASCII planes) → [`data-flow.md`](data-flow.md)
- Per-capability Core/Candidate/Fixture governance + evidence → [`capabilities.md`](capabilities.md)
- What's proven vs mocked, with `[proxy]`/`[production]` numbers → [`results-log.md`](results-log.md), [`STATUS.md`](STATUS.md)
