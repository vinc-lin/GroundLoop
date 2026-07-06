# Plan-Format Fix Stage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the fix stage into a two-phase plan-then-act engine — emit a grounded, gradeable
`RepairPlan`, gate it in-world (re-plan → abstain), then execute it into a patch — behind a measured
`--fixer plan` arm, and harden the `resolved_rate` proxy so the arm is measured on honest ground. The
same grounded substrate is then used to **validate the KB's raw and distilled knowledge** as measured
`--skills` arms (a new `accept_grounded` two-sided gate), replacing the game-able `resolved_rate` the
current KB A/B keys on.

**Architecture:** New `PlanningFixEngine` adapter satisfies the frozen `FixEngine.propose` and adds a
plan-aware path the (non-frozen) eval runner uses to capture the plan. A pure `fixeval/plan.py` holds the
`RepairPlan` type, the tolerant parser, and the oracle-blind gate. New grader metrics
(`plan_groundedness`, `plan_correctness`) and a plan archive are added to `fixeval/`. `core/` and the
atlas schema are untouched.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests: `pytest`. Lint: `ruff` (line length 110). No new deps.

**Design spec:** `docs/superpowers/specs/2026-07-07-plan-format-fix-stage-design.md` (read for rationale;
decisions D1–D5 and the locked defaults `max_replan=1`, `context_window=120`, hardened-metric-as-variant
are already settled — do not re-litigate).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `groundloop/fixeval/patch.py` | diff parsing + apply-check | **Modify** — add `code_added_lines`, `references_api_code` |
| `groundloop/fixeval/scorecard.py` | offline fix grade | **Modify** — `resolved_rate_strict`, plan metrics |
| `groundloop/fixeval/plan.py` | `RepairPlan` + parser + in-world gate | **Create** |
| `groundloop/adapters/fix/planning.py` | `PlanningFixEngine` (two-phase) | **Create** |
| `groundloop/fixeval/runner.py` | whole-loop runner + `FixRecord` | **Modify** — carry plan, `_do_propose` |
| `groundloop/fixeval/archive.py` | persist plan + outcome | **Create** |
| `groundloop/fixeval/report.py` | scorecard markdown | **Modify** — surface plan metrics |
| `groundloop/fixeval/compare.py` | Δ + accept gate | **Modify** — grounded metrics + `accept_grounded` |
| `groundloop/cli/__init__.py` | composition root | **Modify** — `--fixer`, `--max-replan`, `--skills distilled`, build engine, archive |
| `tests/fixeval/test_patch_hardened.py` … | tests | **Create** (per task) |

Guardrails (from CLAUDE.md — hold at every step): never edit `groundloop/core/`; never alter the atlas
SQLite schema; swap behavior only at the composition root; keep the loop oracle-blind (the gate uses only
in-world signals, `plan_correctness` is offline); commit only when the suite is green + ruff clean; end
commit messages with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

## Phase 0 — Harden the `resolved_rate` proxy

### Task 0.1: Comment-aware API reference check

**Files:**
- Modify: `groundloop/fixeval/patch.py` (after `references_api`, ~line 47)
- Test: `tests/fixeval/test_patch_hardened.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_patch_hardened.py
from groundloop.fixeval.patch import references_api, references_api_code


def test_code_api_excludes_comment_namedrop():
    diff = "--- a/f.java\n+++ b/f.java\n@@ -1 +1,2 @@\n+    // remember to call startForeground()\n+    int x = 1;\n"
    assert references_api(diff, "startForeground") is True        # old proxy: comment name-drop counts
    assert references_api_code(diff, "startForeground") is False  # hardened: comments excluded


def test_code_api_matches_real_call():
    diff = "--- a/f.java\n+++ b/f.java\n@@ -1 +1,2 @@\n+    startForeground(1, note);\n"
    assert references_api_code(diff, "startForeground") is True


def test_code_api_ignores_blank_and_star_continuation():
    diff = "--- a/f.java\n+++ b/f.java\n@@ -1 +1,3 @@\n+\n+     * javadoc mentions foo\n+    int y = 0;\n"
    assert references_api_code(diff, "foo") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_patch_hardened.py -q`
Expected: FAIL — `ImportError: cannot import name 'references_api_code'`.

- [ ] **Step 3: Write minimal implementation**

```python
# groundloop/fixeval/patch.py  — add after references_api (keep references_api unchanged)
_COMMENT_PREFIXES = ("//", "#", "*", "/*", "*/")


def _is_comment_or_blank(content: str) -> bool:
    t = content.strip()
    return t == "" or t.startswith(_COMMENT_PREFIXES)


def code_added_lines(diff: str) -> list[str]:
    """Added ('+') line contents excluding the +++ header AND comment/blank lines (a heuristic:
    single-line // # , block-comment * / */ continuations). Used by the hardened resolution check."""
    return [ln for ln in added_lines(diff) if not _is_comment_or_blank(ln)]


def references_api_code(diff: str, api: str) -> bool:
    """Whole-word `\\bapi\\b` over added CODE lines only (comments/blanks excluded)."""
    pat = re.compile(rf"\b{re.escape(api)}\b")
    return any(pat.search(ln) for ln in code_added_lines(diff))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_patch_hardened.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/patch.py tests/fixeval/test_patch_hardened.py
git commit -m "feat(fixeval): comment-aware references_api_code for hardened resolution

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 0.2: `resolved_rate_strict` bound to the patch's own edits

**Files:**
- Modify: `groundloop/fixeval/scorecard.py` (import line 9; `grade_fix_all` body ~line 36-72)
- Test: `tests/fixeval/test_scorecard_hardened.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_scorecard_hardened.py
from dataclasses import dataclass
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all


@dataclass
class O:  # minimal oracle stand-in
    expected_files: list
    required_apis: list
    is_answerable: bool = True


def _rec(**kw):
    base = dict(case_id="c1", arm="a", predicted_repo="r", locations=["src/Right.java"],
                patch_diff="", patch_files=[], patch_emitted=True, patch_applies=True,
                abstained=False, abstain_reason=None, refine_iters=0, cost_usd=0.0)
    base.update(kw)
    return FixRecord(**base)


def test_strict_rejects_wrong_file_edit():
    # localize surfaced the right file, but the patch edits the WRONG file
    diff = "--- a/src/Wrong.java\n+++ b/src/Wrong.java\n@@ -1 +1,2 @@\n+    foo();\n"
    rec = _rec(patch_diff=diff, patch_files=["src/Wrong.java"])
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["foo"])}
    card = grade_fix_all([rec], oracle_by_case=oracle)["arms"]["a"]
    assert card["resolved_rate"]["value"] == 1.0          # old proxy: file_recall over locations passes
    assert card["resolved_rate_strict"]["value"] == 0.0   # hardened: patch touched the wrong file


def test_strict_rejects_comment_only_api():
    diff = "--- a/src/Right.java\n+++ b/src/Right.java\n@@ -1 +1,2 @@\n+    // foo() should be called\n+    int x=1;\n"
    rec = _rec(patch_diff=diff, patch_files=["src/Right.java"])
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["foo"])}
    card = grade_fix_all([rec], oracle_by_case=oracle)["arms"]["a"]
    assert card["resolved_rate_strict"]["value"] == 0.0   # api only name-dropped in a comment
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_scorecard_hardened.py -q`
Expected: FAIL — `KeyError: 'resolved_rate_strict'`.

- [ ] **Step 3: Write minimal implementation**

In `groundloop/fixeval/scorecard.py`, extend the import and add the strict predicate + metric.

```python
# line 9 — extend the import
from groundloop.fixeval.patch import norm_path, references_api, references_api_code, touched_files


