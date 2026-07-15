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
  atlas.db), `estate.py` (MockEstate), `fix/` (`CannedFixEngine` hermetic stub + `ModelPatchEngine`
  real propose-patch), `model/` (`GatewayModel`), `skills/` (`MockSkillRegistry` = the SP3 dev-experience KB).
- `groundloop/engines/` — migrated **as-is** from the old knowledgeLoop (source:
  `/mnt/x/code/knowledgeLoop/knowledgeloop/`): `atlas/` (Store/embed/retrieve/registry/index),
  `lore/` (CBM client + launch + wiki), `produce/` (CodeWiki generation).
- `groundloop/domains/android_ivi/` — the domain pack (fleet catalog, `AndroidSignalExtractor`).
  Multi-domain is a design-for-later seam; no plugin framework yet (YAGNI).
- **Type-2 stack** (eval/benchmark side): `eval/` (oracle-blind Stage-1 matching eval → scorecard),
  `fixeval/` (fix-loop eval: file_recall/patch_applies/resolved_rate/fabrication_rate + `compare`),
  `mine/` (GitHub issue→merged-PR miner, incl. typed honest-refusal negatives), `synth/` (AAOS synth
  failure-log generation), `skills/`+`kb/` (dev-experience KB: raw `Skill` feedstock distilled into the
  injectable `Knowledge` primitive; leak-safe corpus),
  `build/` (fleet clone + atlas build), `grade/` (offline grader).
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
The Type-2 (Test 2) track has since shipped end-to-end: SP1 (honest-refusal negatives) → SP2 (fix-loop
eval) → SP3 (dev-experience KB arm), plus the KB feedstock corpus. All eval results (incl. the first
cross-stage evaluation and the first production run) live in `docs/results-log.md`, `[proxy]`/`[production]`-tagged.

## Docs — single source of truth
**GroundLoop `docs/` is the single source of truth** (consolidated 2026-07-04 from `../loop-agent` +
`../knowledgeLoop`; re-consolidated 2026-07-11 from 23 → 12 top-level docs — see the design/plan under
`docs/superpowers/{specs,plans}/2026-07-11-docs-optimization*.md`; `capabilities.md` added 2026-07-12):
- `docs/environments.md` — **the canonical dev-box ↔ production split + the `[proxy]`/`[production]` result
  tag convention.** Read this first; every other doc links here instead of restating it.
- `docs/capabilities.md` — **the Production-Core / Dev-Labs governance model + the capability registry**
  (every capability → Core / Candidate / Dev-Labs-Infra / Fixture / Archived, with evidence). The line
  between the product and research scaffolding; says which `gloop run` defaults are Core-aligned.
- `docs/workflows.md` — the two operational checklists (**Production** deploy→run→grade→feedback SOP +
  **Dev** inner-loop/Candidate→Core promotion) + the **per-stage feature map** (stage × feature × state).
- `docs/charter.md` — mission, FR-1..8 / NFR-1..8, the four stages, metrics, glossary, non-goals.
- `docs/architecture.md` — hexagonal ports & adapters, the deterministic control plane, atlas internals, migration.
- `docs/guide.md` — how GroundLoop is deployed, run, and migrated (the single how-to; adapter swap map, checklist).
- `docs/evaluation.md` — **canonical for the evaluation**: Type-2 effectiveness (fleet, dataset, arms,
  metrics/scorecard, harness) **+ the Type-1 hermetic test surface (§14)**.
- `docs/build-setup.md` — atlas build + env-var reference + the reuse contract + gated-live setup + the
  portable atlas-build gotchas (CBM timeout, one-index-at-a-time, `pgrep -fa` not `ps -C`, run eval off ext4).
- `docs/fix-loop.md` — localize → fix → grade design provenance + the dev-experience KB (a measured fix arm).
- `docs/kb-distillation.md` — **how the KB distills Skills into knowledge** (the Skill source + Knowledge
  primitive, the distillation lane, injection, the admit-on-measured-lift retain-loop; machinery built, efficacy production-gated).
- `docs/engines.md` — produce / lore / CBM / atlas engine operations (migrated from knowledgeLoop).
- `docs/production-guide.md` — production deploy / validate / feedback SOP (the production side of `environments.md`).
- `docs/roadmap.md` — mining, the two-stage matcher, milestone tracks, downstream phasing.
- `docs/results-log.md` — chronological, `[proxy]`/`[production]`-tagged log of every eval result.
- `docs/STATUS.md` — current state, blockers, next steps (read first when resuming).
GL-M1 plan (for provenance):
`/mnt/x/code/loop-agent/docs/superpowers/plans/2026-07-04-groundloop-m1-index-build.md`.

