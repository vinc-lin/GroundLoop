# Relocate & Strip `produce` (CodeWiki) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate `groundloop/engines/produce/` → top-level `codewiki/` (out of the product package) and delete the ~30 dead files the atlas build never reaches — keeping only the 56-file live doc-gen path.

**Architecture:** Pure structure — no live-logic rewrite. The critical ordering: `produce/__init__.py:11` eagerly imports the standalone CLI (`from ...cli.main import cli`), so importing produce executes the "dead" CLI/config tree at import time. **Neutralize that `__init__` edge FIRST** (Task 1); then the 30 dead files are import-dead and deletable (Task 2); then relocate survivors + rewrite imports (Task 3); then the contract + docs (Task 4). No dynamic import escapes the closure; `_envcompat` needs no vendoring (its only importer is deleted); `templates/` is deletable (only the deleted HTML viewer used it).

**Tech Stack:** Python 3.12, `uv` `.venv`, `pytest`, `ruff` (line-length 110). Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`.

**Hard constraints:** never edit `groundloop/core/`; never touch the atlas schema; no rewrite of produce's LIVE logic; preserve the produce→atlas filesystem output contract (`module_tree.json`/`metadata.json`/`.md` doc-units); suite green + ruff clean **per commit**. Verification caveat (spec §5): the hermetic suite mocks/gates produce doc-gen, so correctness rests on the reachability trace + an import-smoke + the suite; a real `gloop produce` run is a **gateway-gated follow-up**, not a merge gate.

---

## The dead set (30 files, from the reachability trace)

**Unconditionally dead (18):** `__main__.py`, `cli/html_generator.py`, `cli/utils/api_errors.py`, `mcp/__init__.py`, `mcp/server.py`, `run_web_app.py`, `src/be/main.py`, and `src/fe/{__init__,background_worker,cache_manager,config,github_processor,models,routes,template_utils,templates,visualise_docs,web_app}.py` (11).

**Conditional-dead (12) — deletable only after the Task-1 `__init__` edit:** `cli/main.py`, `cli/commands/{__init__,config,generate,regenerate}.py`, `cli/config_manager.py`, `cli/models/config.py`, `cli/utils/{fs,instructions,logging,repo_validator,validation}.py`.

Plus **`templates/`** (dir). **Keep** the 56 live files (the adapter, the `DocumentationGenerator` backend + both LLM backends + all 9 analyzers + full `dependency_analyzer/`, `src/config.py`, `src/utils.py`, live cli helpers).

---

## Task 1: Neutralize the eager `__init__` import (unblocks the strip)

**Files:** Modify `groundloop/engines/produce/__init__.py`.

- [ ] **Step 1:** Read `groundloop/engines/produce/__init__.py` + `cli/main.py`. Confirm `__init__.py:11` is `from groundloop.engines.produce.cli.main import cli` and note what it re-exports (`__all__`, `__version__`).
- [ ] **Step 2:** Edit `produce/__init__.py` so importing the package NO LONGER loads the standalone CLI tree: remove the `from ...cli.main import cli` import; if `cli`/`__version__` appear in `__all__`, remove/adjust them; if `__version__` was sourced from `cli.main`, hardcode it inline (e.g. `__version__ = "<the current value>"`) or drop it. The goal: `import groundloop.engines.produce` executes only a minimal `__init__` that imports NOTHING in the dead set. (The other package `__init__.py` files in the live chain are empty markers — no change needed.)
- [ ] **Step 3: Verify import + smoke.**
```bash
.venv/bin/python -c "import groundloop.engines.produce; print('ok')"
.venv/bin/python -c "import importlib; importlib.import_module('groundloop.engines.produce.cli.adapters.doc_generator'); print('adapter ok')"
```
Expected: both print ok (the live adapter still imports; the CLI tree is no longer eager).
- [ ] **Step 4: Full suite + ruff.** `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests` — green (the 3 produce tests route through the adapter/`main(["produce"])`, still fine).
- [ ] **Step 5: Commit**
```bash
git add groundloop/engines/produce/__init__.py
git commit -m "refactor(produce): stop __init__ eagerly importing the standalone CLI (unblocks the dead-code strip)"
```

## Task 2: Strip the 30 dead files + `templates/`

**Files:** `git rm` the dead set.

- [ ] **Step 1: Delete the dead files + templates dir** (all 30 are now import-dead after Task 1):
```bash
cd /mnt/x/code/GroundLoop
git rm groundloop/engines/produce/__main__.py \
       groundloop/engines/produce/run_web_app.py \
       groundloop/engines/produce/cli/html_generator.py \
       groundloop/engines/produce/cli/main.py \
       groundloop/engines/produce/cli/config_manager.py \
       groundloop/engines/produce/cli/models/config.py \
       groundloop/engines/produce/cli/utils/api_errors.py \
       groundloop/engines/produce/cli/utils/fs.py \
       groundloop/engines/produce/cli/utils/instructions.py \
       groundloop/engines/produce/cli/utils/logging.py \
       groundloop/engines/produce/cli/utils/repo_validator.py \
       groundloop/engines/produce/cli/utils/validation.py \
       groundloop/engines/produce/src/be/main.py
