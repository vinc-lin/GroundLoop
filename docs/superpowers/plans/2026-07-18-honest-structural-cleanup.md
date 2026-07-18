# Honest Structural Cleanup — Implementation Plan (Cycle 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GroundLoop's documentation and packaging honest about what is actually delivered — stop presenting the mocked `bind`/`bound` as `[production]` efficacy, rescope the "8-stage closed loop" claim to the validated reality, reclassify vestigial test-only code as Fixture, relabel the KB **Dormant**, fix two documentary defects, and externalize the `produce/` doc-generator's dependency + import surface so the product neither imports nor (at runtime) installs it.

**Architecture:** All changes live **outside** `groundloop/core/` (FROZEN) and touch **no** atlas SQLite schema. The three fixed invariants (oracle-blindness, anti-leak, deterministic control flow) are untouched. Honesty about the mock `bind` is added at the run-record/reporting layer (mirroring the existing `change_sink=mock` manifest pattern), never in `core/workflow.py`. Produce externalization is done by moving its dependency block to an optional extra + locking the import boundary with a dependency-free CI test — **not** by rewriting produce (migration-verbatim contract) and **not** (in this plan) by physically relocating the 20k-LOC tree.

**Tech Stack:** Python 3.12, `uv`-managed `.venv`, `pytest`, `ruff` (line-length 110). Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`.

**Out of scope (deliberate — its own follow-up plan):** the *physical relocation* of `groundloop/engines/produce/` to a sibling tool package (repointing the `python -m groundloop.cli produce` subprocess entry + moving ~5 test files). Once Tasks 8–10 land, the product imports and installs zero produce; physically moving the tree adds only cognitive/clarity value at high churn, so it is separated per the writing-plans scope rule.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `groundloop/run/record.py` | Modify | Add honest `bind_kind` field to the persisted run-record |
| `groundloop/run/batch.py` | Modify | Derive `bind_kind` from the `ChangeSink` adapter identity |
| `groundloop/run/grade_run.py` | Modify | Surface the mock-bind from `manifest.json` into the scorecard |
| `groundloop/run/report.py` | Modify | Render the honest bind status in the markdown scorecard |
| `docs/charter.md` | Modify | Rescope §1 mission + §2 stage framing |
| `docs/capabilities.md` | Modify | Fix the `:72` citation, add Dormant subsection, reclassify Fixture, fix `0.68` defect |
| `groundloop/grade/grader.py` | Modify | Docstring note: test-only Fixture (hidden-oracle bridge) |
| `groundloop/kb/attribute.py` | Modify | Fix the rotting `primary` default metric |
| `pyproject.toml` | Modify | Move produce-only deps to `[project.optional-dependencies].produce` |
| `groundloop/cli/__init__.py` | Modify | Helpful error if `produce` extra not installed (the one lazy import) |
| `tests/run/test_record.py` | Modify | Assert the record marks bind as mock |
| `tests/run/test_batch.py` | Modify | Assert the batch persists `bind_kind="mock"` |
| `tests/run/test_report.py` | Modify/Create | Assert the scorecard renders the mock-bind line |
| `tests/kb/test_attribute_govern.py` | Modify | Adapt to the new default metric |
| `tests/architecture/test_import_boundary.py` | Create | Dependency-free CI guard: product must not import produce |
| `tests/build/test_atlas_build.py` | Modify | Assert `symbol_only=True` skips the produce stage |

---

## Part A — Honesty & governance (small, low-risk)

### Task 1: Honest `bind_kind` in the run-record

**Files:**
- Modify: `groundloop/run/record.py` (RunDoc ~line 43; `write` sig line 55-56 + blob line 67; `read` line 89)
- Modify: `groundloop/run/batch.py` (the `RunRecordIO.write(...)` call, lines 34-36)
- Test: `tests/run/test_record.py`, `tests/run/test_batch.py`

Rationale: `core/workflow.py:42` sets `RunRecord.bound=True` unconditionally (frozen, cannot change). We do not touch it; we add a sibling `bind_kind` field, derived from the `ChangeSink` adapter identity, so no reader mistakes `bound=True` for a real JIRA↔commit chain. Mirrors the existing `manifest.py` `change_sink="mock"` pattern.

- [ ] **Step 1: Write the failing test** — add to `tests/run/test_record.py` (reuse the existing `_rec()` builder in that file):

```python
def test_record_marks_bind_as_mock(tmp_path):
    import json
    mo = MaterializeOutcome(repo="engineering", path="/w/engineering", present=True, n_files=3)
    p = tmp_path / "runs" / "GEI-1.json"
    RunRecordIO.write(str(p), _rec(), materialize=mo, match_arm="component",
                      patch_applies=True, bind_kind="mock")
    doc = RunRecordIO.read(str(p))
    assert doc.bind_kind == "mock"
    raw = json.loads(p.read_text())
    assert raw["bind_kind"] == "mock"      # honest marker persisted in the bytes
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/run/test_record.py::test_record_marks_bind_as_mock -q`
Expected: FAIL — `TypeError: write() got an unexpected keyword argument 'bind_kind'`

- [ ] **Step 3: Implement in `groundloop/run/record.py`**

Add the field as the **last** RunDoc field (it has a default, so it must come after the no-default fields), after line 50 (`fixer: str`):

```python
    fixer: str
    bind_kind: str = "mock"
