# GroundLoop — Data Flow & Module Map

How the pieces relate: which modules **produce** the index/assets (the *build* plane), and how the
deterministic loop's stages **consume** them (the *runtime* plane). Centered on the six things that matter
most — **`atlas.db`, CBM, CodeWiki, Match, Localize, Fix** — set in the full 8-stage pipeline.

The one idea to hold onto: **CBM and CodeWiki each play two roles at two different times** — baked into
`atlas.db` at *build* time, and consumed as live grounded context at *query* time — and `atlas.db` is the
shared hub every read-stage sits on. See §3 for that table; the design *rationale* is in
`docs/superpowers/specs/2026-07-16-localize-fix-design-logic.md`.

Companion docs: `docs/architecture.md` (ports/adapters + control plane), `docs/stages-concept.md` (the
concept behind the stages), `docs/engines.md` (produce/CBM/atlas engine ops), `docs/capabilities.md`
(which arms are Core vs Candidate), `docs/results-log.md` (efficacy).

---

## 1. Plane 1 · BUILD (offline) — making the index + assets

`gloop build-atlas` = **produce** (CodeWiki) + **index** (atlas) + **bridge** (entity_map). Runs off a
`bge-m3`-pinned embedder, one repo at a time, off ext4 (see `docs/build-setup.md`).

```
PLANE 1 · BUILD (offline)                          [ gloop build-atlas = produce + index + bridge ]

  fleet source repos ─┬─▶ CBM  index_repository ─────▶ code graph ─┐
  (130+ AAOS / OSS)   │      (codebase-memory-mcp)                 │ node
                      │                                            │ enumeration
                      │                                            ▼
                      │                                       symbol units ─┐
                      │                                                      │  gloop index
                      ├─▶ CodeWiki  gloop produce ─▶ wiki *.md ─▶ doc units ─┤  (bge-m3 embed)
                      │      (engines/produce)         │                     ▼
                      │                                │              ┌──────────────┐
                      │                                │              │   atlas.db   │
                      │                                │              │  FTS5+vector │
                      │                                │              │ symbol + doc │
                      │                                │              └──────────────┘
                      │       gloop bridge             ▼
                      └───────────────────────▶ entity_map.json   (module ─▶ source files)
                              module_tree.json  [+ optional CBM line-span join]
```

- **CBM → symbol units.** `CBM.index_repository` builds a code graph; `gloop index` flattens its **node
  list** into `symbol` units (one per code symbol, carrying `repo`/`file`/`qualified_name`). *The graph
  edges are not stored* — they're recomputed live at query time (Plane 2). Source: `engines/lore/graph`,
  `engines/atlas/index.py`.
- **CodeWiki → doc units + `module_tree`.** `gloop produce` writes per-module LLM docs (`*.md`) +
  `module_tree.json`. `gloop index` turns the wiki pages into `doc` units (a doc unit's `file` is the *wiki
  basename*, with its module in `meta`). Source: `engines/produce`, `engines/atlas/chunk.py::doc_units`.
- **`gloop index` → `atlas.db`.** Symbol + doc units are `bge-m3`-embedded and written to one SQLite index
  (FTS5 keyword + vector). Schema is frozen; doc units are *additive*. Source: `engines/atlas/store.py`.
- **`gloop bridge` → `entity_map.json`.** Walks the `module_tree` (optionally CBM-joined for exact line
  spans) into a **module → source-files** map — the bridge that lets a CodeWiki `doc` hit become a real
  source file (used only at runtime, Plane 2). Source: `engines/lore/bridge`, `gloop bridge`.

**Net build artifacts:** one shared `atlas.db` (symbol + doc units + vectors) **+** a per-repo
`entity_map.json` side-car. The CBM graph and CodeWiki `.md` pages remain on disk for live use.

---

## 2. Plane 2 · RUNTIME — the 8-stage loop consuming them

The deterministic control plane (`core/workflow.py`) runs **oracle-blind**; grading is a separate offline
pass. Each stage is one of the 7 core ports.

```
PLANE 2 · RUNTIME (core/workflow.py — deterministic, oracle-blind)

  JIRA ticket + failure logs
        │  intake         · IssueSource.fetch
        ▼
  extract              · SignalExtractor.extract(logs, ticket) ─▶ signals (classes·methods·.so·pkg)
        │
        ▼
  MATCH                · CodeIndex.rank_repos(signals, catalog)
    reads ▶ atlas.db  (symbol + doc units, FTS5 — no kinds filter)     ─▶ predicted owning repo
        │
        ▼
  materialize          · RepoEstate.materialize(repo) ─▶ worktree
    (fix-eval) ▶ @base = fix^  via base_checkout
        │
        ▼
  LOCALIZE             · CodeIndex.retrieve(repo, query)
    floor  ▶ atlas.db (symbol units only, kinds=["symbol"])            ─▶ ranked files
    rerank ▶ atlas.db (symbol ∪ doc pool)                              ┐
           ▶ entity_map       (doc hit ─▶ source file)                 │ grounded
           ▶ CodeWiki summary (per-candidate context)                  │ LLM judge
           ▶ live CBM         (call-graph context)                     ┘ reorders the pool
        │
        ▼
  FIX                  · FixEngine.propose(worktree, ticket, locations)
    over ▶ @base source ;  plan ─▶ anti-leak gate ─▶ abstain ─▶ patch
    fix-context ▶ CodeWiki summaries + live CBM  (FixContextProvider)  ─▶ patch (or abstain)
        │
        ▼
  submit · ChangeSink.submit ─▶ change/PR        bind · ChangeSink.bind ─▶ JIRA ↔ commit chain
        │
        ▼
  ┈┈┈ (offline) grade · reads the hidden oracle ─▶ scorecard   [never enters the loop] ┈┈┈
```

