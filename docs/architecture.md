# GroundLoop — Architecture (Ports & Adapters)

GroundLoop is a hexagonal (ports & adapters) system: a **deterministic Python control plane** drives the
full ticket→repo→fix→bind loop through a small set of abstract **ports**, while every concrete behavior —
issue I/O, log parsing, repo ranking, patching, model calls — lives in a swappable **adapter** behind
those ports. The core imports no adapter, no filesystem path, and no domain literal. This is what makes
the mock environment "just an adapter set", makes moving machines a config change, and keeps the loop
honest about the one fact it must never be told: which repo owns the defect.

See also: [charter](charter.md) (mission, FR/NFR, fleet layers, glossary) · [engines](engines.md)
(produce / lore / CBM / atlas operations) · [environments.md](environments.md) (dev↔production split,
oracle-blindness) · [roadmap](roadmap.md) (forward plan, milestones).

> **On the name.** The charter/spec "KnowledgeLoop" **is** GroundLoop (the integrated system).
> `knowledgeLoop` remains only as the read-only migration SOURCE engine repo (held open by live processes);
> the loop-agent "bfl"/bug-fixing-loop is a separate sibling experiment — neither is the GroundLoop CLI.
> Design source (reference, do not copy):
> [`2026-07-04-unified-architecture-ports-and-adapters-design.md`](../../loop-agent/docs/superpowers/specs/2026-07-04-unified-architecture-ports-and-adapters-design.md).

## 1. The two-plane split

**Control plane (deterministic, Python-owned).** `groundloop/core/workflow.py::run_ticket` is a straight-
line orchestrator running the 8 stages of §3. Control flow is ordinary Python — no LLM decides what happens
next; only the *content* at each step (signals, ranking, patch) comes from the cognition/IO plane. This is
the **"grounding over narrative"** principle: trust what reality verifies (real matches over a real index,
deterministic control flow, passing tests), distrust unverifiable LLM prose. `run_ticket` emits an
append-only event trace and is fail-soft.

**Cognition / IO plane (behind ports).** Everything concrete — JIRA, Gerrit, the atlas index, the fix engine,
the model gateway — sits behind a Protocol; the core depends only on the port, and the composition root picks the adapter.

**The loop never sees the oracle.** The owning repo is a **predicted output** of `CodeIndex.rank_repos`,
never an input — `run_ticket` has no oracle parameter to leak through, so the classic owning-repo leak is
structurally impossible. Grading is a **separate offline pass** (`grade/grader.py`) that reads the oracle
*after* the run. The dev↔production split and the full oracle-blindness / offline-grading treatment are in
[environments.md](environments.md).

## 2. The 7 core ports

Exactly seven Protocols live in `groundloop/core/ports.py`. Each is `@runtime_checkable`; most map directly
to a workflow stage (Model is infra used by adapters, not a stage of its own). Mocks are the hermetic test
substrate; real adapters wrap the migrated engines and live services.

| Port | Responsibility | Key method(s) | Mock adapter | Real adapter |
|---|---|---|---|---|
| **IssueSource** | Ticket I/O (incl. logs) + write-back | `fetch(id)->Ticket`; `post_comment(id, body)`; `transition(id, status)` | `MockJira` (`adapters/mock/jira.py`; dataset files + `ledger.jsonl`) | JIRA client (later) |
| **SignalExtractor** *(domain)* | logs + ticket → structured signals | `extract(logs, ticket)->Signals` | — (supplied by the DomainPack) | `AndroidSignalExtractor` (`domains/android_ivi/signal_extractor.py`) — **shipped** (FR-2) |
| **RepoEstate** | fleet catalog + scrubbed checkout | `catalog()->[RepoRef]`; `materialize(repo)->WorkTree` | `MockEstate` (`adapters/estate.py`) | `GitFixtureEstate` + `CheckoutEstate` (`adapters/estate.py`) — **shipped** (via `--repos`) |
| **CodeIndex** | repo-ranking (MATCH) + within-repo retrieval | `rank_repos(signals, catalog)->[RepoScore]`; `retrieve(repo, query)->[str]` | `TokenIndex` (`adapters/index/simple.py`, membership-overlap stub) | `AtlasIndex` (`adapters/index/atlas.py`, real FTS5 over an `atlas.db`) |
| **FixEngine** | localize + propose a patch | `propose(worktree, ticket, locations)->Patch` | `CannedFixEngine` (`adapters/fix/canned.py`, deterministic diff stub) | `ModelPatchEngine` / `PlanningFixEngine` (`adapters/fix/`) — **shipped** (via `gloop fixeval` / `--fixer model`) |
| **ChangeSink** | patch→Change + bind (JIRA↔commit) | `submit(repo, patch, ticket)->Change`; `bind(change, ticket)` | `MockGerrit` (`adapters/mock/gerrit.py`; content-hashed Change-Id + ledger) | Gerrit client (later) |
| **Model** *(infra)* | text completion | `complete(prompt)->str` | `CannedModel` (`adapters/mock/model.py`) | LiteLLM gateway (later) |