```

Add the `write` keyword (line 55-56 signature) and blob entry (after line 67 `"bound": rec.bound,`):

```python
    def write(path: str, rec: RunRecord, *, materialize: MaterializeOutcome, match_arm: str,
              patch_applies: bool, signals=None, cost=None, fixer: str = "", bind_kind: str = "mock") -> None:
        blob = {
            ...
            "bound": rec.bound,
            "bind_kind": bind_kind,
            ...
```

Add the `read` line (after line 89 `... bound=raw["bound"],`), using a back-compat default like the other `.get(...)` fields:

```python
            fixer=raw.get("fixer", ""), bind_kind=raw.get("bind_kind", "mock"))
```

- [ ] **Step 4: Run the record test — expect PASS**

Run: `.venv/bin/python -m pytest tests/run/test_record.py -q`
Expected: PASS

- [ ] **Step 5: Write the failing batch test** — add to `tests/run/test_batch.py` (reuse the existing `_dataset` fixture + `MockGerrit` harness in that file):

```python
def test_batch_persists_mock_bind_kind(tmp_path):
    import json
    from groundloop.adapters.mock.gerrit import MockGerrit
    ds = _dataset(tmp_path)                                  # existing helper in this file
    out = str(tmp_path / "out")
    run_dataset(ds, issues=_issues(ds), extractor=_Extractor(), estate=_Estate(),
                index=_StubIndex(), fixer=_Fixer(), changes=MockGerrit(str(tmp_path / "changes"), _issues(ds)),
                match_arm="component", out=out)
    rec = json.loads(Path(out, "runs", _CASE_ID + ".json").read_text())
    assert rec["bind_kind"] == "mock"
```

> Note: mirror the exact stub names/fixtures already defined in `tests/run/test_batch.py` (`_StubIndex`, `_dataset`, `_CASE_ID`, etc.); the names above are placeholders for whatever that file already provides — do NOT invent new stubs.

- [ ] **Step 6: Run it — expect FAIL** (`KeyError: 'bind_kind'`)

Run: `.venv/bin/python -m pytest tests/run/test_batch.py::test_batch_persists_mock_bind_kind -q`

- [ ] **Step 7: Implement in `groundloop/run/batch.py`** — derive and pass `bind_kind` at the `write` call (lines 34-36):

```python
        bind_kind = "mock" if type(changes).__name__ == "MockGerrit" else "live"
        RunRecordIO.write(f"{out}/runs/{case.case_id}.json", rec, materialize=outcome,
                          match_arm=match_arm, patch_applies=applies,
                          signals=sig, cost=cost, fixer=fixer_kind, bind_kind=bind_kind)
```

- [ ] **Step 8: Run the run-suite — expect PASS**

Run: `.venv/bin/python -m pytest tests/run/ -q`
Expected: PASS (existing tests unaffected — `bind_kind` has a default; `read` back-compats old JSON).

- [ ] **Step 9: Commit**

```bash
git add groundloop/run/record.py groundloop/run/batch.py tests/run/test_record.py tests/run/test_batch.py
git commit -m "feat(run): record honest bind_kind (mock) so bound=True is not misread as a real chain"
```

---

### Task 2: Surface the mock-bind in the scorecard

**Files:**
- Modify: `groundloop/run/grade_run.py` (`grade_run`, add a manifest read near line 214-215)
- Modify: `groundloop/run/report.py` (`render_run_markdown`, near line 26)
- Test: `tests/run/test_report.py`

Rationale: today `bound` is dark — `grade_run.py`/`report.py` never surface bind status, so a human reading the scorecard cannot see that the JIRA↔commit chain is mocked. Add one honest line sourced from `manifest.json`'s existing `change_sink` field.

- [ ] **Step 1: Write the failing test** — `tests/run/test_report.py`:

```python
from groundloop.run.report import render_run_markdown