# add near _file_recall (module level)
def _resolved_strict(rec, oracle) -> bool:
    """Hardened resolution: the PATCH's own touched files intersect expected_files (not localize's
    locations), and every required_api appears on an added CODE line (comments excluded)."""
    tf = {norm_path(x) for x in touched_files(rec.patch_diff)}
    ef = {norm_path(e) for e in oracle.expected_files}
    return bool(rec.patch_applies and (tf & ef)
                and all(references_api_code(rec.patch_diff, a) for a in oracle.required_apis))
```

Inside `grade_fix_all`, after the `solved = [...]` list (line 40), add:

```python
        solved_strict = [r for r, o in grd if _resolved_strict(r, o)]
```

And in the `arms[arm] = {...}` dict, after the `"resolved_rate": ...` entry (line 63), add:

```python
            "resolved_rate_strict": (_wrap(len(solved_strict) / len(grd), len(grd))
                                     if grd else {"value": None, "n": 0}),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_scorecard_hardened.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full fix suite + lint**

Run: `.venv/bin/python -m pytest tests/fixeval -q && .venv/bin/ruff check groundloop tests`
Expected: PASS, no lint errors. (Confirms the extra metric key did not break existing scorecard tests.)

- [ ] **Step 6: Commit**

```bash
git add groundloop/fixeval/scorecard.py tests/fixeval/test_scorecard_hardened.py
git commit -m "feat(fixeval): resolved_rate_strict — bind resolution to the patch's own edits

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1 — The PlanningFixEngine + `--fixer plan` arm

### Task 1.1: `RepairPlan` type + tolerant parser

**Files:**
- Create: `groundloop/fixeval/plan.py`
- Test: `tests/fixeval/test_plan.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_plan.py
from groundloop.fixeval.plan import RepairPlan, PlanTarget, parse_plan, plan_to_dict


def test_parse_fenced_json():
    text = ('```json\n{"root_cause":"npe after onDestroyView","targets":[{"file":"a/F.java",'
            '"symbol":"onBind","why":"null deref"}],"required_apis":["isAdded"],'
            '"strategy":"guard","citations":["a/F.java"],"confidence":0.7}\n```')
    p = parse_plan(text)
    assert isinstance(p, RepairPlan)
    assert p.targets == (PlanTarget(file="a/F.java", why="null deref", symbol="onBind"),)
    assert p.required_apis == ("isAdded",)
    assert p.abstain is False


def test_parse_bare_json_and_string_targets():
    p = parse_plan('prose... {"root_cause":"x","targets":["src/A.java"],"strategy":"y"} trailing')
    assert p.targets == (PlanTarget(file="src/A.java"),)


def test_parse_abstain_and_junk():
    assert parse_plan('{"abstain":true,"root_cause":"","targets":[],"strategy":""}').abstain is True
    assert parse_plan("not json at all") is None
    assert parse_plan("") is None


