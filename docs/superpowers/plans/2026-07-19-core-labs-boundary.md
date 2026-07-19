# Compile the Core/Labs Boundary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GroundLoop's Core/Labs boundary a CI-enforced import contract — the production runtime cannot module-import any labs package — by cutting the module-level product→labs edges (via re-export shims + relocation) and extending the AST import guard.

**Architecture:** A logical import contract, not a package rename. Pure module relocation + import repointing — **zero logic change**. Edge-cuts use re-export shims so only the *one* product importer of each shared helper repoints (labs keeps its imports). Relocations (`git mv` + scripted repoint) move the labs code out of product directories. Lazy/function-local imports remain the sanctioned opt-in seam.

**Tech Stack:** Python 3.12, `uv` `.venv`, `pytest`, `ruff` (line-length 110). Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`.

**Hard constraints:** never edit `groundloop/core/`; never touch the atlas schema; **no logic change** (move + repoint only); suite green + ruff clean **per commit**. Sequence: edge-cuts (Tasks 1–4) → relocations (Tasks 5–7) → contract (Task 8). `_FAULT_SCALE` (`cli:1424`, the only importer, **lazy**) is left as a sanctioned lazy seam — the module-level contract does not flag it, and pulling it down ripples funceval's TAU constants for no contract benefit (a documented refinement of spec §3 edge #4).

---

## File Structure

| File | Change |
|---|---|
| `groundloop/adapters/model/cost.py` | **Create** (moved from `eval/cost.py`) |
| `groundloop/eval/cost.py` | Re-export shim → `adapters.model.cost` (labs back-compat) |
| `groundloop/run/dataset.py` | **Create** — oracle-free `load_cases`/`CaseRef`/`case_catalog` (moved from `eval/dataset.py`) |
| `groundloop/eval/dataset.py` | Keep the oracle side; re-import + re-export the moved loaders |
| `groundloop/kb/inject.py` | **Create** (moved from `adapters/fix/knowledge_inject.py`) |
| `groundloop/adapters/index/labs/` | **New subpackage** — the 11 non-Core arms move here |
| `groundloop/skills/adapters/` | **New** — `adapters/skills/` moves here |
| `groundloop/grade/{grade_run,compare,promotion}.py` | Moved from `run/` |
| `groundloop/run/batch.py`, `adapters/model/gateway.py`, `cli/__init__.py` | Repoint imports |
| `tests/architecture/test_import_boundary.py` | Extend into the Core/Labs contract |
| `groundloop/core/**`, atlas schema | **zero-diff** |

---

## Task 1: Edge-cut — move `eval/cost.py` → `adapters/model/cost.py` (re-export shim)

**Files:** Create `groundloop/adapters/model/cost.py`; modify `groundloop/eval/cost.py`, `groundloop/adapters/model/gateway.py`.

- [ ] **Step 1: Move the module.** `git mv groundloop/eval/cost.py groundloop/adapters/model/cost.py`. `cost.py` has no groundloop imports (pure), so nothing inside it changes.
- [ ] **Step 2: Re-export shim** — create a new `groundloop/eval/cost.py`:
```python
"""Back-compat re-export: cost helpers moved to the product surface adapters/model/cost.py (Core/Labs
boundary). Labs may keep importing groundloop.eval.cost; product imports groundloop.adapters.model.cost."""
from groundloop.adapters.model.cost import PRICES, cost_from_raw, cost_of, tokens_from_raw  # noqa: F401
```
- [ ] **Step 3: Repoint the product importer** — `groundloop/adapters/model/gateway.py:6`:
```python
from groundloop.adapters.model.cost import cost_of
```
- [ ] **Step 4: Verify** — full suite + ruff. The 2 labs arm importers (`rerank_localize`, `atlas_judge`) and `tests/eval/test_cost.py` keep importing `groundloop.eval.cost` via the shim.

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: green + clean.

- [ ] **Step 5: Commit**
```bash
git add groundloop/eval/cost.py groundloop/adapters/model/cost.py groundloop/adapters/model/gateway.py
git commit -m "refactor(boundary): move cost helpers to product adapters/model/cost.py (eval.cost re-export shim); repoint GatewayModel"
```

## Task 2: Edge-cut — repoint `run/batch.py` off `fixeval.patch`

**Files:** Modify `groundloop/run/batch.py:10`.

- [ ] **Step 1: Repoint** — the real `patch_applies` is `groundloop/fix/patch.py:109` (already product; `fixeval/patch.py` is a re-export shim of it). Change `run/batch.py:10`:
```python
from groundloop.fix.patch import patch_applies
```
- [ ] **Step 2: Verify** — full suite + ruff green (behavior identical; same function).

Run: `.venv/bin/python -m pytest tests/run/ -q && .venv/bin/ruff check groundloop tests`

- [ ] **Step 3: Commit**
```bash
git add groundloop/run/batch.py
git commit -m "refactor(boundary): repoint run/batch.py patch_applies to product fix.patch (off fixeval)"
```

## Task 3: Edge-cut — split oracle-free loaders `eval/dataset.py` → `run/dataset.py` (re-export shim)

**Files:** Create `groundloop/run/dataset.py`; modify `groundloop/eval/dataset.py`, `groundloop/run/batch.py:9`.

- [ ] **Step 1: Read `groundloop/eval/dataset.py`.** Identify the oracle-FREE definitions to move: `CaseRef` (dataclass), `load_cases`, `case_catalog`, and their private helpers (`_ORACLE_KEYS` stays with the oracle side; anything `load_cases`/`case_catalog` need moves). The oracle side that STAYS: `load_oracle`, `load_eval_oracle`, `EvalOracle`.
- [ ] **Step 2: Create `groundloop/run/dataset.py`** — move the oracle-free loaders verbatim (they import only `groundloop.core.types` + stdlib, so they're product-clean):
```python
"""Oracle-free case/catalog loaders — the product-surface half of the old eval/dataset.py (Core/Labs
boundary). Reads the case dir's ticket/catalog, NEVER the hidden _oracle/. The oracle side stays in
eval/dataset.py (labs)."""
from __future__ import annotations
# ... CaseRef dataclass, load_cases(...), case_catalog(...) moved verbatim ...
```
- [ ] **Step 3: Edit `groundloop/eval/dataset.py`** — delete the moved defs; at the top, re-import + re-export them so every existing importer keeps working:
```python
from groundloop.run.dataset import CaseRef, case_catalog, load_cases  # noqa: F401  (moved to product surface)
```
Keep `load_oracle`/`load_eval_oracle`/`EvalOracle` in place (they may reference `CaseRef` — now imported from `run.dataset`).
- [ ] **Step 4: Repoint the product importer** — `groundloop/run/batch.py:9`:
```python
from groundloop.run.dataset import load_cases
```
(All other importers — cli lazy at 185/278/512, `eval/runner`, `fixeval/runner`, `funceval/runner`, `faulteval/runner`, `kb/ab`, `grade_run`, and every test — keep importing from `eval.dataset` via the shim.)
- [ ] **Step 5: Verify** — full suite + ruff green.

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`

- [ ] **Step 6: Commit**
```bash
git add groundloop/run/dataset.py groundloop/eval/dataset.py groundloop/run/batch.py
git commit -m "refactor(boundary): split oracle-free loaders to product run/dataset.py (eval.dataset re-export); repoint batch"
```

## Task 4: Edge-cut — move `knowledge_inject.py` → `kb/inject.py`

**Files:** `git mv groundloop/adapters/fix/knowledge_inject.py groundloop/kb/inject.py`; repoint `cli/__init__.py:1278`, `tests/fixeval/test_knowledge_inject.py:6`, `tests/run/test_cli_run_kb.py:11`.

- [ ] **Step 1: Move.** `git mv groundloop/adapters/fix/knowledge_inject.py groundloop/kb/inject.py`. Its internal imports (`kb.render`, `skills.ctx`) are unchanged (absolute paths still valid).
- [ ] **Step 2: Repoint the 3 importers** to `groundloop.kb.inject`:
  - `groundloop/cli/__init__.py:1278` (lazy, in `_wire_kb`): `from groundloop.kb.inject import KnowledgeInjectingFixEngine`
  - `tests/fixeval/test_knowledge_inject.py:6`, `tests/run/test_cli_run_kb.py:11`: same.
- [ ] **Step 3: Verify** — full suite + ruff green.

Run: `.venv/bin/python -m pytest tests/fixeval/test_knowledge_inject.py tests/run/test_cli_run_kb.py -q && .venv/bin/python -m pytest -q`

- [ ] **Step 4: Commit**
```bash
git add -A groundloop/kb/inject.py groundloop/adapters/fix/ groundloop/cli/__init__.py tests/fixeval/test_knowledge_inject.py tests/run/test_cli_run_kb.py
git commit -m "refactor(boundary): move the opt-in KB fixer to kb/inject.py (off the product adapters tree)"
```

## Task 5: Relocate the 11 non-Core index arms → `adapters/index/labs/`

**Files:** move `adapters/index/{simple,fault_routing,component_prior,atlas_semantic,functional_text,signal_query,split,cascade_localize,rerank_localize,atlas_judge,text_profile}.py` → `adapters/index/labs/`; repoint all importers. **`adapters/index/atlas.py` (Core) STAYS.**

- [ ] **Step 1: Create the subpackage + move the 11 arms.**
```bash
mkdir -p groundloop/adapters/index/labs
printf '"""Labs index arms — experimental match/localize strategies, opt-in only (Core/Labs boundary).\nThe Core index is groundloop/adapters/index/atlas.py, which stays outside this subpackage."""\n' > groundloop/adapters/index/labs/__init__.py
for m in simple fault_routing component_prior atlas_semantic functional_text signal_query split cascade_localize rerank_localize atlas_judge text_profile; do
  git mv groundloop/adapters/index/$m.py groundloop/adapters/index/labs/$m.py
done
```
- [ ] **Step 2: Repoint every importer** with a per-arm find-replace (each arm name is distinct from `atlas`, so this never rewrites the Core arm; the two movers that import `adapters.index.atlas` are left correct):
```bash
for m in simple fault_routing component_prior atlas_semantic functional_text signal_query split cascade_localize rerank_localize atlas_judge text_profile; do
  grep -rl --include='*.py' "adapters\.index\.$m\b" groundloop tests \
    | xargs -r sed -i "s/adapters\.index\.$m\b/adapters.index.labs.$m/g"
done
```
This handles: the intra-arm `rerank_localize.py` → `atlas_judge` import (rewritten to `labs.atlas_judge`), the module-level movers (`funceval/arms.py`, `funceval/runner.py`), the cli lazy ladder, and all test importers (see the spec's importer map). The two arms importing `adapters.index.atlas` (`fault_routing.py:9`, `functional_text.py:9` — now under `labs/`) keep the unchanged `adapters.index.atlas` path (the sed only matches the 11 arm names, not `atlas`).
- [ ] **Step 3: Sanity — no stray old paths.**
```bash
grep -rn "adapters\.index\.\(simple\|fault_routing\|component_prior\|atlas_semantic\|functional_text\|signal_query\|split\|cascade_localize\|rerank_localize\|atlas_judge\|text_profile\)\b" groundloop tests | grep -v "index\.labs\." || echo "clean"
```
Expected: `clean` (every reference now goes through `.labs.`).
- [ ] **Step 4: Verify** — full suite + ruff green.

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: 753 passed / 8 skipped, clean. (If a bare-module import like `from groundloop.adapters.index import component_prior` in `tests/index/test_component_antileak.py:3` or `from groundloop.adapters.index import functional_text, text_profile` in `tests/index/test_functional_antileak.py:3` didn't get rewritten by the name-based sed, fix those by hand to `from groundloop.adapters.index.labs import ...`.)

- [ ] **Step 5: Commit**
```bash
git add -A groundloop/adapters/index/ groundloop/funceval/ groundloop/cli/__init__.py tests/
git commit -m "refactor(boundary): relocate the 11 non-Core index arms to adapters/index/labs/ (Core atlas stays)"
```

## Task 6: Relocate `adapters/skills/` → `skills/adapters/`

**Files:** move `adapters/skills/{mock,migrate}.py` + `adapters/skills/data/` → `skills/adapters/`; repoint `cli/__init__.py:239` + the ~9 test importers.

- [ ] **Step 1: Move.**
```bash
mkdir -p groundloop/skills/adapters
git mv groundloop/adapters/skills/mock.py groundloop/skills/adapters/mock.py
git mv groundloop/adapters/skills/migrate.py groundloop/skills/adapters/migrate.py
git mv groundloop/adapters/skills/data groundloop/skills/adapters/data
[ -f groundloop/adapters/skills/__init__.py ] && git mv groundloop/adapters/skills/__init__.py groundloop/skills/adapters/__init__.py || printf '' > groundloop/skills/adapters/__init__.py && git add groundloop/skills/adapters/__init__.py
```
`mock.py`'s `SEED_PATH = Path(__file__).parent / "data" / "aaos_playbooks.toml"` is `__file__`-relative, so it resolves in the new location with no edit (the `data/` dir moved with it). Its imports from `groundloop.skills.{base,ctx,predicate}` are now same-parent-package — leave as absolute (still valid) or convert to relative; absolute is simplest.
- [ ] **Step 2: Repoint importers** (find-replace the package path):
```bash
grep -rl --include='*.py' "adapters\.skills\." groundloop tests | xargs -r sed -i "s/adapters\.skills\./skills.adapters./g"
```
This hits `cli/__init__.py:239` (lazy) and the ~9 test files (`tests/skills/*`, `tests/fixeval/test_skill_*`, `tests/synth/test_logs.py`, `tests/kb/test_feedstock.py`'s `importorskip("groundloop.adapters.skills.mock")` string). **Do NOT** conflate the two `SEED_PATH`s — `cli:239-240` imports `adapters.skills.mock.SEED_PATH` (moves) AND `kb.validate.SEED_PATH as KB_SEED` (stays); the sed only touches the `adapters.skills.` path.
- [ ] **Step 3: Sanity + verify.**
```bash
grep -rn "adapters\.skills\." groundloop tests || echo "clean"
.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
```
Expected: `clean`, green, ruff clean.

- [ ] **Step 4: Commit**
```bash
git add -A groundloop/skills/adapters/ groundloop/adapters/skills/ groundloop/cli/__init__.py tests/
git commit -m "refactor(boundary): relocate adapters/skills (MockSkillRegistry) into skills/adapters/"
```

## Task 7: Relocate `run/{grade_run,compare,promotion}.py` → `grade/`

**Files:** move the 3 offline-grade modules; repoint `cli/__init__.py` (1320/1333/1343, lazy) + the ~10 test importers.

- [ ] **Step 1: Move.**
```bash
for m in grade_run compare promotion; do git mv groundloop/run/$m.py groundloop/grade/$m.py; done
```
`compare.py`/`promotion.py` have zero groundloop imports (clean move). `grade_run.py`'s internal imports are absolute and target modules that stay put (`adapters.index.atlas`, `core.types`, `eval.dataset` (shim), `eval.metrics`, `fix.patch`, `fixeval.*`, `run.record`) — all still valid; **but** its lazy labs-arm imports (`adapters.index.{signal_query,atlas_semantic,rerank_localize,cascade_localize}`) were already repointed to `.labs.` by Task 5's sed. Confirm.
- [ ] **Step 2: Repoint importers.**
```bash
for m in grade_run compare promotion; do
  grep -rl --include='*.py' "run\.$m\b" groundloop tests | xargs -r sed -i "s/groundloop\.run\.$m\b/groundloop.grade.$m/g"
done
```
Hits `cli/__init__.py:1320/1333/1343` (lazy) + `tests/run/test_grade_run_*.py`, `tests/run/test_run_compare.py`, `tests/run/test_promotion_notes.py`. **Watch-out:** do NOT rewrite `groundloop.fixeval.compare` (a different module) — the pattern `run\.compare` won't match `fixeval.compare`, so it's safe.
- [ ] **Step 3: Sanity + verify.**
```bash
grep -rn "groundloop\.run\.\(grade_run\|compare\|promotion\)\b" groundloop tests || echo "clean"
.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
```
Expected: `clean`, green, clean.

- [ ] **Step 4: Commit**
```bash
git add -A groundloop/grade/ groundloop/run/ groundloop/cli/__init__.py tests/
git commit -m "refactor(boundary): relocate offline-grade tooling (grade_run/compare/promotion) run/ -> grade/"
```

## Task 8: Extend the AST guard into the Core/Labs contract

**Files:** modify `tests/architecture/test_import_boundary.py`.

- [ ] **Step 1: Write the new contract test** — replace/extend the guard so the product runtime cannot module-import any labs package. Keep the existing produce rule as one case. Add the labs prefixes + the `adapters/index/labs` exclusion from the product scan:
```python
"""CI contract: the product runtime must not MODULE-import any labs package (Core/Labs boundary).
Function-local imports are the sanctioned opt-in seam (the cli's lazy arm/KB/produce/grade loads)."""
import ast, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "groundloop"
PRODUCT_DIRS = ["core", "config", "adapters", "domains", "run", "fix", "engines/atlas", "engines/lore"]
# labs subtrees that physically live under a product dir -> excluded from the product scan
EXCLUDE = [ROOT / "adapters" / "index" / "labs"]
FORBIDDEN = ("groundloop.eval", "groundloop.fixeval", "groundloop.funceval", "groundloop.faulteval",
             "groundloop.synth", "groundloop.mine", "groundloop.kb", "groundloop.skills",
             "groundloop.grade", "groundloop.build", "groundloop.adapters.index.labs",
             "groundloop.engines.produce")

def _module_level_imports(py):
    for node in ast.parse(py.read_text(), filename=str(py)).body:   # top-level only
        if isinstance(node, ast.Import):
            for a in node.names: yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module

def _product_files():
    files = [ROOT / "cli" / "__init__.py"]
    for d in PRODUCT_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            if not any(str(py).startswith(str(ex)) for ex in EXCLUDE):
                files.append(py)
    return files

def test_product_runtime_does_not_module_import_labs():
    offenders = []
    for py in _product_files():
        for mod in _module_level_imports(py):
            if any(mod == p or mod.startswith(p + ".") for p in FORBIDDEN):
                offenders.append(f"{py.relative_to(ROOT.parent)} -> {mod}")
    assert not offenders, "product module-level imports of labs (must be lazy/opt-in):\n" + "\n".join(offenders)
```
- [ ] **Step 2: Run it — expect PASS** (Tasks 1–7 cut every module-level product→labs edge).

Run: `.venv/bin/python -m pytest tests/architecture/test_import_boundary.py -q`
Expected: PASS. **If it fails, the offender list is the exact remaining edge to cut** — fix it (a missed repoint), don't weaken the contract.

- [ ] **Step 3: Sanity-mutation** — temporarily add `from groundloop.kb.knowledge import KnowledgePlaybook` at the TOP of `groundloop/run/batch.py`, run the guard, confirm it FAILS listing `run/batch.py -> groundloop.kb...`, then REMOVE the line (`git diff groundloop/run/batch.py` clean).
- [ ] **Step 4: Full suite + ruff.**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: green + clean.

- [ ] **Step 5: Commit**
```bash
git add tests/architecture/test_import_boundary.py
git commit -m "test(arch): compile the Core/Labs boundary - product runtime must not module-import any labs package"
```

## Task 9: Docs — record the compiled boundary

**Files:** `docs/capabilities.md`, `CLAUDE.md`.

- [ ] **Step 1:** In `docs/capabilities.md` §4 (enforcement), add that the Core/Labs boundary is now **CI-enforced** by `tests/architecture/test_import_boundary.py` (product runtime cannot module-import labs; lazy imports = the opt-in seam), and note the labs subpackage locations (`adapters/index/labs/`, `skills/adapters/`, `grade/`).
- [ ] **Step 2:** In `CLAUDE.md`, update the architecture note: the experimental index arms live in `adapters/index/labs/`, `MockSkillRegistry` in `skills/adapters/`, offline-grade tooling in `grade/`; the import contract enforces product↛labs.
- [ ] **Step 3: Verify** — re-read; `grep -n "adapters.index.labs\|CI-enforced" docs/capabilities.md CLAUDE.md`.
- [ ] **Step 4: Commit**
```bash
git add docs/capabilities.md CLAUDE.md
git commit -m "docs: record the CI-enforced Core/Labs import boundary + the labs subpackage locations"
```

---

## Self-Review

**Spec coverage:** §3 edges → Tasks 1 (cost), 2 (patch), 3 (dataset), 4 (knowledge_inject); `_FAULT_SCALE` left lazy (documented refinement). §4 relocations → Tasks 5 (arms), 6 (skills), 7 (grade). §5 contract → Task 8. §7 docs → Task 9. Invariants: no task edits `core/` or the atlas schema; all are move+repoint (no logic change).

**Placeholder scan:** every step is an exact command or code block. The bulk repoints are scripted `sed` (precise, per-distinct-name so `atlas` is never rewritten) with a `grep` sanity check + a hand-fix note for the two bare-module test imports.

**Type/path consistency:** the moved paths are used consistently — `adapters.model.cost`, `run.dataset`, `kb.inject`, `adapters.index.labs.<arm>`, `skills.adapters.*`, `grade.<mod>`. The re-export shims (`eval.cost`, `eval.dataset`) keep every labs importer valid so only the single product importer repoints per edge. The contract's `EXCLUDE`/`FORBIDDEN` match the relocation targets.

**Risk notes:** Task 5 is the largest (11 files + ~40 repoints) — the `grep -v index.labs` sanity check + the full suite catch a missed one; watch the two bare-module test imports. Do the tasks in order (Task 5's sed must run before Task 7 so grade_run's lazy arm imports are already `.labs.`). Each task is independently green + committable.
