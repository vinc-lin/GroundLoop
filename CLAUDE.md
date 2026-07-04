# GroundLoop

GroundLoop is a **code-driven, model-portable pipeline + benchmark** for automated bug-fixing across a
large fleet of **Android Automotive (AAOS) in-vehicle** repos. The real problem: an automated closed
loop from a **JIRA defect ticket + failure LOGS → code fix across 130+ repos**, with a traceable
JIRA↔commit chain.

**Stage-1 core objective = ticket→repo matching.** From ticket text + log signals (exception/error
stacks, module/process/package/class/method names, `.so` names), identify which repo among many OWNS
the defect. Downstream: localize → fix → change/PR↔JIRA bind. The owning repo is a *predicted output +
hidden-oracle field*, **never a loop input**.

**Core principle — "grounding over narrative":** trust only what reality verifies (real matches over a
real index, deterministic control flow, passing tests); distrust unverifiable LLM prose. The Python
orchestrator owns control flow; **the loop never sees the oracle** (grading is a separate offline pass).

## Architecture — ports & adapters (hexagonal)
- `groundloop/core/` — **FROZEN**, domain-agnostic: types, the ports (Protocols), and `run_ticket`
  (the deterministic control plane: intake → extract → match → materialize → localize → fix → submit →
  bind). Do **not** edit `core/` for a feature; swap behavior at the composition root (`cli/__init__.py`).
- `groundloop/adapters/` — port implementations: `mock/` (MockJira, MockGerrit, CannedModel = the
  hermetic test substrate), `index/` (`TokenIndex` M0 stub, `AtlasIndex` real FTS5 matcher over an
  atlas.db), `estate.py` (MockEstate), `fix/` (CannedFixEngine).
- `groundloop/engines/` — migrated **as-is** from the old knowledgeLoop (source:
  `/mnt/x/code/knowledgeLoop/knowledgeloop/`): `atlas/` (Store/embed/retrieve/registry/index),
  `lore/` (CBM client + launch + wiki), `produce/` (CodeWiki generation).
- `groundloop/domains/android_ivi/` — the domain pack (fleet catalog, `AndroidSignalExtractor`).
  Multi-domain is a design-for-later seam; no plugin framework yet (YAGNI).
- `groundloop/config/settings.py` — the single env-reading surface (`KLOOP_*`).

The **7 core ports** (`core/ports.py`): IssueSource, SignalExtractor (domain), RepoEstate, CodeIndex
(`rank_repos` + `retrieve`), FixEngine, ChangeSink, Model. (`Embedder` is an engine-internal Protocol in
`engines/atlas/embed.py`; `grade()` is an offline **function** in `groundloop/grade/grader.py` — neither
is a core port.) `rank_repos(signals, catalog) -> [RepoScore]` is the ticket→repo MATCH method; top-1 =
predicted owning repo. Full rationale: `docs/architecture.md`.

## Status
Current state, blockers, and next steps live in **`docs/STATUS.md`** — read it first when resuming.
Milestones **GL-M0** (walking skeleton) + **GL-M1** (real `AtlasIndex` + `gloop index` build) have landed
— GroundLoop's own track, distinct from the `bfl` **BFL-M0..M9** and the repo-matching spec **M1–M5**
tracks (never write a bare "M1"; see `docs/roadmap.md`).

## Docs — single source of truth
**GroundLoop `docs/` is the single source of truth** (consolidated 2026-07-04 from `../loop-agent` +
`../knowledgeLoop`; those repos carry "canonical → GroundLoop" banners atop the absorbed docs):
- `docs/charter.md` — mission, FR-1..8 / NFR-1..8, the four stages, metrics, fleet layers, glossary.
- `docs/application-guide.md` — how GroundLoop is applied: the pipeline + benchmark uses and scenarios.
- `docs/architecture.md` — hexagonal ports & adapters, the deterministic control plane, migration.
- `docs/engines.md` — produce / lore / CBM / atlas engine operations (migrated from knowledgeLoop).
- `docs/roadmap.md` — mining, the two-stage matcher, milestone tracks, downstream phasing.
- `docs/downstream-fix-loop.md` — design provenance for localize → fix → grade (fix stage is a stub).
- `docs/type2-evaluation.md` — **canonical for the Type-2 (Test 2) evaluation**: fleet, dataset, arms,
  metrics/scorecard, and the eval harness (supersedes the detail in `groundloop-testing-strategy.md` §3).
- `docs/m1-index-build.md` · `docs/type2-eval-setup.md` · `docs/groundloop-testing-strategy.md`.
GL-M1 plan (for provenance):
`/mnt/x/code/loop-agent/docs/superpowers/plans/2026-07-04-groundloop-m1-index-build.md`.

## Working in this repo
- Python 3.12, `.venv` (uv-managed). `pyproject.toml` — CBM + CodeWiki `produce` are **default deps**
  (the CBM Level-1 decision: `mcp` + `codebase-memory-mcp==0.8.1` + the produce stack in base deps).
- Setup: `uv sync --extra dev` (base deps + `pytest`/`ruff`; plain `uv sync` omits the test tooling).
- Tests: `.venv/bin/python -m pytest -q`  ·  Lint: `.venv/bin/ruff check groundloop tests` (line 110).
  Single test: `.venv/bin/python -m pytest tests/test_atlas_index.py -q` (or `-k <pattern>`).
  Gated Type-2 live tests (`tests/e2e/`) need env flags — see `docs/type2-eval-setup.md`.
- CLI: `.venv/bin/gloop {run,index,produce,doctor}`.
- **Two test surfaces** (`docs/groundloop-testing-strategy.md`): **Type-1 (Test 1)** hermetic
  development tests (no network / no real LLM; runs every change; shared fixtures in
  `tests/conftest.py`, anti-leak invariants in `tests/test_invariants.py`) and **Type-2 (Test 2)** live
  eval / evaluation environment (real models + a real atlas.db; `skipif`-gated). Live-eval setup +
  build steps: `docs/type2-eval-setup.md`.

## Conventions & guardrails
- **Never modify `groundloop/core/`.** Never alter the SQLite schema in `engines/atlas/store.py` (there
  is no schema-version guard — a change forces a full re-index).
- **Secret hygiene:** never commit keys, tokens, LAN IPs, or the real `.env`. `.env` is gitignored
  (it reuses the LiteLLM gateway creds from `/mnt/x/code/loop-agent/.env`); all config is env-only
  (`KLOOP_*`). `.env.example` holds placeholders only.
- Migration = copy the real source file, rewire `knowledgeloop.*` → `groundloop.engines.*`, preserve
  logic verbatim (only the import rewire + the `_envcompat` shim change).
- Reuse contract (keep an atlas.db shareable): embed model pinned `bge-m3` at index + query time;
  stable repo names + pinned SHAs; shared atlas.db path; schema unchanged.
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  Commit only when the suite is green + ruff clean.
- Plans / substantial features: subagent-driven (superpowers skills), two-stage review per task.
- Deep project history predating this repo lives in the loop-agent memory at
  `/home/vinc/.claude/projects/-mnt-x-code-loop-agent/memory/`. This repo is reachable as both
  `/mnt/x/code/GroundLoop` and `/home/vinc/code/GroundLoop` (same directory). The migration SOURCE
  engine stays at `/mnt/x/code/knowledgeLoop` (do not rename — held open by live processes).