`rank_repos(signals, catalog) -> [RepoScore]` is **the** ticket→repo MATCH method; `top-1` is the predicted
owning repo. `RepoScore` carries a `score` and matched-token `evidence`.

**Atlas internals — how `CodeIndex` works.** `rank_repos` (match) and `retrieve` (localize) both run over
the **atlas**: a SQLite store of *code units*, each held in two searchable forms — an **FTS5** full-text row
(keyword) and a **bge-m3** vector (semantic). A unit's `kind` is **symbol** (one per class/method/function,
enumerated by CBM; indexed text = a compact `name label qualified_name file_path` identity + optional
source — the shape a `package.Class.method` / `.so` signal matches) or **doc** (CodeWiki markdown chunks;
the shipped fleet atlas is largely symbol-only). Two arms split the work: **membership** is pure FTS5
keyword — each signal token is matched against `units_fts` and a repo scores by its count of distinct
hitting tokens (no embedding; fully offline, $0 / no GPU); **semantic** cosines the embedded signal tokens
against stored vectors, scoring each repo by its best hit (recovering prose logs where membership
collapses). Membership for signal-rich logs, semantic for prose; the embed model is pinned bge-m3 (§5).

**Not core ports.** Two things that look port-shaped are deliberately not in `core/ports.py`:

- **Embedder** is an **engine-internal Protocol** (`engines/atlas/embed.py`, `embed(texts)->list[list[float]]`),
  not a core port — embeddings are an atlas implementation detail; the core never embeds anything.
- **`grade()`** is an **offline function**, not a port (`grade/grader.py::grade(record, oracle)->Scores`) —
  keeping it a plain function, not a dependency the core holds, is how the oracle stays off the loop's path.

## 3. The `run_ticket` pipeline (8 stages)

`run_ticket` executes these in order, appending each name to the event trace:

1. **intake** — `issues.fetch(ticket_id)` → `Ticket` (summary, description, logs; **no** owning repo).
2. **extract** — `extractor.extract(ticket.logs, ticket)` → `Signals` (packages, classes, methods, native symbols, `.so` names, errors).
3. **match** — `index.rank_repos(signals, estate.catalog())` → ranked `[RepoScore]`; `chosen = ranked[0].repo` (the predicted owning repo).
4. **materialize** — `estate.materialize(chosen)` → a scrubbed `WorkTree`.
5. **localize** — `index.retrieve(chosen, ticket.summary)` → candidate file locations within the repo.
6. **fix** — `fixer.propose(worktree, ticket, locations)` → `Patch`.
7. **submit** — `changes.submit(chosen, patch, ticket)` → `Change` (Change-Id + JIRA key in the subject).
8. **bind** — `changes.bind(change, ticket)` → append the change ledger + transition the ticket (the JIRA↔commit chain).

The result is a `RunRecord` (`ticket_id, ranked, chosen, locations, patch, change, bound, events`) — the input the offline grader scores against the oracle.

## 4. Composition root

Behavior is **swapped at the composition root — `groundloop/cli/__init__.py`** — not inside the core: `cli`
selects each adapter and passes it to `run_ticket` by keyword. Later milestones change the wiring
(`TokenIndex` → `AtlasIndex`, `CannedFixEngine` → agentic, `MockEstate` → corpus-backed, new domains) **without touching `core/`**.

**`groundloop/core/` is FROZEN.** Never edit `core/` to add a feature — swap the adapter at the composition
root instead. The CLI is `gloop {run, grade-run, index, produce, doctor, build-atlas, mine, mine-affinity,
eval, fixeval, funceval, faulteval, synth, combine-oracle, compare, kb-*}` (`index` builds an `atlas.db`;
`produce` generates a CodeWiki; `doctor` checks readiness; `mine` harvests benchmark tickets; `fixeval` /
`grade-run` grade the fix loop). Full list: `CLAUDE.md`.

Config is the single env-reading surface, `groundloop/config/settings.py`, resolved from `KLOOP_*` env vars
(e.g. `KLOOP_DATA_DIR`, `KLOOP_DOMAIN`, `KLOOP_ATLAS_DB`, `KLOOP_EMBED_MODEL`). No other module reads a path
or env var directly, so "move to another machine" is a config change, not a code change.