def _min_card():
    return {"n_cases": 1, "bind": "mock",
            "overall": {"match": {"n": 1, "recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0},
                        "localize": {"as_run": {"file@1": 0.0}, "isolated": None},
                        "fix": {"n_gradeable": 0, "n_ungradeable_no_source": 1,
                                "resolved_rate_strict": {"value": None, "n": 0}}},
            "cases": []}

def test_scorecard_shows_mock_bind():
    md = render_run_markdown(_min_card())
    assert "bind: mock" in md and "not a real Gerrit change" in md
```

- [ ] **Step 2: Run it — expect FAIL** (`assert ... in md`)

Run: `.venv/bin/python -m pytest tests/run/test_report.py::test_scorecard_shows_mock_bind -q`

- [ ] **Step 3: Implement `render_run_markdown`** — in `groundloop/run/report.py`, after the `fix` block (after line 32), add:

```python
    if card.get("bind"):
        note = "" if card["bind"] != "mock" else " (mocked — not a real Gerrit change)"
        lines.append(f"- bind: {card['bind']}{note}")
```

- [ ] **Step 4: Populate `card["bind"]` in `grade_run.py`** — in `grade_run`, before `return card` (line 222), read the manifest's existing honest field:

```python
    mpath = Path(runs_dir) / "manifest.json"
    if mpath.exists():
        try:
            card["bind"] = json.loads(mpath.read_text()).get("change_sink", "mock")
        except (json.JSONDecodeError, OSError):
            card["bind"] = "mock"
    return card
```

- [ ] **Step 5: Run report + grade_run tests — expect PASS**

Run: `.venv/bin/python -m pytest tests/run/test_report.py tests/run/test_grade_run_core.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add groundloop/run/grade_run.py groundloop/run/report.py tests/run/test_report.py
git commit -m "feat(run): scorecard surfaces bind=mock (change_sink) so mocked bind is visible"
```

---

### Task 3: Rescope the "8-stage closed loop" claim + fix the `:72` citation

**Files:**
- Modify: `docs/charter.md` (§1 mission lines 30-38; §2 lines 57-58)
- Modify: `docs/capabilities.md` (§1 lines 19-20; the Core-row citation line 72)

Rationale: documentary only. Make the headline claims consistent with the caveats already buried at `charter.md:238` and `capabilities.md:251-253`. No code, no test — verify by re-reading.

- [ ] **Step 1: Fix the false-efficacy citation** in `docs/capabilities.md:72`. Replace:

```
| `gloop run` — the frozen 8-stage `run_ticket` loop (`core/workflow.py`) | 2026-07-11 GEI run executed all 8 stages to a bound change on 10/10 cases, 0 crashes `[production]`. |
```

with:

```
| `gloop run` — the frozen 8-stage `run_ticket` loop (`core/workflow.py`) | 2026-07-11 GEI run drove all 8 stages over 10/10 cases with 0 crashes `[production]` — a **completion/liveness** read, not an efficacy one. `submit`/`bind` are `MockGerrit` and `bound` is a hardcoded constant (`core/workflow.py:42`), so "bound" reflects a **mock** bind (`change_sink=mock`), not a real JIRA↔commit chain. Per-stage efficacy is graded separately (match recall@1, localize file@k, fix resolved_rate). |
```

- [ ] **Step 2: Rescope the charter §1 mission** — `docs/charter.md:30-31`. After the "closed loop" mission sentence, add a scoping note (keep the aspiration, label the reality):

```
**Delivered vs aspirational (2026-07-18 rescope).** What is `[production]`-validated today is **Stage-1
match** (recall@1 0.50) **+ recall-localize** (7/10 file@5). **Fix** is real but `[production]`-unproven;
**submit/bind** are mocked at both ends (`bound` is a hardcoded constant). The closed loop is the
*mission*, not yet a *delivered* capability — see [capabilities.md](capabilities.md) §3.
```

- [ ] **Step 3: Rescope capabilities §1** — `docs/capabilities.md:19-20`, append to the "8-stage `run_ticket` loop" sentence:

```
(Note: of these 8, `match` + `localize` are `[production]`-validated, `fix` is real-but-unproven, and
`submit`/`bind` are mocked — the loop *runs* all 8, but only match/localize carry a `[production]` efficacy read.)
```

- [ ] **Step 4: Verify** — no test; re-read the three edits and confirm the headline no longer asserts a *delivered* traceable JIRA↔commit chain.

Run: `grep -n "completion/liveness\|Delivered vs aspirational\|real-but-unproven" docs/charter.md docs/capabilities.md`
Expected: three matches (one per edit).

- [ ] **Step 5: Commit**

```bash
git add docs/charter.md docs/capabilities.md
git commit -m "docs: rescope 8-stage 'closed loop' to validated match+localize; fix bound-as-efficacy citation"
```

---

### Task 4: Reclassify the hidden-oracle bridge as test-only Fixture

**Files:**
- Modify: `docs/capabilities.md` (Fixture list, lines 210-211)
- Modify: `groundloop/grade/grader.py` (module docstring)

Rationale: `grade/grader.py::grade()` + `core.types.Oracle`/`Scores` + `eval.dataset.load_oracle` are called **only by tests** (verified: 3 test importers; the real grade path uses `EvalOracle`). `core/` is frozen so `Oracle`/`Scores` stay defined — this is a **documentary** reclassification (option a), lowest risk. (Physically moving `grade()` into a test helper is a sanctioned but deferred follow-up.)

- [ ] **Step 1: Extend the Fixture list** — `docs/capabilities.md:210-211`. Replace `legacy grade().` with:

```
legacy `grade()` **+ the hidden-oracle bridge it uses** — `core.types.Oracle`/`Scores` and
`eval.dataset.load_oracle` (test-only; the real grade path uses `eval.dataset.EvalOracle`, never core `Oracle`).
```

- [ ] **Step 2: Add a docstring note** to `groundloop/grade/grader.py` (top of file, it currently starts with `from __future__`):

```python
"""TEST-ONLY FIXTURE (hidden-oracle bridge). `grade(record, oracle) -> Scores` and the core `Oracle`/`Scores`
types are called ONLY by tests; the real `gloop grade-run`/eval path uses `eval.dataset.EvalOracle` +
`run/grade_run.py`. Kept because `core/` is frozen (cannot delete `Oracle`/`Scores`). Never wire into the loop."""
from __future__ import annotations
```

- [ ] **Step 3: Verify the suite still green** (no code semantics changed):

Run: `.venv/bin/python -m pytest tests/test_grader.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docs/capabilities.md groundloop/grade/grader.py
git commit -m "docs+comment: reclassify grade()/Oracle/Scores as the test-only hidden-oracle bridge (Fixture)"
```

---

### Task 5: Relabel the KB implementation **Dormant**

**Files:**
- Modify: `docs/capabilities.md` (§2 states table line 43; Candidate header line 118; KB block lines 189-200; Archived back-ref lines 217-221)

Rationale: the current KB implementation is 0-signal, off-path, and untestable on the dev box — but the *null was never validly measured* (so not Archived) and it is *not promising-but-unvalidated* (so "Candidate" launders it). Introduce a **Dormant** state (off the promote→archive axis, like Dev-Labs Infra/Fixture) meaning "concept valuable, current implementation weak, blocked on redesign + real data; kept in-tree." Documentary only — `fixeval/runner.py:17` hard-imports `kb/`, so the code stays.

- [ ] **Step 1: Define the Dormant state** — add a row to the §2 states table after line 43 (`Archived`):

```
| **Dormant** | Concept judged valuable, but the **current implementation** is weak / 0-signal — *not* a validly-measured null (so not Archived) and *not* promising-but-unvalidated (so not Candidate). Blocked on a redesign + real data. Kept in-tree. | No. |
```

- [ ] **Step 2: Move the KB block out of Candidate** — cut lines 189-200 (the `**Dev-experience KB** ...` block) from the `### Candidate` section and paste under a new subsection placed after the Candidate section (before `### Dev-Labs Infra`):

```
### Dormant — valuable concept, weak current implementation (1)
**Dev-experience KB** (raw Skills → knowledge distill) — **Dormant** (2026-07-18 first-principles review).
The *concept* is the productization of charter §7's strongest lever (cross-repo grounding, +40–60pp); the
*current implementation* has produced 0 positive signal (0/60 validated, 0.0 resolved in every fair arm),
sits off the `run_ticket` path, and is untestable on the dev box (synth floors resolution at 0; the OSS
fleet has ~7–15 crash-with-fix cases). It is neither a valid null (Archived) nor promising-but-unvalidated
(Candidate). **Blocked on a 3-axis redesign** — injection mechanism (retriever, not firehose: raw Skills in
the localize query cost Δ−0.10; wholesale into the planner hurt 0.51→0.22) · richer Knowledge representation
(worked crash-RCA playbooks / cross-repo helper pointers, not atomic claims) · a loop-outcome learning loop —
plus real AAOS crash+fix data. Kept in-tree (`fixeval/runner.py:17` hard-imports `kb/`; the green in-tree
tests are its readiness). Redesign: `docs/superpowers/specs/2026-07-18-first-principles-review.md` §7. Its
A/B machinery (`kb-ab`/`kb-extract`/`kb-attribute`/placebo) is the eval infra for that test.
```

- [ ] **Step 3: Decrement the Candidate count** — `docs/capabilities.md:118`, change `(9)` to `(8)`.

- [ ] **Step 4: Update the Archived back-ref** — `docs/capabilities.md:217-221`, change "reclassified Archived → Candidate (2026-07-13)" to "reclassified Archived → Candidate (2026-07-13), then **Dormant** (2026-07-18)".

- [ ] **Step 5: Verify**

Run: `grep -n "Dormant" docs/capabilities.md`
Expected: ≥3 matches (states table, subsection header, KB block, archived back-ref).

- [ ] **Step 6: Commit**

```bash
git add docs/capabilities.md
git commit -m "docs(capabilities): relabel the KB implementation Dormant (concept valuable, impl weak) + define the Dormant state"
```

---

### Task 6: Fix the rotting `attribute.py` default metric

**Files:**
- Modify: `groundloop/kb/attribute.py:146`
- Test: `tests/kb/test_attribute_govern.py`

Rationale: `attribute_and_govern(..., primary="plan_target_recall@1", ...)` governs the KB LOFO gate on the exact metric this project discredited (`capabilities.md:190`, `:218`). Every other governance consumer (`run/promotion.py`, `run/compare.py`, `fixeval/compare.py`, `cli`) keys on `resolved_rate_strict`. Align the default.

- [ ] **Step 1: Update the covering test** — `tests/kb/test_attribute_govern.py`, the `run_card_fn` in `test_govern_promotes_a_load_bearing_item` (lines 58-61) currently varies only `ptr` (`plan_target_recall@1`) while `rss` (`resolved_rate_strict`) is fixed. Make it vary `rss` so the new default has a signal to promote on:

```python
    def run_card_fn(ids):                       # c1 lifts resolved_rate_strict; its placebo does not
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.5, rss=0.8 if good else 0.4)      # ptr flat; rss is the load-bearing metric now
```

- [ ] **Step 2: Run it to confirm it FAILS under the current default** (proves the test now depends on `rss`):

Run: `.venv/bin/python -m pytest tests/kb/test_attribute_govern.py::test_govern_promotes_a_load_bearing_item -q`
Expected: FAIL — the LOFO Δ on `plan_target_recall@1` (flat 0.5) is 0, so `c1` is not promoted.

- [ ] **Step 3: Flip the default** — `groundloop/kb/attribute.py:146`:

```python
                         primary: str = "resolved_rate_strict", cost_budget: float | None = None,
```

- [ ] **Step 4: Run the KB attribute tests — expect PASS**

Run: `.venv/bin/python -m pytest tests/kb/test_attribute_govern.py tests/kb/test_lofo_knowledge.py tests/kb/test_cli_kb_attribute.py -q`
Expected: PASS. If any legacy test still assumes the old default, pass `primary="plan_target_recall@1"` explicitly in that specific test (do not revert the default).

- [ ] **Step 5: Commit**

```bash
git add groundloop/kb/attribute.py tests/kb/test_attribute_govern.py
git commit -m "fix(kb): govern LOFO gate on resolved_rate_strict (the discredited plan_target_recall default was rotting)"
```

---

### Task 7: Fix the `0.68 [proxy]` doc-defect

**Files:**
- Modify: `docs/capabilities.md:160`

Rationale: `capabilities.md:160` cites `functional/dispatch arm (0.68 [proxy])` as a favorable Candidate signal — but `environments.md:59-65` uses that exact `0.68` as *the* canonical "the proxy flatters" cautionary tale (0.68 `[proxy]` → 0.10 `[production]`). Same number, opposite framing. Documentary only.

- [ ] **Step 1: Annotate the citation** — `docs/capabilities.md:160`, replace `functional/dispatch arm (0.68 `[proxy]`)` with:

```
functional/dispatch arm (0.68 `[proxy]` → **0.10 `[production]`** — the canonical "proxy flatters" collapse; see [environments.md](environments.md) §"the proxy is optimistic")
```

- [ ] **Step 2: Verify**

Run: `grep -n "0.10 .\[production\]. — the canonical" docs/capabilities.md`
Expected: 1 match.

- [ ] **Step 3: Commit**

```bash
git add docs/capabilities.md
git commit -m "docs(capabilities): annotate the 0.68 [proxy] functional citation with its [production] collapse (proxy-lies consistency)"
```

---

## Part B — Externalize the produce dependency + import surface

### Task 8: Move produce-only dependencies to an optional `produce` extra

**Files:**
- Modify: `pyproject.toml` (lines 9-47)
- Modify: `groundloop/cli/__init__.py` (the lazy import at line 112, inside `_run_produce`)
- Modify: `CLAUDE.md` + `docs/build-setup.md` (the dev-sync command)

Rationale: `pyproject.toml:10-43` is entirely produce-only (audited: 0 usages outside `engines/produce/`). Moving it to an extra means a **runtime** install (`pip install groundloop`) skips the whole heavy stack (click, openai, litellm, pydantic-ai, fastapi, tree-sitter×10, …); build/dev machines install `groundloop[produce]`. `httpx`/`mcp`/`codebase-memory-mcp` stay in base (real runtime deps).

- [ ] **Step 1: Edit `pyproject.toml`** — remove lines 9-43 (the `# produce ... deps` comment through `coding-agent-wrapper`) from `[project.dependencies]` so base is just:

```toml
dependencies = [
    "httpx>=0.27",
    "mcp",
    "codebase-memory-mcp==0.8.1",
]
```

and add a `produce` extra (paste the removed lines verbatim) under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff"]
produce = [
    "click>=8.1.0",
    "keyring>=24.0.0",
    "GitPython>=3.1.40",
    "Jinja2>=3.1.6",
    "tree-sitter>=0.23.2",
    "tree-sitter-language-pack>=0.8.0",
    "tree-sitter-python>=0.23.6",
    "tree-sitter-java>=0.23.5",
    "tree-sitter-javascript>=0.21.4",
    "tree-sitter-typescript>=0.21.2",
    "tree-sitter-c>=0.21.4",
    "tree-sitter-cpp>=0.23.4",
    "tree-sitter-c-sharp>=0.23.1",
    "tree-sitter-php>=0.23.0",
    "tree-sitter-kotlin>=1.1.0",
    "openai>=1.107.0",
    "litellm>=1.77.0",
    "pydantic>=2.11.7",
    "pydantic-settings>=2.10.1",
    "pydantic-ai>=1.0.6",
    "requests>=2.32.4",
    "python-dotenv>=1.1.1",
    "rich>=14.1.0",
    "networkx>=3.5",
    "psutil>=7.0.0",
    "PyYAML>=6.0.2",
    "mermaid-parser-py>=0.0.2",
    "mermaid-py>=0.8.0",
    "fastapi>=0.116.0",
    "uvicorn>=0.35.0",
    "python-multipart>=0.0.20",
    "colorama>=0.4.6",
    "logfire>=4.1.0",
    "coding-agent-wrapper>=0.1.2",
]
```

- [ ] **Step 2: Make the lazy produce import fail helpfully** — `groundloop/cli/__init__.py`, wrap the import at line 112 inside `_run_produce`:

```python
    try:
        from groundloop.engines.produce.cli.adapters.doc_generator import CLIDocumentationGenerator
    except ImportError as e:
        raise SystemExit("gloop produce requires the produce extra — install it with "
                         "`uv sync --extra produce` (or `pip install groundloop[produce]`).") from e
```

- [ ] **Step 3: Re-sync with the extra so the suite has produce deps**

Run: `uv sync --extra dev --extra produce`
Expected: resolves and installs the produce stack into `.venv`.

- [ ] **Step 4: Run the full suite — expect green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (produce tests still have their deps via the `produce` extra; `pytest.importorskip("pydantic_ai")` in `tests/engines/test_doc_generator_navigate.py` already guards the produce-less case).

- [ ] **Step 5: Update the dev-setup docs** — in `CLAUDE.md` (the "Setup:" line) and `docs/build-setup.md`, change `uv sync --extra dev` to `uv sync --extra dev --extra produce` and note: "runtime installs omit `--extra produce`; the product imports zero produce."

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml groundloop/cli/__init__.py CLAUDE.md docs/build-setup.md
git commit -m "build: move produce-only deps to a [produce] extra so runtime installs skip the CodeWiki stack"
```

---

### Task 9: Lock the import boundary — product must not import produce

**Files:**
- Create: `tests/architecture/test_import_boundary.py`

Rationale: the product runtime imports 0 lines of produce today (only a lazy, function-local import inside `_run_produce`). Make that a CI-enforced invariant with a dependency-free AST scan of module-level imports (a function-local import is invisible to a module-level scan, so the one allowed edge passes naturally).

- [ ] **Step 1: Write the failing test** — `tests/architecture/test_import_boundary.py`:

```python
"""CI guard: the product runtime must not import the produce doc-generator at module level.
Produce is a build-time-only tool (reached via the lazy import inside cli._run_produce)."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "groundloop"
PRODUCT_DIRS = ["core", "adapters", "domains", "run"]
FORBIDDEN_PREFIX = "groundloop.engines.produce"


def _module_level_imports(py: pathlib.Path):
    tree = ast.parse(py.read_text(), filename=str(py))
    for node in tree.body:                                    # top-level only — function-local imports excluded
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def _product_files():
    files = [ROOT / "cli" / "__init__.py"]
    for d in PRODUCT_DIRS:
        files += (ROOT / d).rglob("*.py")
    return files


def test_product_does_not_module_import_produce():
    offenders = []
    for py in _product_files():
        for mod in _module_level_imports(py):
            if mod.startswith(FORBIDDEN_PREFIX):
                offenders.append(f"{py.relative_to(ROOT.parent)} -> {mod}")
    assert not offenders, "product module-level imports of produce (must be lazy/build-only):\n" + "\n".join(offenders)
```

- [ ] **Step 2: Run it — expect PASS today** (the boundary already holds; this locks it):

Run: `.venv/bin/python -m pytest tests/architecture/test_import_boundary.py -q`
Expected: PASS (0 offenders — the only edge is the lazy import inside `_run_produce`).

- [ ] **Step 3: Sanity-check the guard actually catches a violation** — temporarily add `from groundloop.engines.produce.cli.adapters.doc_generator import CLIDocumentationGenerator` at the **top** of `groundloop/run/report.py`, run the test, confirm it FAILS, then remove the line.

Run: `.venv/bin/python -m pytest tests/architecture/test_import_boundary.py -q`
Expected: FAIL listing `groundloop/run/report.py -> groundloop.engines.produce...` (then revert).

- [ ] **Step 4: Commit**

```bash
git add tests/architecture/test_import_boundary.py
git commit -m "test(arch): CI guard — product runtime must not module-import the produce doc-generator"
```

---

### Task 10: Explicit symbol-only build path (never require produce)

**Files:**
- Modify: `groundloop/build/atlas_build.py` (`build_atlas`, lines 49-82)
- Test: `tests/build/test_atlas_build.py`

Rationale: `build_atlas` always calls `produce_fn` (line 68). Add a `symbol_only` switch that skips the produce stage entirely and relies on `wiki_stub.ensure_indexable_wiki` (already fired by `gloop index`) so a build can produce a valid symbol-only atlas without produce installed.

- [ ] **Step 1: Write the failing test** — add to `tests/build/test_atlas_build.py` (mirror the existing injectable-stage pattern):

```python
def test_symbol_only_skips_produce(tmp_path):
    order = []
    def fake_clone(fleet, *, jobs): order.append("clone"); return {}
    def fake_produce(entries, **kw): order.append("produce"); return {}
    def fake_index(reg): order.append("index"); return 0
    def fake_doctor(): order.append("doctor"); return 0
    report = build_atlas(_fake_registry(tmp_path), symbol_only=True,
                         clone_fn=fake_clone, produce_fn=fake_produce,
                         index_fn=fake_index, doctor_fn=fake_doctor)
    assert "produce" not in order          # produce stage skipped
    assert order == ["clone", "index", "doctor"]
    assert report.ok is True
```

> Reuse the existing registry-fixture helper in `tests/build/test_atlas_build.py` (shown as `_fake_registry` here — use whatever that file already defines, e.g. `_fake_toml`).

- [ ] **Step 2: Run it — expect FAIL** (`build_atlas() got an unexpected keyword argument 'symbol_only'`)

Run: `.venv/bin/python -m pytest tests/build/test_atlas_build.py::test_symbol_only_skips_produce -q`

- [ ] **Step 3: Implement in `groundloop/build/atlas_build.py`** — add the parameter (after `force` on line 54) and guard the produce stage (lines 68-71):

```python
    force: bool = False,
    symbol_only: bool = False,
```

```python
    produce_res: dict = {}
    if not symbol_only:
        produce_res = produce_fn(entries, jobs=jobs, concurrency=concurrency, force=force)
        if any(getattr(r, "status", "") == "failed" for r in produce_res.values()):
            return BuildReport(ok=False, failed_stage="produce",
                               clone=clone_res, produce=produce_res)
```

- [ ] **Step 4: Run the build tests — expect PASS**

Run: `.venv/bin/python -m pytest tests/build/ -q`
Expected: PASS (default `symbol_only=False` keeps existing behavior).

- [ ] **Step 5: Wire a `--symbol-only` CLI flag** (optional but recommended) — in `groundloop/cli/__init__.py` `_run_build_atlas`, add an argparse `--symbol-only` flag and pass `symbol_only=args.symbol_only` to `build_atlas`. Mirror the existing flag-wiring in that handler.

- [ ] **Step 6: Full suite + lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: PASS, clean.

- [ ] **Step 7: Commit**

```bash
git add groundloop/build/atlas_build.py groundloop/cli/__init__.py tests/build/test_atlas_build.py
git commit -m "feat(build): symbol_only build path skips produce (produce becomes optional at build time)"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-07-18-first-principles-review.md` §9 items 1–4):
- #1 externalize produce → Tasks 8 (deps extra), 9 (import boundary), 10 (symbol-only build). *Physical tree relocation deliberately deferred to a follow-up plan — noted in the header.*
- #2 rescope + `bound=True` → Tasks 1 (record `bind_kind`), 2 (scorecard surfacing), 3 (docs rescope + `:72` citation).
- #3 reclassify grade()/Oracle/Scores as Fixture → Task 4.
- #4 KB Dormant + `0.68` doc-defect → Tasks 5, 7. The `attribute.py:146` rotting default → Task 6.