**Which stage reads which asset:**

- **Match** queries `atlas.db` over the signal tokens with *no* `kinds` filter, so **CodeWiki doc units
  count as match evidence** alongside symbol units. Output: a `RepoScore` ranking; top-1 = predicted owning
  repo. (Core default arm = `component`, an affinity re-rank over this score; other arms are Candidates.)
- **Localize** queries `atlas.db` on the *same* repo. Two shapes:
  - *floor* (`--localize atlas`, Core): `retrieve` over **symbol units only** — pure FTS5.
  - *rerank* (`--localize rerank`, **Candidate**): a hybrid symbol∪doc pool → doc hits rewritten to source
    via the **`entity_map`** → a grounded LLM judge reorders, fed per-candidate **CodeWiki** summaries +
    **live CBM** call-graph. `±CodeWiki` = `KLOOP_REGISTRY` present/absent; `±CBM` = `--repos` present/absent.
- **Fix** works over the materialized **`@base` source** (fix-eval checks out `fix^` so patches are
  gradeable). Core = `--fixer plan` (`PlanningFixEngine`: plan→gate→abstain→patch). `--fix-context
  {codewiki,cbm}` (**Candidate**, default OFF) prepends the same CodeWiki summaries + live CBM context to the
  plan/patch prompt.

---

## 3. The dual-role assets (the key relationship)

| Asset | BUILD-time role (Plane 1) | RUNTIME role (Plane 2) |
|---|---|---|
| **`atlas.db`** | *is* the built index (symbol + doc units + `bge-m3` vectors, FTS5) | the substrate **Match** + **Localize** query |
| **CBM** | `index_repository` → nodes → **symbol units** | live call-graph (`CBMLiveGraph`) → context for **Localize** rerank + **Fix** |
| **CodeWiki** | `produce` → **doc units** (+ `module_tree` → `entity_map`) | module summaries → context for **Localize** rerank + **Fix**; doc→source rewrite via `entity_map` |
| **`entity_map`** | built by `gloop bridge` from `module_tree` | doc-unit → source-file bridge (Localize rerank + Fix-context) |

So a single arrow like "CodeWiki → Localize" is really *two* edges: a build edge (`produce` → doc units in
`atlas.db`) and a runtime edge (module summary → the reranker's judge, via the `entity_map`). Same for CBM
(nodes → symbol units at build; call-graph → context at query).

---

## 4. The 8 stages, at a glance

| # | Stage | Core port | Reads | Writes / emits | Notes |
|---|---|---|---|---|---|
| 1 | intake | `IssueSource` | JIRA ticket + logs | `Ticket` | |
| 2 | extract | `SignalExtractor` | ticket + logs | `Signals` | domain pack (`android_ivi`) |
| 3 | **Match** | `CodeIndex.rank_repos` | **`atlas.db`** (symbol+doc) | predicted repo | oracle-blind; top-1 = owner |
| 4 | materialize | `RepoEstate` | repo (+ `fix^` in fix-eval) | worktree | `base_checkout` for gradeability |
| 5 | **Localize** | `CodeIndex.retrieve` | **`atlas.db`** (+ `entity_map`, CodeWiki, **live CBM**) | ranked files | floor=symbol-only; rerank=Candidate |
| 6 | **Fix** | `FixEngine.propose` | `@base` source (+ CodeWiki, **live CBM**) | patch / abstain | `--fixer plan`; `--fix-context` Candidate |
| 7 | submit | `ChangeSink.submit` | patch | change/PR | mock (`MockGerrit`) today |
| 8 | bind | `ChangeSink.bind` | change | JIRA↔commit | mock today |
| — | grade | *offline fn* | run-record **+ hidden oracle** | scorecard | never in the loop |

(The 7th port, `Model`, is the LLM gateway the rerank judge / plan fixer call; it is not a stage.)

---

## 5. Where to look in code

- Control plane / stages: `groundloop/core/workflow.py`, `groundloop/core/ports.py` (**frozen**).
- `atlas.db`: `groundloop/engines/atlas/{index,store,chunk,retrieve,embed}.py`.
- CBM: `groundloop/engines/lore/graph/*` (build) · `groundloop/adapters/graph/cbm_live.py` (live facade).
- CodeWiki: `groundloop/engines/produce/*` · bridge `groundloop/engines/lore/bridge/*`.
- Match: `groundloop/adapters/index/{atlas,split,…}.py`.
- Localize rerank: `groundloop/adapters/index/rerank_localize.py`.
- Fix: `groundloop/adapters/fix/planning.py` · context `groundloop/fix/context.py` · base
  `groundloop/fixeval/base_checkout.py`.
- Build CLI: `gloop {produce,index,bridge,build-atlas,doctor}`; run: `gloop run`; grade: `gloop grade-run`.