> **CBM env exception.** CBM *launch overrides* are read as `KNOWLEDGELOOP_CBM_*` / `REPO_MEMORY_CBM_*`
> via the `engines/_envcompat.py` shim (**not** `KLOOP_CBM_*`), and raw CBM knobs like `CBM_CACHE_DIR` are
> intentionally un-prefixed. `KLOOP_CBM_READY` is a separate GroundLoop-level gate flag.

## 5. CBM as a Level-1 hard dependency

Codebase-Memory-MCP (**`codebase-memory-mcp==0.8.1`**) is a **first-class, default, Level-1** GroundLoop
dependency: the pinned package is **installed** on `.venv/bin` PATH and launched as the **installed binary**
(not `uvx`-resolved at runtime), buying reproducibility and offline operation. CBM's code-graph nodes become
the atlas **symbol units** and the `entity_map` doc→file+line bridge targets — load-bearing for **both**
matching and localization. GroundLoop ships a working default launch config; `gloop doctor` resolves and
reports the CBM launch spec (gated by `KLOOP_CBM_READY`). A CBM-less machine falls back to a **pre-built,
shippable `atlas.db`** (build once where CBM runs, ship the artifact). Operational detail: [engines](engines.md).

**Embed pin.** The embed model is pinned to **`bge-m3`** (`KLOOP_EMBED_MODEL` default); the query-time
embedder **must equal** the index-time embedder. The atlas `vectors` table stores RAW embeddings, so a
model/dimension mismatch would corrupt cosine ranking — `SemanticAtlasIndex` guards this at construction
(fails loud, not silent). Changing the model forces a full re-index.

## 6. The DomainPack seam (design-for-later)

Domain specifics live behind a small **DomainPack seam** so the core stays generic. A DomainPack bundles the
fleet/catalog (candidate repos + namespace→repo rules) and the `SignalExtractor` for that domain. **Today
exactly one pack is built — `groundloop/domains/android_ivi/`** (AAOS fleet catalog + `AndroidSignalExtractor`
parsing logcat / Java stack traces / native backtraces). Multi-domain is a **design-for-later seam, not a
feature**: there is deliberately **no plugin / discovery / registry framework**, no second domain, and no
abstraction AAOS doesn't exercise (YAGNI). Adding a domain later = add a package; the core is untouched.

## 7. Migration strategy

The valuable engines are **migrated, not rewritten** — carried into `groundloop/engines/` (`atlas/`, `lore/`,
`produce/`) from the read-only SOURCE at `/mnt/x/code/knowledgeLoop/knowledgeloop/`, each hidden behind an
adapter so the core never depends on their internals. The migration contract is mechanical and verbatim:

- **Copy** the real source file into `groundloop/engines/…`.
- **Rewire** imports `knowledgeloop.*` → `groundloop.engines.*`.
- **Preserve logic verbatim** — the only permitted changes are the import rewire and the `_envcompat` shim.
- Keep the atlas.db **reuse contract** intact — embed pin, stable repo names + pinned SHAs, shared path,
  **unchanged** schema (`engines/atlas/store.py` has no schema-version guard, so any change forces a full re-index); canonical statement in [environments.md](environments.md).

The old repos stay runnable throughout; each step is test-green before the next. Migration also collapses the
duplicated model/cost/extract layers and CBM launch config into the single `config/` surface. Provenance:
[`../../loop-agent/docs/superpowers/plans/2026-07-04-knowledgeloop-m0-walking-skeleton.md`](../../loop-agent/docs/superpowers/plans/2026-07-04-knowledgeloop-m0-walking-skeleton.md)
and the SOURCE engine docs under [`../../knowledgeLoop/docs/`](../../knowledgeLoop/docs/) (reference, do not copy).

## 8. Non-goals (YAGNI)

Left as clean seams, **not built now**: a multi-domain plugin framework or a second domain; real JIRA/Gerrit
clients and a live Gerrit container; an ANN vector index; deeper build/test ("Tier-3") grading; the full
130+-repo production fleet. The fleet grows by requirement across its layers —
production **target** 130+ AAOS repos, charter **pilot** ~11 OSS repos, **built corpora** 3 at pinned SHAs
(`corpora/corpus.toml`), and the **hermetic M1 fixture** of 4 repos — see [charter](charter.md) and
[roadmap](roadmap.md). Milestones **GL-M0** (walking skeleton) and **GL-M1** (real `AtlasIndex` +
`gloop index/produce/doctor`) have landed.