git rm -r groundloop/engines/produce/cli/commands \
          groundloop/engines/produce/mcp \
          groundloop/engines/produce/src/fe \
          groundloop/engines/produce/templates
```
- [ ] **Step 2: (optional cleanup) remove the dead `run()` method** — `src/be/documentation_generator.py::DocumentationGenerator.run()` (~lines 636-707) is dead (its only callers were the deleted `mcp/`/`src/be/main.py`/`src/fe/`). First confirm no live caller: `grep -rn "\.run()" groundloop/engines/produce/ | grep -i documentationgenerator` and `grep -rn "def run" groundloop/engines/produce/src/be/documentation_generator.py`. If confirmed uncalled, delete the method body. **If it looks entangled or risky, SKIP it** (a dead-but-uncalled method is harmless) and report DONE_WITH_CONCERNS.
- [ ] **Step 3: Verify import + smoke + no dangling imports.**
```bash
.venv/bin/python -c "import groundloop.engines.produce; print('ok')"
.venv/bin/python -c "import importlib; importlib.import_module('groundloop.engines.produce.cli.adapters.doc_generator'); print('adapter ok')"
grep -rn "html_generator\|config_manager\|cli.main\|cli.commands\|from .*cli.utils.fs\|src.be.main\|\.mcp\.\|src.fe" groundloop/engines/produce/ | grep -v "__pycache__" || echo "no dangling refs to deleted modules"
```
Expected: imports ok; no live file references a deleted module. (If a surviving file DOES reference one, that file was mis-classified — investigate, don't force.)
- [ ] **Step 4: Full suite + ruff.** `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests` — green (incl. the 3 produce tests).
- [ ] **Step 5: `_envcompat` confirm** — `grep -rn "engines._envcompat\|getenv_compat" groundloop/engines/produce/` → EMPTY (its only importer `config_manager.py` is deleted; no vendoring needed).
- [ ] **Step 6: Commit**
```bash
git commit -m "refactor(produce): strip ~30 dead files (web app, MCP server, standalone CLI, config lane, dead utils, templates)"
```

## Task 3: Relocate survivors → `codewiki/` + rewrite imports

**Files:** `git mv groundloop/engines/produce/` → `codewiki/`; rewrite internal `groundloop.engines.produce.*` → `codewiki.*`; repoint `cli/__init__.py:113` + the 3 produce tests; `pyproject.toml` packages.find.

- [ ] **Step 1: Move the surviving tree.**
```bash
git mv groundloop/engines/produce codewiki
```
- [ ] **Step 2: Rewrite all internal + external `groundloop.engines.produce` references → `codewiki`:**
```bash
grep -rl --include='*.py' "groundloop\.engines\.produce" codewiki groundloop tests \
  | xargs -r sed -i "s/groundloop\.engines\.produce/codewiki/g"