**Placeholder scan:** every code step shows real code; doc steps show exact before/after text; each has a concrete verify command. Test helpers that already exist (`_rec`, `_dataset`, `_fake_toml`, `_StubIndex`) are referenced by name with an explicit "use what the file already defines" caveat rather than re-invented (re-inventing them would risk constructor drift on frozen `core` types).

**Type/consistency:** `bind_kind` is added consistently across `RunDoc` field, `write` kwarg + blob key, and `read` `.get` default (all string `"mock"`); the scorecard reads `card["bind"]` from the manifest `change_sink` (existing honest field), not from the per-record field, keeping one source of truth for the rendered line. `symbol_only` default `False` preserves all existing `build_atlas` callers.

**Risk notes for the executor:**
- Task 8 changes the dev-sync command (`--extra produce`); run Step 3 before Step 4 or the produce tests will fail to import. This is the highest-blast-radius task — commit it alone.
- Task 6 will break `test_govern_promotes_a_load_bearing_item` until Step 1's test edit lands; do Steps 1→3 together.
- Do Part A before Part B (Part A is docs/tiny-code and de-risks the review's honesty claims first).

---

**Physical-relocation follow-up (separate plan):** once Tasks 8–10 land, author `docs/superpowers/plans/2026-07-18-produce-physical-relocation.md` to move `groundloop/engines/produce/` → a sibling tool package, repoint `build/produce_fleet.py`'s subprocess entry + `_run_produce` + the ~5 produce test files (`tests/build/test_cli_produce_concurrency.py`, `tests/engines/test_produce_smoke.py`, `tests/engines/test_doc_generator_navigate.py`). Migration-verbatim: import-rewire only, no produce rewrite.
