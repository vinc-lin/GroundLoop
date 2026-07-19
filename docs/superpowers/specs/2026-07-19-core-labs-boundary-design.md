# Compile the Core/Labs Boundary — Design

> **Date:** 2026-07-19 · **Status:** design deliverable (first-principles review Phase-2 menu, item #5). Feeds
> an implementation plan next.
> **Provenance:** the first-principles review (`docs/superpowers/specs/2026-07-18-first-principles-review.md`
> §5 finding #4, §8, §9) found the Core/Labs boundary is **documentary, not structural** — the production
> `run` path, the ~13 index arms, the eval harnesses, and the KB all share one package tree, one CLI, one
> composition root, and `capabilities.md`'s "Dev Labs stays isolated from Production" is asserted but not
> enforced in code. This turns that boundary into a **CI-enforced import contract**.

## 1. Goal & approach

**Goal:** make it *impossible* (CI-caught) for the production runtime to depend on the research/labs surface,
so `capabilities.md`'s Production-Core / Dev-Labs governance is load-bearing in code, not just prose.

**Approach (chosen over a top-level `product/`+`labs/` package move):** a **logical import contract** — extend
Cycle 1's dependency-free AST guard (`tests/architecture/test_import_boundary.py`, which already forbids the
product runtime from module-importing `produce`) to forbid product→*any labs package* — **plus contained
relocations** of the labs code that currently sits inside product directories, so the guard's product scope is
a clean set. Lazy/function-local imports remain the **sanctioned opt-in seam** (exactly how `produce`, the KB,
and the experimental arms already load on demand).

**Invariants:** `groundloop/core/` and the atlas SQLite schema stay **zero-diff**; oracle-blindness / anti-leak
/ deterministic control flow are untouched (this is pure module relocation + import repointing); suite green +
ruff clean after every step. **Net logic change: none** — modules move and imports repoint; behavior is identical.

## 2. The product vs labs classification (grounded)

From the import-graph map (2026-07-19):

**Product runtime** (what a real `gloop run` executes): `groundloop/core/`, `config/`, `domains/`,
`engines/atlas/`, `engines/lore/`, `run/{batch,record,report,manifest}.py`, `adapters/{mock,estate,model,
extractor_recording}/`, `adapters/fix/{canned,planning,model_patch}.py`, `adapters/index/atlas.py` (the Core
`AtlasIndex`), and the `run` composition root in `cli/__init__.py`.

**Labs** (research/eval/benchmark): `eval/`, `fixeval/`, `funceval/`, `faulteval/`, `synth/`, `mine/`, `kb/`,
`skills/`, `grade/`, `build/`, every non-`atlas` index arm in `adapters/index/`, `adapters/skills/`, and the
offline-grade tooling `run/{grade_run,compare,promotion}.py`.

## 3. Cut the six product→labs import edges

| # | Current edge (file:line) | Fix |
|---|---|---|
| 1 | `adapters/model/gateway.py:6` → `eval.cost.cost_of` | **Move** `eval/cost.py` (pure — no groundloop imports) → `groundloop/adapters/model/cost.py` (product, next to `GatewayModel`). Repoint `gateway.py`; leave a re-export in `eval/cost.py` for labs back-compat (or repoint the 2 labs consumers `atlas_judge`/`rerank_localize` — they then import *down*, which is fine). |
| 2 | `run/batch.py:10` → `fixeval.patch.patch_applies` | **Repoint** to `from groundloop.fix.patch import patch_applies` (`fix/patch.py:109` — already product). The `fixeval/patch.py` re-export shim can stay for labs or be dropped. |
| 3 | `run/batch.py:9` → `eval.dataset.load_cases` | **Split** the oracle-free loader out: move `load_cases`/`CaseRef` → `groundloop/run/dataset.py` (product; imports only `core.types`). `eval/dataset.py` keeps `load_eval_oracle`/`EvalOracle` and imports `CaseRef`/`load_cases` *down* from `run/dataset` (re-exporting them so the ~10 labs importers don't all change). Repoint `run/batch.py`. |
| 4 | `cli/__init__.py:1424` → `funceval.arms._FAULT_SCALE` | **Pull the constant down** next to the dispatch arm (`adapters/index/labs/functional_text.py`, where `DispatchIndex` lives after the move in §4). The cli's dispatch branch reads it from the arm module (or a shared config); the `funceval` import goes away. `funceval/arms.py` re-imports it (labs→labs) or keeps its own. |
| 5,6 | `adapters/fix/knowledge_inject.py:7-8` → `kb.render` + `skills.ctx` | **Move** `knowledge_inject.py` → `groundloop/kb/inject.py` (labs — it *is* the opt-in `--kb-store` KB fixer). The run root's `_wire_kb` (`cli/__init__.py`) lazy-imports it (`from groundloop.kb.inject import KnowledgeInjectingFixEngine`) — the sanctioned opt-in seam, exactly like `produce`. Update `tests/fixeval/test_knowledge_inject.py`'s import. |

After these five moves/repoints, **no product-runtime file module-imports labs.**

## 4. Relocate the labs code sitting in product directories (contained)

Small, mechanical moves (`git mv` + repoint importers) so the product directories contain only product code:

- **Experimental index arms → `adapters/index/labs/`** (a new subpackage): `simple.py` (TokenIndex M0 stub),
  `fault_routing.py`, `component_prior.py`, `atlas_semantic.py`, `functional_text.py` (Dispatch/FunctionalText),
  `signal_query.py`, `split.py`, `cascade_localize.py`, `rerank_localize.py`, `atlas_judge.py`. **Leaves only
  `adapters/index/atlas.py`** (the Core arm) in the product-scanned dir. Repoint every importer — the cli's
  lazy per-arm imports (~12 sites in the `run`/`eval` handlers), plus `eval`/`fixeval`/`grade` consumers.
- **`adapters/skills/` → `skills/adapters/`** (or fold into `skills/`): `mock.py` (`MockSkillRegistry`),
  `migrate.py`, `data/`. Labs-only (consumed by `_load_skills`). Repoint `cli/_load_skills` (lazy) + tests.
- **`run/{grade_run,compare,promotion}.py` → `grade/`**: offline-grade tooling reached only by `gloop
  grade-run` (never `gloop run`). `run/` then holds only product-runtime modules. Repoint the `grade-run`/
  `compare` cli handlers (lazy) + tests.

## 5. The contract (the "compile")

Extend `tests/architecture/test_import_boundary.py` from a single-target guard into the Core/Labs contract:

- **Product scope:** files under `PRODUCT_DIRS = [core, config, adapters, domains, run, fix, engines/atlas,
  engines/lore]` **minus** the labs subtrees that live under a product dir (`adapters/index/labs/`,
  `adapters/skills/` → moved out), plus `cli/__init__.py`.
- **Forbidden (labs) prefixes:** `groundloop.{eval, fixeval, funceval, faulteval, synth, mine, kb, skills,
  grade, build}` + `groundloop.adapters.index.labs` + the existing `groundloop.engines.produce`.
- **Rule:** no product-scope file may **module-level** import a forbidden prefix. Walk `tree.body` only (as
  today) — **function-local imports are the sanctioned opt-in seam** (the cli's lazy arm/KB/produce loads, and
  `grade-run`/`fixeval` handlers, stay legal; that's how opt-in labs features are reached without a hard
  product dependency).
- **Sanity mutation** (in the test, like Cycle 1): a temporary top-level labs import in a product file must
  make the guard fail.
- **Keep** `tests/run/test_core_defaults_unchanged.py` (defaults are Core: `component`/`atlas`/`plan`) — the
  behavioral half of the contract.

## 6. Non-goals (YAGNI)

- **No top-level `product/`+`labs/` package split.** Same enforcement guarantee for a fraction of the churn;
  can be done later purely as directory cosmetics.
- **No new arm-registry.** The existing lazy per-selection import ladder in the `run` composition root already
  *is* the opt-in seam; the contract enforces the boundary without a registry abstraction. (Noted as a future
  option if the ladder grows unwieldy.)
- **No behavior change / no efficacy work.** Pure structure; every arm/harness stays reachable exactly as now.

## 7. Module touch-map

| Change | Files |
|---|---|
| Move (edge cuts) | `eval/cost.py`→`adapters/model/cost.py`; new `run/dataset.py` (from `eval/dataset.py` split); `adapters/fix/knowledge_inject.py`→`kb/inject.py` |
| Move (relocations) | `adapters/index/{10 arms}`→`adapters/index/labs/`; `adapters/skills/*`→`skills/adapters/`; `run/{grade_run,compare,promotion}.py`→`grade/` |
| Repoint imports | `adapters/model/gateway.py`, `run/batch.py`, `cli/__init__.py` (arm ladder + `_wire_kb` + `_load_skills` + grade-run/compare handlers), `eval/dataset.py` (re-export), the labs importers of the moved arms (`eval`/`fixeval`/`grade`), + affected tests |
| Constant | `_FAULT_SCALE` → the dispatch arm module |
| Contract | `tests/architecture/test_import_boundary.py` (extend) |
| Docs | `capabilities.md` (note the boundary is now CI-enforced) · `CLAUDE.md` (the labs subpackage locations) |
| Zero-diff | `groundloop/core/**`, atlas schema |

## 8. Open questions for the plan

- Exact home for the shared cost util (`adapters/model/cost.py` vs a neutral `groundloop/cost.py`) — pick the
  one that keeps labs importing *down* with the fewest repoints.
- Whether to keep the `eval/cost.py` / `fixeval/patch.py` / `eval.dataset` re-export shims (fewer labs repoints,
  slightly less "clean") or repoint every labs consumer (cleaner, more churn) — default to shims where they
  reduce churn without re-creating a product→labs edge.
- Sequencing so every commit stays green: edge-cuts first (each self-contained), then each relocation as its
  own commit (move + repoint + green), then the contract test last (it should pass once the moves land, then
  the sanity-mutation proves it bites).