```
This hits: the ~internal self-imports across `codewiki/`, the lazy import in `groundloop/cli/__init__.py:113`, and the 3 test files (`tests/build/test_cli_produce_concurrency.py`, `tests/engines/test_produce_smoke.py`, `tests/engines/test_doc_generator_navigate.py`).
- [ ] **Step 3: Make `codewiki` an installable package** — `pyproject.toml`, `[tool.setuptools.packages.find]`:
```toml
include = ["groundloop*", "codewiki*"]
```
- [ ] **Step 4: Sanity + verify.**
```bash
grep -rn "groundloop\.engines\.produce" groundloop tests codewiki || echo "clean (no stale produce path)"
.venv/bin/python -c "import importlib; importlib.import_module('codewiki.cli.adapters.doc_generator'); print('codewiki adapter ok')"
.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
```
Expected: `clean`, adapter imports, suite green (the 3 produce tests now exercise `codewiki`). If `import codewiki` fails under pytest, confirm the repo root is on `sys.path` (it is via pytest rootdir); the pyproject change covers real installs.
- [ ] **Step 5: Commit**
```bash
git add -A codewiki/ groundloop/cli/__init__.py tests/ pyproject.toml
git commit -m "refactor(produce): relocate the stripped generator groundloop/engines/produce -> top-level codewiki/"
```

## Task 4: Update the import contract + docs

**Files:** `tests/architecture/test_import_boundary.py`, `docs/capabilities.md`, `CLAUDE.md`.

- [ ] **Step 1: Update the contract FORBIDDEN** — in `tests/architecture/test_import_boundary.py`, replace `"groundloop.engines.produce"` with `"codewiki"` (the product runtime must not module-import the relocated generator; the lazy `gloop produce` bridge stays sanctioned).
- [ ] **Step 2: Run the contract + sanity-mutation.**
```bash
.venv/bin/python -m pytest tests/architecture/test_import_boundary.py -q
```
Expected: PASS (the only `codewiki` importer in product is the lazy `cli:113`). Then temporarily add `import codewiki` at the TOP of `groundloop/run/report.py`, run the guard, confirm it FAILS listing that offender, then REVERT (`git diff` clean).
- [ ] **Step 3: Docs.** In `docs/capabilities.md` (the produce/externalize note) and `CLAUDE.md` (the architecture/engines note), record that the CodeWiki generator was relocated to top-level `codewiki/` (out of the `groundloop/` product package) and stripped to the live doc-gen path; `gloop produce` still bridges to it. Update any `groundloop/engines/produce` path reference in these two files (grep first). Do NOT rewrite dated/historical plan/spec docs.
- [ ] **Step 4: Full suite + ruff.** `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests` — green + clean.
- [ ] **Step 5: Commit**
```bash
git add tests/architecture/test_import_boundary.py docs/capabilities.md CLAUDE.md
git commit -m "test+docs: point the import contract at codewiki + record the produce relocation/strip"
```

---

## Self-Review

**Spec coverage:** relocate → Task 3; strip → Tasks 1-2 (the `__init__` unblock + the 30-file delete + `templates/` + optional `run()`); `_envcompat` → confirmed no-vendor (Task 2 Step 5); externals repoint → Task 3; contract + pyproject → Tasks 3-4; docs → Task 4; verification caveat → the import-smoke steps + the gated-follow-up note.

**Placeholder scan:** exact `git rm`/`git mv`/`sed` commands + import-smoke assertions; the one judgment call (`run()` method removal) is explicitly optional/skippable.

**Ordering (the load-bearing bit):** Task 1 (`__init__` edit) MUST precede Task 2 (delete) — else deleting the 12 conditional files breaks `import produce`. Task 2 (delete) precedes Task 3 (move) so we move less. Task 3 rewrites the tests+cli import in the SAME commit as the move (green per commit). Task 4's contract update passes because product only lazy-imports `codewiki`.

**Risk:** the reachability trace found no dynamic import escaping the closure, so a static-import rewrite is safe; the import-smoke + the 3 produce tests + the dangling-ref grep (Task 2 Step 3) catch a mis-classification. The residual, disclosed risk: no dev-box end-to-end `gloop produce` run (Type-2 gated) — the real doc-gen is verified only at the gated follow-up.