## Working in this repo
- Python 3.12, `.venv` (uv-managed). `pyproject.toml` — CBM + CodeWiki `produce` are **default deps**
  (the CBM Level-1 decision: `mcp` + `codebase-memory-mcp==0.8.1` + the produce stack in base deps).
- Setup: `uv sync --extra dev` (base deps + `pytest`/`ruff`; plain `uv sync` omits the test tooling).
- Tests: `.venv/bin/python -m pytest -q`  ·  Lint: `.venv/bin/ruff check groundloop tests` (line 110).
  Single test: `.venv/bin/python -m pytest tests/test_atlas_index.py -q` (or `-k <pattern>`).
  Gated Type-2 live tests (`tests/e2e/`) need env flags — see `docs/build-setup.md`.
- CLI: `.venv/bin/gloop {run,grade-run,index,produce,doctor,build-atlas,build-textprofile,mine,mine-affinity,eval,label-bugkind,fixeval,funceval,faulteval,synth,combine-oracle,compare,kb-ab,kb-extract,kb-attribute}`.
  `gloop run` defaults (Core-aligned): match `component` arm + **`--fixer plan`** (the Provisional-Core
  `PlanningFixEngine` "Bug Plan Mode", default since 2026-07-13; `--fixer` = `canned|model|plan`; safety default —
  abstains not fabricates, effectiveness production-gated) + localize `tokens` (the Provisional-Core
  `SignalQueryIndex` default since 2026-07-15; `atlas` is the reversible opt-out), fail-closed without
  gateway creds / a valid `--repos`. Experimental Candidate arms are opt-in, never the silent default:
  `--match-arm {semantic,judge,functional,dispatch}`, `--localize {atlas,semantic,dispatch}`,
  `--profile labs`/`KLOOP_LABS` (reachable ≠ default — see `docs/capabilities.md`).
- **Two test surfaces** (`docs/evaluation.md` §14 + `docs/environments.md`): **Type-1 (Test 1)** hermetic
  development tests (no network / no real LLM; runs every change; shared fixtures in
  `tests/conftest.py`, anti-leak invariants in `tests/test_invariants.py`) and **Type-2 (Test 2)** live
  eval / evaluation environment (real models + a real atlas.db; `skipif`-gated). Live-eval setup +
  build steps: `docs/build-setup.md`.
- **`KLOOP_DEV` dev-gate:** the hermetic fixtures (`--index` M0 stub, `--fixer canned`, single-case `--case`)
  are **dev-gated** — reachable only with `KLOOP_DEV=1` (or the hidden `--dev` flag). The Type-1 suite arms
  `KLOOP_DEV=1` via an autouse fixture; **production leaves `KLOOP_DEV` OFF** so a run cannot silently select a
  hermetic double.

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
- **KB/fix-arm gotcha:** `localize` runs *before* fix `propose`, so a fix-stage Skill/Knowledge injection is
  `file_recall`-invariant — grade KB lift on `resolved_rate`/`patch_applies`/`fabrication_rate`, never
  `file_recall@1`. The eval datasets carry **no** honest-refusal negatives yet (those metrics are fixture-only).
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  Commit only when the suite is green + ruff clean.
- Plans / substantial features: subagent-driven (superpowers skills), two-stage review per task.
- Deep project history predating this repo lives in the loop-agent memory at
  `/home/vinc/.claude/projects/-mnt-x-code-loop-agent/memory/`. This repo is reachable as both
  `/mnt/x/code/GroundLoop` and `/home/vinc/code/GroundLoop` — but `/home/vinc/code` is a **symlink to
  `/mnt/x/code`** (a **v9fs Windows-drive mount**), so BOTH paths are slow for random I/O. Run atlas
  builds and `gloop eval` (sqlite over the multi-GB atlas) off **real ext4** — `/home/vinc` *directly*
  (not `/home/vinc/code`), `/var/tmp`, or `/dev/shm`. The migration SOURCE engine stays at
  `/mnt/x/code/knowledgeLoop` (do not rename — held open by live processes).
