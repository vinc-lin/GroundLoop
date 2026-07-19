# Relocate & Strip `produce` (CodeWiki) — Design

> **Date:** 2026-07-19 · **Status:** design deliverable (first-principles review Phase-2 menu #1, the deferred
> *physical* relocation). Feeds an implementation plan next.
> **Provenance:** the first-principles review (`docs/superpowers/specs/2026-07-18-first-principles-review.md` §5
> finding #1) found `groundloop/engines/produce/` — a vendored CodeWiki doc generator — is **65% of the tree**,
> build-time-only, `[production]`-value "within noise" (0 doc units in the prod atlas), with **~4,500 LOC dead
> even inside it**. Cycle 1 externalized its *dependencies* (a `[produce]` extra), locked the *import boundary*
> (product can't module-import produce), and made `build_atlas` symbol-only. This is the deferred **physical
> relocation + strip**. A grounded duplication investigation (2026-07-19) produced the reachability-precise
> live/dead boundary this spec is built on.

## 1. Goal

Move produce out of the `groundloop/` product package **and** delete everything the atlas build never reaches —
so the product tree is lean and contains only product code, while the doc-generation the atlas actually uses
stays available. `groundloop/core/` + the atlas schema stay **zero-diff**; the produce→atlas **filesystem output
contract** (`module_tree.json`, `metadata.json`, `.md` doc-units) is preserved verbatim.

## 2. The two moves

### 2a. Relocate: `groundloop/engines/produce/` → top-level `codewiki/`
An in-repo top-level package (NOT a separate repo/distribution — YAGNI; the review said "sibling tool"). The
product package `groundloop/` stops containing the generator. `[produce]` extra deps are unaffected.

### 2b. Strip to the reachable core
**Anchor:** `gloop produce` → `cli/__init__.py::_run_produce` → `CLIDocumentationGenerator.generate()` is the
**only** entry the atlas build uses (`build/produce_fleet.py` subprocesses `python -m groundloop.cli produce`).
**Method (the plan executes this):** a static reachability trace from `CLIDocumentationGenerator` → the LIVE
set; everything not reachable (and not needed for the output contract) is DEAD → `git rm`. Migration-verbatim
is honored for the LIVE code (only the import-prefix rewire + the `_envcompat` vendor, §3); the DEAD code is
**removed, not rewritten**.

**Known DELETE targets** (grounded, reachability-confirmed as unreachable from `CLIDocumentationGenerator`):
- **Non-produce entry apps:** `mcp/` (the *CodeWiki* MCP server — NOT the CBM you depend on; that's the separate
  `codebase-memory-mcp` pkg + `engines/lore/graph/`), `src/fe/` (FastAPI web app), `run_web_app.py`,
  `src/be/main.py`, `__main__.py` (the standalone `python -m` entry).
- **Standalone CodeWiki CLI:** `cli/main.py` + `cli/commands/*` (`generate`/`regenerate`/`config`/`version`) —
  the human `codewiki` CLI; the atlas build never goes through it (it builds `CLIDocumentationGenerator` directly).
- **Redundant config lane:** `cli/config_manager.py` (keyring/persistent settings) + `cli/models/config.py`
  (`Configuration`/`AgentInstructions`) — carries a literal **copy-paste** of the `get_prompt_addition()` +
  `doc_type_instructions` block that also lives (live) in `src/config.py`. Keep only the `src/config.py::Config`
  copy.
- **The backend's dead `run()` orchestration:** `src/be/documentation_generator.py::DocumentationGenerator.run()`
  (~lines 636-707) — a redundant re-implementation of the adapter's live `_run_backend_generation()`; its only
  callers are the deleted `mcp/`, `src/be/main.py`, `src/fe/`. Delete `run()` *after* those callers are gone
  (keep the `DocumentationGenerator` class + its fine-grained methods).
- **Dead utils:** `cli/utils/{fs,validation,repo_validator,instructions,logging,api_errors}.py` (`api_errors.py`
  is imported by nothing; the rest are only reached by the deleted config-lane/standalone-CLI).

**KEEP — the LIVE doc-gen path** (do NOT delete): `cli/adapters/doc_generator.py` (`CLIDocumentationGenerator`);
the backend `DocumentationGenerator` class + its live methods (`build_dependency_graph`,
`generate_module_documentation`, `create_documentation_metadata`) and their transitive deps
(`dependency_analyzer/`, `get_backend`/`backend`, `cluster_modules`, `prompt_template`, `model_profiles`,
`src/be/utils.py`, agent tools); `src/config.py::Config` (+ constants); `src/utils.py::FileManager`; the live cli
helpers `cli/utils/progress.py`, `cli/utils/errors.py`, `cli/models/job.py`, `cli/git_manager.py`; `templates/`;
`py.typed`; the `__init__.py` package structure (pruned to survivors).

**Ambiguous — plan verifies before deciding:** `cli/html_generator.py` + its `cli/utils/fs.py` dep are reachable
from the adapter ONLY when `generate_html=True`, which default `gloop produce` never sets. **Delete IF** the
adapter's html import is function-local/guarded (so removing it can't break module import); **keep** if it's a
module-level import. The plan checks `doc_generator.py`'s html import site and decides.

## 3. The one real code edit — vendor `_envcompat`
`produce/cli/config_manager.py:19` imports `from groundloop.engines._envcompat import getenv_compat` — a reverse
dependency *up into* `groundloop/`. BUT `config_manager.py` is a DELETE target (§2b), so this edge likely
**disappears with the strip**. The plan must confirm: after the strip, `grep -rn "engines._envcompat" codewiki/`
→ if any surviving LIVE file still imports it, **vendor** the 30-line shim (`os`/`warnings` only, no groundloop
deps) into `codewiki/` and repoint; if the only importer was the deleted `config_manager.py`, no vendor is
needed (the reverse dep is gone for free). Either way, `codewiki/` ends up self-contained (no import back into
`groundloop`).

## 4. Repoint the externals (small, exact)
- `groundloop/cli/__init__.py:113` — the one lazy import (`gloop produce` stays a thin bridge):
  `from codewiki.cli.adapters.doc_generator import CLIDocumentationGenerator` (the try/except helpful-error stays).
- The ~remaining internal `groundloop.engines.produce.*` imports across the SURVIVING files → `codewiki.*`
  (scripted `sed`, over the post-strip tree).
- **Tests (3):** `tests/build/test_cli_produce_concurrency.py` (monkeypatch target string), `tests/engines/
  test_produce_smoke.py` (import + monkeypatch), `tests/engines/test_doc_generator_navigate.py` (import).
  Repoint `groundloop.engines.produce` → `codewiki`. (These target the LIVE doc-gen path, so they survive the
  strip; any test that only exercised a deleted app would itself be deleted — the plan checks none do.)
- **`tests/architecture/test_import_boundary.py`:** the `FORBIDDEN` entry `"groundloop.engines.produce"` →
  `"codewiki"` (a `codewiki.*` import is outside the `groundloop/` scan root, so the FORBIDDEN entry is what keeps
  the boundary guarding product↛the generator).
- **`pyproject.toml`:** `[tool.setuptools.packages.find] include = ["groundloop*"]` → `["groundloop*",
  "codewiki*"]` so the relocated package is still installable/importable. The `[produce]` extra list is unchanged.
- **No repoint needed:** `build/produce_fleet.py` (subprocesses via the `groundloop.cli produce` string), the
  entire atlas/loader path (`engines/lore/wiki/loader.py` + consumers — filesystem contract).

## 5. Verification — the honest caveat
The hermetic Type-1 suite **cannot run `gloop produce` end-to-end**: `test_produce_smoke` monkeypatches the
generator, `test_doc_generator_navigate` is `importorskip`'d on `pydantic_ai`, and the real doc-gen needs the LLM
gateway. So the strip's correctness rests on:
1. **Static reachability** (conservative — retain anything reachable, incl. `importlib`/string dynamic imports the
   plan greps for).
2. **Import-smoke:** with the `[produce]` extra installed, `python -c "import codewiki.cli.adapters.doc_generator"`
   and importing the kept backend closure succeed (no dangling import to a deleted module).
3. **Full suite + ruff** green (the 3 produce tests exercise the live path).
The **final** confirmation is a real `gloop produce` run on a tiny repo — **Type-2, gateway-gated** — which this
spec calls out as a follow-up, NOT a merge gate for the structural move.

## 6. Non-goals
- No separate repo / PyPI distribution (in-repo `codewiki/` sibling package suffices).
- No reconciling / touching the cross-repo vendoring source `/mnt/x/code/knowledgeLoop/knowledgeloop/produce/`
  (different repo, held open by live processes, intentionally diverged incl. a GroundLoop-only bugfix — off-limits).
- No rewrite of produce's LIVE logic (migration-verbatim); no behavior change to `gloop produce` or the atlas build.
- Not removing `gloop produce` (kept as the bridge); not adding a standalone `codewiki` console script (the
  standalone CLI is being stripped — produce is reachable only via `gloop produce`).

## 7. Module touch-map (feeds the plan)
| Change | Target |
|---|---|
| Strip (delete) | `mcp/`, `src/fe/`, `run_web_app.py`, `src/be/main.py`, `__main__.py`, `cli/main.py`, `cli/commands/`, `cli/config_manager.py`, `cli/models/config.py`, `DocumentationGenerator.run()`, `cli/utils/{fs?,validation,repo_validator,instructions,logging,api_errors}.py` |
| Relocate | surviving `groundloop/engines/produce/**` → `codewiki/**` + internal `groundloop.engines.produce.*`→`codewiki.*` |
| Vendor (if needed) | `_envcompat` shim → `codewiki/` (only if a surviving file imports it) |
| Repoint | `cli/__init__.py:113`, 3 produce tests, `test_import_boundary.py` FORBIDDEN, `pyproject.toml` packages.find |
| Zero-diff | `groundloop/core/**`, atlas schema, the produce→atlas filesystem output contract |

## 8. Open questions for the plan
- The exact reachability closure of `src/be/` from `CLIDocumentationGenerator` (the plan runs the trace + greps
  for dynamic imports before the final delete list).
- `cli/html_generator.py` keep-vs-delete (per the §2b html-import-guard check).
- Sequencing for green-per-commit: strip-in-place (delete dead, suite green — the 3 produce tests target the live
  path) → vendor `_envcompat` if needed → `git mv` survivors to `codewiki/` + rewrite imports → repoint externals
  + contract + pyproject → import-smoke. Each a self-contained green commit.