def test_round_trip_dict():
    p = parse_plan('{"root_cause":"x","targets":[{"file":"A"}],"strategy":"s","required_apis":["k"]}')
    d = plan_to_dict(p)
    assert d["targets"] == [{"file": "A", "symbol": None, "why": ""}]
    assert d["required_apis"] == ["k"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_plan.py -q`
Expected: FAIL — `ModuleNotFoundError: groundloop.fixeval.plan`.

- [ ] **Step 3: Write minimal implementation**

```python
# groundloop/fixeval/plan.py
"""RepairPlan — the grounded, structured artifact the PlanningFixEngine emits between localize and
patch. Pure / oracle-free. See docs/superpowers/specs/2026-07-07-plan-format-fix-stage-design.md."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanTarget:
    file: str
    why: str = ""
    symbol: str | None = None


@dataclass(frozen=True)
class RepairPlan:
    root_cause: str
    targets: tuple[PlanTarget, ...]
    required_apis: tuple[str, ...] = ()
    strategy: str = ""
    citations: tuple[str, ...] = ()
    risks: str = ""
    confidence: float = 0.0
    abstain: bool = False


_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def parse_plan(text: str) -> RepairPlan | None:
    """Tolerant decode of a model plan (```json fenced or a bare {...} span). Returns None on any
    failure — the caller treats None as a gate failure (re-plan, then abstain). Never raises."""
    if not text or not text.strip():
        return None
    m = _JSON_FENCE.search(text)
    raw = m.group(1) if m else text
    if not m:
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1 or j < i:
            return None
        raw = raw[i:j + 1]
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    targets: list[PlanTarget] = []
    for t in d.get("targets", []) or []:
        if isinstance(t, dict) and t.get("file"):
            targets.append(PlanTarget(file=str(t["file"]), why=str(t.get("why", "")),
                                      symbol=(str(t["symbol"]) if t.get("symbol") else None)))
        elif isinstance(t, str) and t.strip():
            targets.append(PlanTarget(file=t.strip()))
    return RepairPlan(
        root_cause=str(d.get("root_cause", "")).strip(),
        targets=tuple(targets),
        required_apis=tuple(str(a) for a in (d.get("required_apis", []) or []) if str(a).strip()),
        strategy=str(d.get("strategy", "")).strip(),
        citations=tuple(str(c) for c in (d.get("citations", []) or []) if str(c).strip()),
        risks=str(d.get("risks", "")).strip(),
        confidence=float(d.get("confidence", 0.0) or 0.0),
        abstain=bool(d.get("abstain", False)),
    )


def plan_to_dict(plan: RepairPlan) -> dict:
    return {
        "root_cause": plan.root_cause,
        "targets": [{"file": t.file, "symbol": t.symbol, "why": t.why} for t in plan.targets],
        "required_apis": list(plan.required_apis),
        "strategy": plan.strategy,
        "citations": list(plan.citations),
        "risks": plan.risks,
        "confidence": plan.confidence,
        "abstain": plan.abstain,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_plan.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/plan.py tests/fixeval/test_plan.py
git commit -m "feat(fixeval): RepairPlan type + tolerant plan parser

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.2: The oracle-blind in-world gate

**Files:**
- Modify: `groundloop/fixeval/plan.py` (add gate + groundedness)
- Test: `tests/fixeval/test_plan_gate.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_plan_gate.py
from groundloop.fixeval.plan import RepairPlan, PlanTarget, check_plan_in_world, plan_groundedness


def _wt(tmp_path, files):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return str(tmp_path)


def test_gate_passes_when_grounded(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F { void onBind(){ isAdded(); } }"})
    plan = RepairPlan(root_cause="rc", strategy="s",
                      targets=(PlanTarget(file="src/F.java", symbol="onBind"),),
                      required_apis=("isAdded",))
    chk = check_plan_in_world(plan, wt, candidates=["src/F.java"])
    assert chk.ok is True
    assert plan_groundedness(chk) == 1.0


def test_gate_flags_missing_file_and_scope(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    plan = RepairPlan(root_cause="rc", strategy="s",
                      targets=(PlanTarget(file="src/Ghost.java"),), required_apis=())
    chk = check_plan_in_world(plan, wt, candidates=["src/F.java"])
    assert chk.ok is False
    assert any("target_file_missing" in f for f in chk.failures)
    assert any("target_out_of_scope" in f for f in chk.failures)
    assert plan_groundedness(chk) == 0.0


def test_gate_flags_unresolved_symbol_and_api(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    plan = RepairPlan(root_cause="rc", strategy="s",
                      targets=(PlanTarget(file="src/F.java", symbol="nope"),),
                      required_apis=("alsoNope",))
    chk = check_plan_in_world(plan, wt, candidates=["src/F.java"])
    assert any("symbol_unresolved" in f for f in chk.failures)
    assert any("api_unresolved" in f for f in chk.failures)


def test_gate_rejects_abstain_and_empty(tmp_path):
    wt = _wt(tmp_path, {"src/F.java": "class F {}"})
    assert check_plan_in_world(RepairPlan("", (), abstain=True), wt, ["src/F.java"]).ok is False
    assert check_plan_in_world(RepairPlan("", ()), wt, ["src/F.java"]).ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_plan_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_plan_in_world'`.

- [ ] **Step 3: Write minimal implementation** (append to `groundloop/fixeval/plan.py`)

```python
from pathlib import Path                          # add to the imports at the top
from typing import Sequence                        # add to the imports at the top

from groundloop.fixeval.patch import norm_path     # add to the imports at the top


@dataclass(frozen=True)
class PlanCheck:
    ok: bool
    failures: tuple[str, ...]
    n_citations: int
    n_resolved: int


def _word(token: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", text) is not None


def check_plan_in_world(plan: RepairPlan, worktree_path: str, candidates: Sequence[str]) -> PlanCheck:
    """Oracle-blind gate: every claim must cite reality. Checks (a) each target file exists in the
    work-tree, (b) each target is within the localize candidate set, (c) each target.symbol /
    required_api appears textually in an existing target file, (d) root_cause/strategy/targets present.
    Citations = target files + symbols + required_apis; groundedness = resolved / cited."""
    if plan is None:
        return PlanCheck(False, ("unparseable_plan",), 0, 0)
    if plan.abstain:
        return PlanCheck(False, ("model_abstained",), 0, 0)
    failures: list[str] = []
    cand = {norm_path(c) for c in candidates}
    n_cit = n_res = 0
    text_by_file: dict[str, str] = {}
    if not plan.root_cause:
        failures.append("empty_root_cause")
    if not plan.strategy:
        failures.append("empty_strategy")
    if not plan.targets:
        failures.append("no_targets")
    for t in plan.targets:
        n_cit += 1
        p = Path(worktree_path) / t.file
        if p.is_file():
            n_res += 1
            text_by_file[t.file] = p.read_text(errors="replace")
        else:
            failures.append(f"target_file_missing:{t.file}")
        if norm_path(t.file) not in cand:
            failures.append(f"target_out_of_scope:{t.file}")
        if t.symbol:
            n_cit += 1
            if t.file in text_by_file and _word(t.symbol, text_by_file[t.file]):
                n_res += 1
            else:
                failures.append(f"symbol_unresolved:{t.symbol}")
    for a in plan.required_apis:
        n_cit += 1
        if any(_word(a, txt) for txt in text_by_file.values()):
            n_res += 1
        else:
            failures.append(f"api_unresolved:{a}")
    return PlanCheck(not failures, tuple(failures), n_cit, n_res)


def plan_groundedness(check: PlanCheck) -> float:
    return (check.n_resolved / check.n_citations) if check.n_citations else 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_plan_gate.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/plan.py tests/fixeval/test_plan_gate.py
git commit -m "feat(fixeval): oracle-blind in-world plan gate + groundedness

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.3: `PlanningFixEngine` (two-phase, gate → re-plan → abstain)

**Files:**
- Create: `groundloop/adapters/fix/planning.py`
- Test: `tests/fixeval/test_planning_engine.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_planning_engine.py
from groundloop.core.types import Ticket, WorkTree
from groundloop.adapters.fix.planning import PlanningFixEngine


class SeqModel:
    """Deterministic sequential model: returns scripted responses in order (last repeats)."""
    def __init__(self, responses):
        self._r = list(responses)
        self.i = 0
        self.cost_usd = 0.0

    def complete(self, prompt: str) -> str:
        r = self._r[min(self.i, len(self._r) - 1)]
        self.i += 1
        return r


def _wt(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "F.java").write_text("class F { void onBind(){ } }")
    return WorkTree(path=str(tmp_path))          # adjust ctor kwargs to core WorkTree if needed


def _ticket():
    return Ticket(id="c1", summary="crash", description="npe", logs=[])   # adjust to core Ticket ctor


_GOOD_PLAN = ('{"root_cause":"npe","targets":[{"file":"src/F.java","symbol":"onBind"}],'
              '"required_apis":[],"strategy":"guard","citations":["src/F.java"]}')
_DIFF = "```diff\n--- a/src/F.java\n+++ b/src/F.java\n@@ -1 +1 @@\n-class F { void onBind(){ } }\n+class F { void onBind(){ if(true){} } }\n```"


def test_happy_path_plan_then_patch(tmp_path):
    m = SeqModel([_GOOD_PLAN, _DIFF])
    eng = PlanningFixEngine(m)
    plan, patch, meta = eng.propose_with_plan(_wt(tmp_path), _ticket(), ["src/F.java"])
    assert plan is not None and patch.diff.startswith("--- a/src/F.java")
    assert meta["replans"] == 0 and meta["groundedness"] == 1.0
    assert m.i == 2                               # exactly two model calls


def test_replan_recovers_from_hallucination(tmp_path):
    bad = '{"root_cause":"x","targets":[{"file":"src/Ghost.java"}],"strategy":"s"}'
    m = SeqModel([bad, _GOOD_PLAN, _DIFF])
    plan, patch, meta = PlanningFixEngine(m, max_replan=1).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff and meta["replans"] == 1


def test_persistent_hallucination_abstains(tmp_path):
    bad = '{"root_cause":"x","targets":[{"file":"src/Ghost.java"}],"strategy":"s"}'
    m = SeqModel([bad, bad, _DIFF])
    plan, patch, meta = PlanningFixEngine(m, max_replan=1).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff == ""                       # abstain — no execute call
    assert m.i == 2                               # 2 plan calls, patch never requested


def test_model_abstain_short_circuits(tmp_path):
    m = SeqModel(['{"abstain":true,"root_cause":"","targets":[],"strategy":""}', _DIFF])
    plan, patch, meta = PlanningFixEngine(m, max_replan=0).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff == "" and m.i == 1


def test_satisfies_fixengine_propose(tmp_path):
    patch = PlanningFixEngine(SeqModel([_GOOD_PLAN, _DIFF])).propose(_wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff.startswith("--- a/src/F.java")
```

> Implementer note: confirm the exact `WorkTree` / `Ticket` constructor kwargs from
> `groundloop/core/types.py` and adjust `_wt`/`_ticket` accordingly before running (do NOT edit
> `core/types.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_planning_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: groundloop.adapters.fix.planning`.

- [ ] **Step 3: Write minimal implementation**

```python
# groundloop/adapters/fix/planning.py
"""Two-phase PLAN-then-ACT FixEngine. Phase 1 emits a grounded RepairPlan; an oracle-blind in-world
gate validates it (re-plan on failure, abstain after the bound); phase 2 executes the validated plan
into a unified diff over fault-site context. Satisfies the frozen core FixEngine.propose."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from groundloop.core.types import Patch, Ticket, WorkTree
from groundloop.fixeval.patch import extract_unified_diff, touched_files
from groundloop.fixeval.plan import (RepairPlan, check_plan_in_world, parse_plan, plan_groundedness)


class PlanningFixEngine:
    def __init__(self, model, *, preamble: str = "", max_replan: int = 1, context_window: int = 120):
        self.model = model
        self.preamble = preamble
        self.max_replan = max_replan
        self.context_window = context_window

    def with_preamble(self, preamble: str) -> "PlanningFixEngine":
        """Skills-aware clone sharing self.model (so GatewayModel.cost_usd keeps accruing)."""
        return PlanningFixEngine(self.model, preamble=preamble, max_replan=self.max_replan,
                                 context_window=self.context_window)

    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch:
        _plan, patch, _meta = self.propose_with_plan(worktree, ticket, locations)
        return patch

    def propose_with_plan(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]):
        """Returns (RepairPlan|None, Patch, meta{replans, groundedness}). Empty Patch = abstain."""
        locs = list(locations)
        plan = self._plan(worktree, ticket, locs, feedback="")
        chk = check_plan_in_world(plan, worktree.path, locs)
        attempts = 0
        while not chk.ok and attempts < self.max_replan:
            attempts += 1
            fb = ("The previous plan did not ground: " + "; ".join(chk.failures)
                  + ". Cite ONLY files from the candidate list and symbols/APIs that exist in them.")
            plan = self._plan(worktree, ticket, locs, feedback=fb)
            chk = check_plan_in_world(plan, worktree.path, locs)
        meta = {"replans": attempts, "groundedness": plan_groundedness(chk)}
        if not chk.ok:                                    # gate failed / abstained -> honest refusal
            return plan, Patch(diff="", files=()), meta
        return plan, self._execute(worktree, ticket, plan), meta

    def _plan(self, worktree, ticket, locations, *, feedback) -> RepairPlan | None:
        heads = "\n\n".join(self._head(worktree.path, loc) for loc in locations)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Candidate files (cite ONLY these): {', '.join(locations)}\n\n"
                  f"File heads:\n{heads}\n\n"
                  "Produce a REPAIR PLAN as a JSON object with keys: root_cause, "
                  "targets (list of {file, symbol, why}; file MUST be a candidate file), required_apis "
                  "(list), strategy, citations (candidate files your reasoning rests on), risks, "
                  "confidence (0..1), abstain (true if you cannot ground a fix). Reply ONLY with JSON.")
        if feedback:
            prompt += "\n\n" + feedback
        if self.preamble:
            prompt = self.preamble + "\n\n" + prompt
        return parse_plan(self.model.complete(prompt) or "")

    def _execute(self, worktree, ticket, plan: RepairPlan) -> Patch:
        ctx = "\n\n".join(self._window(worktree.path, t) for t in plan.targets)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Root cause: {plan.root_cause}\nStrategy: {plan.strategy}\n"
                  f"Targets: {', '.join(t.file for t in plan.targets)}\n"
                  f"Required APIs: {', '.join(plan.required_apis)}\n\n"
                  f"Fault-site context:\n{ctx}\n\n"
                  "Reply ONLY with a unified diff (```diff fenced) implementing this plan, or empty.")
        diff = extract_unified_diff(self.model.complete(prompt) or "")
        return Patch(diff=diff, files=tuple(touched_files(diff)))

    def _head(self, wt_path, loc, max_lines: int = 40) -> str:
        p = Path(wt_path) / loc
        if not p.is_file():
            return ""
        return f"### {loc}\n" + "\n".join(p.read_text(errors="replace").splitlines()[:max_lines])

    def _window(self, wt_path, target) -> str:
        p = Path(wt_path) / target.file
        if not p.is_file():
            return ""
        lines = p.read_text(errors="replace").splitlines()
        if target.symbol:
            for i, ln in enumerate(lines):
                if target.symbol in ln:
                    lo = max(0, i - self.context_window)
                    hi = min(len(lines), i + self.context_window)
                    return (f"### {target.file} (around {target.symbol}, lines {lo + 1}-{hi})\n"
                            + "\n".join(lines[lo:hi]))
        return f"### {target.file} (head)\n" + "\n".join(lines[: self.context_window * 2])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_planning_engine.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/fix/planning.py tests/fixeval/test_planning_engine.py
git commit -m "feat(fix): PlanningFixEngine — two-phase plan->gate->replan->abstain->patch

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.4: Carry the plan through the runner

**Files:**
- Modify: `groundloop/fixeval/runner.py` (`FixRecord` ~32-45; `_one` ~94-113; add `_do_propose`)
- Test: `tests/fixeval/test_runner_plan.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_runner_plan.py
from groundloop.core.types import Patch
from groundloop.fixeval.runner import FixRecord, _do_propose


class PlainFixer:
    model = type("M", (), {"cost_usd": 0.0})()
    def propose(self, wt, ticket, locations):
        return Patch(diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", files=("x",))


class PlanFixer(PlainFixer):
    def propose_with_plan(self, wt, ticket, locations):
        plan = {"root_cause": "rc", "targets": [{"file": "x", "symbol": None, "why": ""}],
                "required_apis": [], "strategy": "s", "citations": [], "risks": "",
                "confidence": 0.5, "abstain": False}
        return plan, Patch(diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", files=("x",)), \
            {"replans": 1, "groundedness": 1.0}


def test_do_propose_plain_fixer_has_no_plan():
    plan, patch, meta = _do_propose(PlainFixer(), None, None, ["x"])
    assert plan is None and meta == {} and patch.diff


def test_do_propose_plan_fixer_returns_dict_plan():
    plan, patch, meta = _do_propose(PlanFixer(), None, None, ["x"])
    assert plan["root_cause"] == "rc" and meta["groundedness"] == 1.0


def test_fixrecord_accepts_plan_fields():
    r = FixRecord(case_id="c", arm="a", predicted_repo="r", locations=["x"], patch_diff="d",
                  patch_files=["x"], patch_emitted=True, patch_applies=True, abstained=False,
                  abstain_reason=None, refine_iters=0, cost_usd=0.0,
                  plan={"root_cause": "rc"}, groundedness=1.0, replans=1)
    assert r.plan["root_cause"] == "rc" and r.groundedness == 1.0 and r.replans == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_runner_plan.py -q`
Expected: FAIL — `ImportError: cannot import name '_do_propose'` (and FixRecord rejects `plan`).

- [ ] **Step 3: Write minimal implementation**

In `groundloop/fixeval/runner.py`:

(a) Extend `FixRecord` (after `cost_usd: float`, line 45):

```python
    plan: dict | None = None
    groundedness: float | None = None
    replans: int = 0
```

(b) Add the helper (module level, after `_skill_query`):

```python
def _do_propose(f, wt, ticket, locations):
    """Use the plan-aware path when the fixer exposes it, else the frozen propose. Returns
    (plan_dict|None, Patch, meta)."""
    if hasattr(f, "propose_with_plan"):
        plan, patch, meta = f.propose_with_plan(wt, ticket, locations)
        from groundloop.fixeval.plan import plan_to_dict
        pd = plan_to_dict(plan) if plan is not None and not isinstance(plan, dict) else plan
        return pd, patch, (meta or {})
    return None, f.propose(wt, ticket, locations), {}
```

(c) In `_one`, replace the propose + refine block (lines 100-113) with:

```python
        plan_dict, patch, meta = _do_propose(f, wt, ticket, locations)
        applies = patch_applies(patch.diff, wt.path)
        iters = 0
        while patch.diff and not applies and iters < self.max_refine:   # bounded in-world refine
            iters += 1
            plan_dict, patch, meta = _do_propose(f, wt, ticket, locations)
            applies = patch_applies(patch.diff, wt.path)
        pmeta = dict(plan=plan_dict, groundedness=meta.get("groundedness"),
                     replans=meta.get("replans", 0))
        if not patch.diff or not applies:                     # SECONDARY: unappliable -> abstain
            return rec(predicted_repo=predicted, locations=locations, refine_iters=iters,
                       abstain_reason="patch_unappliable", cost_usd=self._cost(fixer) - c0, **pmeta)
        return FixRecord(case_id=case.case_id, arm=arm.name, predicted_repo=predicted,
                         locations=locations, patch_diff=patch.diff, patch_files=list(patch.files),
                         patch_emitted=True, patch_applies=True, abstained=False, abstain_reason=None,
                         refine_iters=iters, cost_usd=self._cost(fixer) - c0, **pmeta)
```

- [ ] **Step 4: Run test to verify it passes, and the full fix suite**

Run: `.venv/bin/python -m pytest tests/fixeval -q`
Expected: PASS (new + existing runner tests green; the `direct` path yields `plan=None`).

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/runner.py tests/fixeval/test_runner_plan.py
git commit -m "feat(fixeval): thread the RepairPlan + groundedness through FixRecord

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.5: `--fixer plan` at the composition root

**Files:**
- Modify: `groundloop/cli/__init__.py` (fixeval argparse ~747; `_run_fixeval` ~278-279)
- Test: `tests/fixeval/test_cli_fixer_arg.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_cli_fixer_arg.py
from groundloop.cli import build_parser        # adjust to the real parser factory name if different


def test_fixeval_accepts_fixer_plan():
    args = build_parser().parse_args(
        ["fixeval", "--dataset", "d", "--catalog", "c", "--index-db", "x",
         "--repos", "r", "--out", "o", "--fixer", "plan", "--max-replan", "2"])
    assert args.fixer == "plan" and args.max_replan == 2


def test_fixeval_fixer_defaults_direct():
    args = build_parser().parse_args(
        ["fixeval", "--dataset", "d", "--catalog", "c", "--index-db", "x", "--repos", "r", "--out", "o"])
    assert args.fixer == "direct" and args.max_replan == 1
```

> Implementer note: confirm the parser factory name (`build_parser` / `_build_parser` / `main`'s
> internal) in `groundloop/cli/__init__.py` and import it accordingly.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_cli_fixer_arg.py -q`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'fixer'`.

- [ ] **Step 3: Write minimal implementation**

(a) In the `fixeval` subparser (after `--skills-seed`, ~line 751), add:

```python
    fx.add_argument("--fixer", choices=["direct", "plan"], default="direct",
                    help="fix engine: direct (single-shot ModelPatchEngine) | "
                         "plan (two-phase PlanningFixEngine: plan->gate->re-plan->abstain->patch)")
    fx.add_argument("--max-replan", dest="max_replan", type=int, default=1,
                    help="plan fixer: bounded re-plan attempts before abstaining (default 1)")
```

(b) In `_run_fixeval`, replace the `records = runner.run(..., fixer=ModelPatchEngine(model))` call
(lines 278-279) with:

```python
    if getattr(args, "fixer", "direct") == "plan":
        from groundloop.adapters.fix.planning import PlanningFixEngine
        fixer = PlanningFixEngine(model, max_replan=args.max_replan)
    else:
        fixer = ModelPatchEngine(model)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)), fixer=fixer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_cli_fixer_arg.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/fixeval/test_cli_fixer_arg.py
git commit -m "feat(cli): gloop fixeval --fixer {direct,plan} + --max-replan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Grader tier + archive

### Task 2.1: `plan_groundedness` + `plan_correctness` in the scorecard

**Files:**
- Modify: `groundloop/fixeval/scorecard.py` (`grade_fix_all`)
- Test: `tests/fixeval/test_scorecard_plan_metrics.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_scorecard_plan_metrics.py
from dataclasses import dataclass
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all


@dataclass
class O:
    expected_files: list
    required_apis: list
    is_answerable: bool = True


def _rec(plan, groundedness):
    return FixRecord(case_id="c1", arm="plan", predicted_repo="r", locations=["src/Right.java"],
                     patch_diff="--- a/src/Right.java\n+++ b/src/Right.java\n@@ -1 +1 @@\n-a\n+b\n",
                     patch_files=["src/Right.java"], patch_emitted=True, patch_applies=True,
                     abstained=False, abstain_reason=None, refine_iters=0, cost_usd=0.0,
                     plan=plan, groundedness=groundedness, replans=0)


def test_plan_metrics_reported():
    plan = {"root_cause": "rc", "targets": [{"file": "src/Right.java", "symbol": None, "why": ""}],
            "required_apis": ["isAdded"], "strategy": "s", "citations": [], "risks": "",
            "confidence": 0.5, "abstain": False}
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["isAdded"])}
    card = grade_fix_all([_rec(plan, 1.0)], oracle_by_case=oracle)["arms"]["plan"]
    assert card["plan_groundedness"]["value"] == 1.0
    assert card["plan_target_recall@1"]["value"] == 1.0
    assert card["plan_api_match"]["value"] == 1.0


def test_plan_correctness_penalizes_wrong_target():
    plan = {"root_cause": "rc", "targets": [{"file": "src/Wrong.java", "symbol": None, "why": ""}],
            "required_apis": [], "strategy": "s", "citations": [], "risks": "",
            "confidence": 0.5, "abstain": False}
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=[])}
    card = grade_fix_all([_rec(plan, 1.0)], oracle_by_case=oracle)["arms"]["plan"]
    assert card["plan_target_recall@1"]["value"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_scorecard_plan_metrics.py -q`
Expected: FAIL — `KeyError: 'plan_groundedness'`.

- [ ] **Step 3: Write minimal implementation** — inside `grade_fix_all`, per arm

```python
        # --- plan metrics (only cases that carry a captured plan) ---
        plan_recs = [r for r in recs if getattr(r, "plan", None)]
        gnd = [r.groundedness for r in plan_recs if r.groundedness is not None]
        pc_loc = [(r, o) for r, o in pairs if getattr(r, "plan", None) and o.expected_files]
        pc_api = [(r, o) for r, o in pairs if getattr(r, "plan", None) and o.required_apis]

        def _plan_target_recall(r, o, k):
            files = [t["file"] for t in r.plan["targets"]]
            return recall_at_k([norm_path(x) for x in files],
                               {norm_path(e) for e in o.expected_files}, k)

        def _plan_api_match(r, o):
            named = {a.lower() for a in r.plan["required_apis"]}
            return sum(1 for a in o.required_apis if a.lower() in named) / len(o.required_apis)
```

Then add to the `arms[arm] = {...}` dict:

```python
            "plan_groundedness": _wrap(sum(gnd) / len(gnd), len(gnd)) if gnd else {"value": None, "n": 0},
            **{f"plan_target_recall@{k}":
               (_wrap(sum(_plan_target_recall(r, o, k) for r, o in pc_loc) / len(pc_loc), len(pc_loc))
                if pc_loc else {"value": None, "n": 0}) for k in (1, 5)},
            "plan_api_match": (_wrap(sum(_plan_api_match(r, o) for r, o in pc_api) / len(pc_api), len(pc_api))
                               if pc_api else {"value": None, "n": 0}),
```

- [ ] **Step 4: Run test to verify it passes + full suite**

Run: `.venv/bin/python -m pytest tests/fixeval -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/scorecard.py tests/fixeval/test_scorecard_plan_metrics.py
git commit -m "feat(fixeval): plan_groundedness + plan_correctness grader metrics

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.2: Plan archive (capture only)

**Files:**
- Create: `groundloop/fixeval/archive.py`
- Modify: `groundloop/cli/__init__.py` (`_run_fixeval`, after grading ~line 282)
- Test: `tests/fixeval/test_archive.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_archive.py
import json
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.archive import archive_plans


def _rec(case_id, plan):
    return FixRecord(case_id=case_id, arm="plan", predicted_repo="r", locations=[], patch_diff="",
                     patch_files=[], patch_emitted=bool(plan), patch_applies=bool(plan),
                     abstained=not plan, abstain_reason=None, refine_iters=0, cost_usd=0.0,
                     plan=plan, groundedness=1.0 if plan else None, replans=0)


def test_archive_writes_only_planned_cases(tmp_path):
    recs = [_rec("c1", {"root_cause": "rc", "targets": []}), _rec("c2", None)]
    n = archive_plans(recs, str(tmp_path))
    assert n == 1
    files = list((tmp_path / "plans").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["case_id"] == "c1" and payload["outcome"]["patch_applies"] is True
    assert payload["schema"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_archive.py -q`
Expected: FAIL — `ModuleNotFoundError: groundloop.fixeval.archive`.

- [ ] **Step 3: Write minimal implementation**

```python
# groundloop/fixeval/archive.py
"""Persist per-case repair plans + outcomes (capture-only; consumption — retrieval / regression /
distill — is a future design). Keyed by case_id + arm under <out>/plans/."""
from __future__ import annotations

import json
from pathlib import Path

ARCHIVE_SCHEMA = 1


def archive_plans(records, out_dir: str) -> int:
    d = Path(out_dir) / "plans"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in records:
        if getattr(r, "plan", None) is None:
            continue
        payload = {
            "schema": ARCHIVE_SCHEMA,
            "case_id": r.case_id,
            "arm": r.arm,
            "predicted_repo": r.predicted_repo,
            "plan": r.plan,
            "outcome": {
                "groundedness": r.groundedness,
                "replans": getattr(r, "replans", 0),
                "abstained": r.abstained,
                "patch_emitted": r.patch_emitted,
                "patch_applies": r.patch_applies,
            },
        }
        (d / f"{r.case_id}__{r.arm}.json").write_text(json.dumps(payload, indent=2))
        n += 1
    return n
```

(b) In `_run_fixeval`, after `Path(args.out).with_suffix(".md").write_text(...)` (line 283), add:

```python
    from groundloop.fixeval.archive import archive_plans
    n_plans = archive_plans(records, str(Path(args.out).parent))
    if n_plans:
        print(f"archived {n_plans} plan(s) -> {Path(args.out).parent}/plans/")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_archive.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/archive.py groundloop/cli/__init__.py tests/fixeval/test_archive.py
git commit -m "feat(fixeval): archive per-case RepairPlan + outcome (capture-only)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.3: Surface plan metrics in the report + CLI summary

**Files:**
- Modify: `groundloop/fixeval/report.py` (`render_fix_markdown`)
- Modify: `groundloop/cli/__init__.py` (`_run_fixeval` print loop ~284-289)
- Test: `tests/fixeval/test_report_plan.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_report_plan.py
from groundloop.fixeval.report import render_fix_markdown


def test_markdown_includes_plan_metrics_when_present():
    card = {"n_cases": 1, "arms": {"plan": {
        "n": 1, "fix_coverage": 1.0, "abstain_rate": 0.0, "patch_apply_rate": 1.0,
        "file_recall@1": {"value": 1.0, "n": 1}, "file_recall@3": {"value": 1.0, "n": 1},
        "file_recall@5": {"value": 1.0, "n": 1}, "resolved_rate": {"value": 1.0, "n": 1},
        "resolved_rate_strict": {"value": 1.0, "n": 1}, "required_api_pass_rate": {"value": 1.0, "n": 1},
        "fabrication_rate": {"value": None, "n": 0}, "n_gradeable": 1, "n_excluded": 0,
        "phi_c": {"1.0": 1.0}, "cost_total": 0.0, "cost_per_solved": None,
        "plan_groundedness": {"value": 0.9, "n": 1}, "plan_target_recall@1": {"value": 1.0, "n": 1},
        "plan_target_recall@5": {"value": 1.0, "n": 1}, "plan_api_match": {"value": 1.0, "n": 1},
        "resolved_by_case": {}}}}
    md = render_fix_markdown(card)
    assert "plan_groundedness" in md and "resolved_rate_strict" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_report_plan.py -q`
Expected: FAIL (the strings are not yet rendered).

- [ ] **Step 3: Write minimal implementation**

Read `render_fix_markdown` first to match its current table shape, then add `resolved_rate_strict`,
`plan_groundedness`, `plan_target_recall@1`, `plan_api_match` as rows/columns (guard for `None`/absent
keys with `.get(...)` so `direct`-arm cards without plan metrics still render). In `_run_fixeval`'s print
loop, extend the per-arm line:

```python
        pg = a.get("plan_groundedness", {}).get("value")
        rs = a.get("resolved_rate_strict", {}).get("value")
        extra = ""
        if pg is not None:
            ptr = a.get("plan_target_recall@1", {}).get("value")
            extra = (f" plan_grounded={pg:.2f} plan_recall@1={'n/a' if ptr is None else f'{ptr:.2f}'}"
                     f" resolved_strict={'n/a' if rs is None else f'{rs:.2f}'}")
        print(f"{arm}: file_recall@1={'n/a' if fr is None else f'{fr:.2f}'} "
              f"apply_rate={a['patch_apply_rate']:.2f} "
              f"fabrication={'n/a' if fab is None else f'{fab:.2f}'} gradeable_n={a['n_gradeable']}{extra}")
```

- [ ] **Step 4: Run test to verify it passes + full suite + lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: PASS (full suite green), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/report.py groundloop/cli/__init__.py tests/fixeval/test_report_plan.py
git commit -m "feat(fixeval): surface plan + strict-resolution metrics in report/summary

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.4: `distilled` skills arm — make distilled knowledge a measurable arm

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_load_skills` ~223-238; fixeval `--skills` choices ~747)
- Test: `tests/fixeval/test_skills_distilled_arm.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_skills_distilled_arm.py
from groundloop.cli import _load_skills, build_parser          # adjust factory name if different
from groundloop.kb.validate import SEED_PATH as KB_SEED


def test_distilled_kind_loads_a_corpus():
    # distilled.toml has the SAME shape as the KB seed; prove the 'distilled' kind resolves + loads a
    # corpus (the KB seed stands in for distilled.toml here via the --skills-seed override path).
    reg = _load_skills("distilled", KB_SEED, None)
    assert reg is not None


def test_fixeval_accepts_skills_distilled():
    args = build_parser().parse_args(
        ["fixeval", "--dataset", "d", "--catalog", "c", "--index-db", "x", "--repos", "r",
         "--out", "o", "--fixer", "plan", "--skills", "distilled"])
    assert args.skills == "distilled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_skills_distilled_arm.py -q`
Expected: FAIL — `--skills distilled` is not an allowed choice; `_load_skills` raises on `"distilled"`.

- [ ] **Step 3: Write minimal implementation**

(a) In `_load_skills`, add a branch (after the `placebo` branch, ~line 235):

```python
    elif kind == "distilled":
        path = seed or str(Path(KB_SEED).parent / "distilled.toml")   # produced by `gloop kb-distill`
```

(b) Add `distilled` to the fixeval `--skills` choices (~line 747):

```python
    fx.add_argument("--skills", choices=["none", "mock", "kb", "placebo", "distilled"], default="none",
                    help="dev-experience KB arm: none | mock | kb (raw corpus) | placebo | "
                         "distilled (the kb-distill output, distilled.toml)")
```

> Note: `distilled.toml` is produced by the existing `gloop kb-distill` pipeline (gated on a positive
> `kb-ab` verdict). If it is absent, `MockSkillRegistry.load` raises a clear `FileNotFoundError` — that
> is intended: validate distilled knowledge only after it has been minted.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/fixeval/test_skills_distilled_arm.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/fixeval/test_skills_distilled_arm.py
git commit -m "feat(cli): gloop fixeval --skills distilled — measurable distilled-KB arm

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.5: Grounded two-sided accept in `gloop compare` (validate KB + distilled on the plan signal)

**Files:**
- Modify: `groundloop/fixeval/compare.py` (`_POS`/`compare_metrics` lines 25-39; add `accept_grounded`)
- Modify: `groundloop/cli/__init__.py` (`_run` compare dispatch ~616-620 — surface the grounded verdict)
- Test: `tests/fixeval/test_compare_grounded.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_compare_grounded.py
from groundloop.fixeval.compare import compare_metrics, accept_grounded


def _arm(**kw):
    base = {"file_recall@1": {"value": 1.0}, "file_recall@3": {"value": 1.0},
            "file_recall@5": {"value": 1.0}, "resolved_rate": {"value": 0.3},
            "resolved_rate_strict": {"value": 0.2}, "patch_apply_rate": 0.9,
            "fabrication_rate": {"value": 0.1}, "plan_target_recall@1": {"value": 0.4},
            "plan_target_recall@5": {"value": 0.6}, "plan_api_match": {"value": 0.5},
            "plan_groundedness": {"value": 0.9}, "phi_c": {"1.0": 0.5},
            "cost_per_solved": 0.01, "cost_total": 1.0}
    base.update(kw)
    return base


def test_grounded_metrics_surfaced():
    cmp = compare_metrics(_arm(), _arm(**{"resolved_rate_strict": {"value": 0.5}}))
    assert cmp["resolved_rate_strict"]["delta"] == 0.3
    assert "plan_target_recall@1" in cmp


def test_grounded_accept_on_plan_recall_lift():
    v = accept_grounded(compare_metrics(_arm(), _arm(**{"plan_target_recall@1": {"value": 0.6}})),
                        {"newly_solved": [], "newly_broken": []})
    assert v["accepted"] is True and v["pos_ok"] is True


def test_grounded_reject_when_groundedness_drops():
    v = accept_grounded(compare_metrics(
        _arm(), _arm(**{"plan_target_recall@1": {"value": 0.6}, "plan_groundedness": {"value": 0.7}})), {})
    assert v["accepted"] is False and v["honesty_ok"] is False   # lifted recall but hallucinated more


def test_grounded_reject_when_fabrication_rises():
    v = accept_grounded(compare_metrics(
        _arm(), _arm(**{"resolved_rate_strict": {"value": 0.4}, "fabrication_rate": {"value": 0.3}})), {})
    assert v["accepted"] is False and v["honesty_ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_compare_grounded.py -q`
Expected: FAIL — `ImportError: cannot import name 'accept_grounded'`.

- [ ] **Step 3: Write minimal implementation** (in `groundloop/fixeval/compare.py`)

Add the grounded metric tuple and include it in `compare_metrics`:

```python
# after _COST (line 27)
_GROUNDED = ("resolved_rate_strict", "plan_target_recall@1", "plan_target_recall@5",
             "plan_api_match", "plan_groundedness")
```

```python
# in compare_metrics, extend the loop (line 33)
    for m in _POS + _NEG + _COST + _GROUNDED:
```

Add the grounded verdict:

```python
def accept_grounded(metrics_cmp: dict, resolved_cmp: dict, *, cost_budget: float | None = None) -> dict:
    """Two-sided verdict on the GROUNDED plan signal (not the game-able resolved_rate) — the gate for
    validating raw KB AND distilled knowledge under --fixer plan. POS = Δplan_target_recall@1>0 OR
    Δresolved_rate_strict>0 ; HONESTY = Δfabrication_rate<=0 AND Δplan_groundedness>=0 (must not
    hallucinate more) ; COST advisory unless a budget is given. Absent plan metrics -> pos_ok False."""
    dtr = metrics_cmp.get("plan_target_recall@1", {}).get("delta")
    drs = metrics_cmp.get("resolved_rate_strict", {}).get("delta")
    dfab = metrics_cmp.get("fabrication_rate", {}).get("delta")
    dgnd = metrics_cmp.get("plan_groundedness", {}).get("delta")
    dcost = metrics_cmp.get("cost_per_solved", {}).get("delta")
    pos_ok = (dtr is not None and dtr > 0) or (drs is not None and drs > 0)
    honesty_ok = (dfab is None or dfab <= 0) and (dgnd is None or dgnd >= 0)
    cost_ok = cost_budget is None or dcost is None or dcost <= cost_budget
    reasons = []
    if not pos_ok:
        reasons.append("no grounded lift (Δplan_target_recall@1<=0 and Δresolved_rate_strict<=0)")
    if not honesty_ok:
        reasons.append(f"honesty regressed (Δfabrication={dfab}, Δgroundedness={dgnd})")
    if not cost_ok:
        reasons.append(f"cost_per_solved rose beyond budget (Δ={dcost})")
    return {"accepted": pos_ok and honesty_ok and cost_ok, "pos_ok": pos_ok,
            "honesty_ok": honesty_ok, "cost_ok": cost_ok, "reasons": reasons}
```

(b) In the `compare` CLI dispatch (`_run`, ~line 616), import and also compute the grounded verdict,
adding it to whatever the command prints/writes (guard so a non-plan comparison still works — it returns
`pos_ok=False`, correctly "no grounded lift"):

```python
    from groundloop.fixeval.compare import compare, compare_metrics, accept, accept_grounded
    ...
    grounded = accept_grounded(mcmp, rcmp, cost_budget=getattr(args, "cost_budget", None))
    # include `grounded` alongside the existing proxy `verdict` in the printed/written output
```

> Implementer note: match the current `_run` compare output shape; add a `grounded_verdict` key next to
> the existing proxy verdict.

- [ ] **Step 4: Run test to verify it passes + full suite + lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: PASS (full suite green), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/compare.py groundloop/cli/__init__.py tests/fixeval/test_compare_grounded.py
git commit -m "feat(fixeval): accept_grounded — two-sided KB/distilled verdict on the plan signal

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Validation & Measurement (how we prove it worked)

This phase has **no code**; it is the acceptance runbook. Do not commit results here — write them up in
Phase 4.

### 3.1 Type-1 acceptance gate (hermetic, every task already ran it; final confirm)

- [ ] `.venv/bin/python -m pytest -q` → **all green** (existing suite + the new plan/gate/engine/runner/
  scorecard/archive/report tests). This proves: the two-phase engine plans→gates→re-plans→abstains
  correctly, the gate is oracle-blind, hardened resolution rejects wrong-file/comment-only patches, the
  plan metrics compute, the archive captures only planned cases, and `direct` still yields `plan=None`.
- [ ] `.venv/bin/ruff check groundloop tests` → clean (line length 110).

### 3.2 Pre-hardening baseline snapshot (do BEFORE relying on the strict metric)

The in-flight live run (`/home/vinc/gl-eval/type2-run/kb-ab`) produces the current-proxy `resolved_rate`
per arm. When it lands, record those values as the **pre-hardening baseline** so the hardened
`resolved_rate_strict` is interpreted against a known "before":

- [ ] Save `resolved_rate` + `resolved_rate_strict` per arm from any existing scorecards to
  `docs/2026-07-07-*.md` notes. (Both are now emitted, so a re-grade of old records is unnecessary once
  Phase 0 is merged — `grade_fix_all` recomputes both from the stored diffs.)

### 3.3 Type-2 live A/B — the measurement (gated; real gateway + fleet repos)

Preconditions (from CLAUDE.md / `docs/type2-eval-setup.md`): source `.env`, run off ext4, use the
plain-dir corpora. **Never** skip the `.env` source or every arm silently degrades to the canned model.

```bash
cd /mnt/x/code/GroundLoop && set -a; . ./.env; set +a
.venv/bin/gloop doctor --atlas-db /home/vinc/gl-eval/atlas-9.db          # repos:9 units:475415 ; gateways 200
ATLAS=/home/vinc/gl-eval/atlas-9.db
SUB=/home/vinc/gl-eval/dataset-neg-synth-sub                              # 278: 128 neg + 150 pos
REPOS=/mnt/x/code/corpora-local                                          # plain-dir @base snapshots (NOT gl-corpora)
OUT=/home/vinc/gl-eval/plan-run ; mkdir -p "$OUT"

# Guard: refuse to spend if the dataset carries no negatives (abstention/fabrication unmeasurable)
# (mirror the existing type2_run.sh guard on n_unanswerable >= 1 before the fixeval calls)

# A/B (engine): direct vs plan, skills=none — isolates the plan-format effect
.venv/bin/gloop fixeval --dataset $SUB --catalog $SUB/catalog.json --index-db $ATLAS \
  --repos $REPOS --fixer direct --skills none --out $OUT/fix-direct-none.json
.venv/bin/gloop fixeval --dataset $SUB --catalog $SUB/catalog.json --index-db $ATLAS \
  --repos $REPOS --fixer plan --max-replan 1 --skills none --out $OUT/fix-plan-none.json

.venv/bin/gloop compare --base $OUT/fix-direct-none.json --head $OUT/fix-plan-none.json   # newly_solved/broken
# (the raw-KB + distilled skills sweep under --fixer plan is §3.6)
```

Cost/time: `--fixer plan` is ~2–3× the model calls of `direct` (plan + execute + up to `max_replan`
re-plans; abstentions are free). Expect the plan A/B over 278 cases to run in the low hours on
deepseek-chat. Run detached; snapshot each `fix-*.json` as it lands.

### 3.4 Metrics collected per arm (all now in the scorecard JSON)

| Metric | Source key | What it tells us |
|--------|-----------|------------------|
| Plan correctness | `plan_target_recall@1/5`, `plan_api_match` | did the plan name the RIGHT files/APIs (non-game-able) |
| Plan groundedness | `plan_groundedness` | did the model hallucinate citations (oracle-blind) |
| Resolution (hardened) | `resolved_rate_strict` | patch edits the right file + calls the API on a code line |
| Resolution (proxy) | `resolved_rate` | old proxy, kept for comparability |
| Honesty | `fabrication_rate` (over the 128 negatives) | clean patch on an unanswerable ticket |
| Coverage | `abstain_rate`, `fix_coverage` | over/under-abstention |
| Repair effort | mean `replans` (from archive outcomes) | how often the gate had to bounce a plan |
| Cost | `cost_total`, `cost_per_solved` | $ per grounded solve |

### 3.5 Decision rule (the arm discipline — roadmap §6)

- [ ] **Adopt `--fixer plan` over `direct`** iff it improves the grounded signal —
  `Δplan_target_recall@1 > 0` **OR** `Δresolved_rate_strict > 0` — **AND** `Δfabrication_rate ≤ 0`, at an
  acceptable `Δcost_per_solved`. (The raw-KB + distilled skills validation under `--fixer plan` is §3.6.)
- [ ] **Report the result honestly either way.** A clean *negative* ("planning did not beat direct on the
  grounded signal at 2–3× cost") is a valid, publishable grounded finding — do not massage it. Note any
  silent caps (e.g. cases with no `expected_files`/`required_apis` are advisory-excluded from
  correctness, as today).

### 3.6 Distilled-knowledge validation (the retain-loop, on the grounded signal)

The KB holds two kinds of knowledge — **raw** authored Skills (`aaos_kb_seed.toml`, 12 candidates) and
**distilled** knowledge (`distilled.toml`, minted by `gloop kb-distill`). Both are validated here on the
plan format's grounded signal, not the game-able proxy the current KB A/B keys on.

**Prerequisite — mint the distilled corpus** (existing gated pipeline):
```bash
# kb-distill is gated on a positive kb-ab verdict: run the KB A/B, then distill (only mints if accepted).
.venv/bin/gloop kb-ab --dataset $SUB --catalog $SUB/catalog.json --index-db $ATLAS \
  --repos $REPOS --out $OUT/kb-ab
.venv/bin/gloop kb-distill --verdict $OUT/kb-ab/verdict.json --dataset $SUB --index-db $ATLAS \
  --repos $REPOS        # writes distilled.toml beside the KB seed IFF the verdict accepted
```

**Grounded 4-arm skills sweep under the plan fixer:**
```bash
for sk in none kb placebo distilled; do
  .venv/bin/gloop fixeval --dataset $SUB --catalog $SUB/catalog.json --index-db $ATLAS \
    --repos $REPOS --fixer plan --max-replan 1 --skills $sk --out $OUT/fix-plan-$sk.json
done
# grounded two-sided verdict (accept_grounded): each vs the length-matched placebo + the marginal test
.venv/bin/gloop compare --base $OUT/fix-plan-placebo.json --head $OUT/fix-plan-kb.json         # raw KB value
.venv/bin/gloop compare --base $OUT/fix-plan-placebo.json --head $OUT/fix-plan-distilled.json  # distilled value
.venv/bin/gloop compare --base $OUT/fix-plan-kb.json      --head $OUT/fix-plan-distilled.json  # marginal value
```

**Questions this answers (each via `grounded_verdict.accepted`):**
- [ ] **Raw KB:** does authored knowledge lift the grounded signal over placebo without more
  hallucination? (kb vs placebo — POS on Δplan_target_recall@1 / Δresolved_rate_strict, Δfabrication≤0,
  Δgroundedness≥0.)
- [ ] **Distilled KB:** does the distilled corpus lift it over placebo? (distilled vs placebo.)
- [ ] **Is distillation worth it?** does distilled retain (or beat) raw's grounded lift at ≤ cost/noise?
  (distilled vs kb.)
- [ ] **Honest-negative is a result.** If raw or distilled ties/loses to placebo on the grounded gate,
  that is the project's core finding surfacing — authored/distilled cold-start knowledge does not beat a
  length-matched control on a trustworthy metric. Record it; do not massage.

**Retain-loop consistency (note):** the distilled corpus above is *distilled* under the proxy
`resolved_rate` (the current `kb-distill` run_fn), then *validated* on the grounded signal — a
deliberately stringent test ("does proxy-distilled knowledge survive a trustworthy metric?"). Re-gating
both `kb-distill`'s run_fn and `kb-ab`'s verdict on `--fixer plan` + `accept_grounded` (so distillation is
produced AND validated on the grounded signal) is a recommended follow-on, tracked but out of this plan's
scope.

---

## Phase 4 — Write up, final review, land

- [ ] Write `docs/2026-07-07-plan-fix-evaluation.md`: the engine A/B scorecard (plan correctness /
  groundedness / hardened + proxy resolution / fabrication / cost per arm), the §3.6 raw-KB and
  distilled-KB `grounded_verdict`s (kb-vs-placebo, distilled-vs-placebo, distilled-vs-kb), the decisions,
  and the honest caveats (proxy-not-tests; file-grain context window; advisory exclusions; distilled
  produced-under-proxy).
- [ ] Dispatch a final code-review subagent over the whole diff (per subagent-driven-development).
- [ ] Confirm `.venv/bin/python -m pytest -q` green + `.venv/bin/ruff check groundloop tests` clean.
- [ ] Update `docs/STATUS.md` and the memory ([[type2-eval-build-status]]) with the outcome.
- [ ] Commit the write-up; push `origin master` (with the earlier unpushed code commits).

---

## Verification (end-to-end acceptance)

1. **Phase 0** — `resolved_rate_strict` present in every fix scorecard; a wrong-file patch and a
   comment-only API both score `strict=0` while the old proxy may score 1.0 (regression tests lock this).
2. **Phase 1** — `gloop fixeval --fixer plan` runs end-to-end; the engine plans→gates→re-plans→abstains;
   `PlanningFixEngine` satisfies `FixEngine.propose`; `direct` path is byte-unchanged (`plan=None`).
3. **Phase 2** — scorecard reports `plan_groundedness` + `plan_target_recall@1/5` + `plan_api_match`;
   `<out>/plans/` holds one `plan.json` per planned case.
4. **Phase 3** — the engine A/B yields a per-arm scorecard with the decision rule applied; the §3.6
   4-arm skills sweep yields `grounded_verdict`s for raw-KB-vs-placebo, distilled-vs-placebo, and
   distilled-vs-raw; the result (lift or honest-negative) is written up.
5. **Invariants** — no diff under `groundloop/core/`; atlas schema unchanged; full suite green + ruff
   clean before each commit.

## Self-review notes (author)

- **Spec coverage:** every spec §5–§8 component maps to a task (engine 1.3, schema 1.1, gate 1.2, KB via
  the existing preamble carried into `_plan`, grader 2.1, archive 2.2, resolved_rate hardening 0.1/0.2,
  arm 1.5). Distilled/raw KB validation on the grounded signal maps to Tasks 2.4 (distilled arm) + 2.5
  (`accept_grounded`) + §3.6. Spec §5.5 structured KB field-injection and symbol/line grain are
  explicitly Phase-3-deferred in the spec and out of scope here — not gaps.
- **Type consistency:** `RepairPlan`/`PlanTarget` (1.1) are used unchanged by the gate (1.2), engine
  (1.3), runner `plan_to_dict` (1.4), and grader (2.1 reads the dict form). `resolved_rate_strict`,
  `plan_groundedness`, `plan_target_recall@k`, `plan_api_match` names are identical across scorecard,
  report, and measurement.
- **Placeholders:** two implementer-verify notes (core `WorkTree`/`Ticket` ctor kwargs; the parser
  factory name) — these are "confirm the existing signature," not unwritten code. All code steps carry
  runnable code.
