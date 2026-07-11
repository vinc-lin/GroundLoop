# Self-Scoring Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gloop run` self-scoring — persist the `RunRecord` it currently discards (batch over a
dataset), and add an offline `gloop grade-run` that turns run-records + the hidden oracle into a per-stage
scorecard (match / localize-as-run / localize-isolated / fix-or-honest-abstain), with automatic counts.

**Architecture:** Five additive units at the composition root + an offline grader. **Zero `core/` edits** —
`run_ticket`/`RunRecord` reused frozen; the record already carries `ranked`, `locations`, `patch`. Reuses
`eval` + `fixeval` machinery (`load_cases`, `load_eval_oracle`, `recall_at_k`, `grade_fix_all`, `FixRecord`,
`patch_applies`, `GitFixtureEstate`). The loop stays oracle-blind (`load_cases` never reads `_oracle/`); the
grader is the sole oracle reader (`load_eval_oracle`), mirroring `fixeval`.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests: `.venv/bin/python -m pytest -q`. Lint:
`.venv/bin/ruff check groundloop tests` (line 110). Spec: `docs/superpowers/specs/2026-07-11-self-scoring-pipeline-design.md`.

**Design refinements locked during planning (vs. the spec):**
- `patch_applies` is computed at **run time** (mechanical, oracle-blind — `patch_applies(diff, worktree)`
  reads only the diff + checkout) and stored in the record, so `grade-run` needs no worktree at grade time.
- The fix UNGRADEABLE gate is simply `materialize.present == False`. A *present* checkout scores a fabricated
  patch as an honest 0 (fails apply / `resolved_strict`); only the empty-worktree case must be excluded.
- `grade-run` adapts each run-record into a `fixeval.runner.FixRecord` and reuses `grade_fix_all` verbatim
  (per-`bug_kind` subset), rather than reimplementing fix metrics.

---

## Task 1: Run-record IO (`groundloop/run/record.py`)

**Files:**
- Create: `groundloop/run/__init__.py` (empty), `groundloop/run/record.py`
- Test: `tests/run/__init__.py` (empty), `tests/run/test_record.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/run/test_record.py
import json
from pathlib import Path
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.record import RunRecordIO, MaterializeOutcome, ORACLE_KEYS


def _rec():
    patch = Patch(diff="--- a/x.kt\n+++ b/x.kt\n@@ -1 +1 @@\n-a\n+b\n", files=("x.kt",))
    return RunRecord(
        ticket_id="GEI-1",
        ranked=[RepoScore(RepoRef("engineering"), 0.9, ("ev",)), RepoScore(RepoRef("other"), 0.1)],
        chosen=RepoRef("engineering"), locations=["x.kt", "y.kt"], patch=patch,
        change=Change(change_id="gl-1", commit_subject="fix", ticket_id="GEI-1", patch=patch),
        bound=True, events=["intake", "match"])


def test_roundtrip(tmp_path):
    mo = MaterializeOutcome(repo="engineering", path="/w/engineering", present=True, n_files=3)
    p = tmp_path / "runs" / "GEI-1.json"
    RunRecordIO.write(str(p), _rec(), materialize=mo, match_arm="component", patch_applies=True)
    doc = RunRecordIO.read(str(p))
    assert doc.ticket_id == "GEI-1"
    assert doc.chosen == "engineering"
    assert doc.ranked[0]["repo"] == "engineering" and doc.ranked[0]["score"] == 0.9
    assert doc.locations == ["x.kt", "y.kt"]
    assert doc.patch["files"] == ["x.kt"]
    assert doc.patch_applies is True
    assert doc.match_arm == "component"
    assert doc.materialize.present is True and doc.materialize.n_files == 3


def test_record_carries_no_oracle(tmp_path):
    p = tmp_path / "runs" / "GEI-1.json"
    RunRecordIO.write(str(p), _rec(), materialize=MaterializeOutcome("engineering", "/w", False, 0),
                      match_arm="flood", patch_applies=False)
    blob = json.loads(Path(p).read_text())
    text = json.dumps(blob).lower()
    for k in ORACLE_KEYS:                       # owning_repo / expected_files / required_apis
        assert k not in blob
    assert "owning_repo" not in text and "expected_files" not in text
```

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/run/test_record.py -q` → FAIL (no module `groundloop.run.record`).

- [ ] **Step 3: Write minimal implementation**

```python
# groundloop/run/record.py
"""Serialize the frozen RunRecord (+ a materialize sidecar) to a loop-only, oracle-free run-record JSON.
The run pass writes it; the offline grade pass reads it. No oracle fields ever appear here."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from groundloop.core.workflow import RunRecord

ORACLE_KEYS = ("owning_repo", "expected_files", "required_apis")


@dataclass(frozen=True)
class MaterializeOutcome:
    repo: str
    path: str
    present: bool
    n_files: int


@dataclass(frozen=True)
class RunDoc:
    ticket_id: str
    match_arm: str
    ranked: list[dict]
    chosen: str
    locations: list[str]
    patch: dict
    patch_applies: bool
    change_id: str
    bound: bool
    events: list[str]
    materialize: MaterializeOutcome


class RunRecordIO:
    @staticmethod
    def write(path: str, rec: RunRecord, *, materialize: MaterializeOutcome, match_arm: str,
              patch_applies: bool) -> None:
        blob = {
            "ticket_id": rec.ticket_id,
            "match_arm": match_arm,
            "ranked": [{"repo": rs.repo.name, "score": rs.score, "evidence": list(rs.evidence)}
                       for rs in rec.ranked],
            "chosen": rec.chosen.name,
            "locations": list(rec.locations),
            "patch": {"diff": rec.patch.diff, "files": list(rec.patch.files)},
            "patch_applies": bool(patch_applies),
            "change_id": rec.change.change_id,
            "bound": rec.bound,
            "events": list(rec.events),
            "materialize": {"repo": materialize.repo, "path": materialize.path,
                            "present": materialize.present, "n_files": materialize.n_files},
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(blob, indent=2, ensure_ascii=False))

    @staticmethod
    def read(path: str) -> RunDoc:
        raw = json.loads(Path(path).read_text())
        m = raw["materialize"]
        return RunDoc(
            ticket_id=raw["ticket_id"], match_arm=raw["match_arm"], ranked=raw["ranked"],
            chosen=raw["chosen"], locations=raw["locations"], patch=raw["patch"],
            patch_applies=raw["patch_applies"], change_id=raw["change_id"], bound=raw["bound"],
            events=raw["events"],
            materialize=MaterializeOutcome(m["repo"], m["path"], m["present"], m["n_files"]))
```

- [ ] **Step 4: Run test to verify it passes** — `.venv/bin/python -m pytest tests/run/test_record.py -q` → PASS.
- [ ] **Step 5: Commit** — `git add groundloop/run tests/run && git commit -m "feat(run): oracle-free run-record IO (RunRecordIO + MaterializeOutcome)"`

---

## Task 2: Recording + checkout estates (`groundloop/adapters/estate.py`)

**Files:**
- Modify: `groundloop/adapters/estate.py` (add `RecordingEstate`, `CheckoutEstate`; do NOT touch `MockEstate`/`GitFixtureEstate`)
- Test: `tests/run/test_estate_wrappers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/run/test_estate_wrappers.py
from pathlib import Path
from groundloop.core.types import RepoRef
from groundloop.adapters.estate import MockEstate, RecordingEstate, CheckoutEstate


def _catalog(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text('[{"name": "alpha"}, {"name": "beta"}]')
    return str(p)


def test_recording_estate_records_empty_vs_present(tmp_path):
    inner = MockEstate(_catalog(tmp_path), str(tmp_path / "work"))      # materialize -> empty dir
    est = RecordingEstate(inner)
    assert [r.name for r in est.catalog()] == ["alpha", "beta"]         # delegates
    wt = est.materialize(RepoRef("alpha"))
    out = est.outcome_for("alpha")
    assert out.repo == "alpha" and out.path == wt.path
    assert out.present is False and out.n_files == 0                    # empty work dir


def test_checkout_estate_materializes_snapshot(tmp_path):
    # a fake repo snapshot with one file
    snap = tmp_path / "repos" / "alpha"
    snap.mkdir(parents=True)
    (snap / "Main.kt").write_text("class Main")
    est = RecordingEstate(CheckoutEstate(_catalog(tmp_path), str(tmp_path / "repos"),
                                         str(tmp_path / "work")))
    assert [r.name for r in est.catalog()] == ["alpha", "beta"]
    wt = est.materialize(RepoRef("alpha"))
    assert (Path(wt.path) / "Main.kt").is_file()                       # real source checked out
    assert est.outcome_for("alpha").present is True
    # a repo with no snapshot -> empty, honest-abstain
    est.materialize(RepoRef("beta"))
    assert est.outcome_for("beta").present is False
```

- [ ] **Step 2: Run test to verify it fails** — `... pytest tests/run/test_estate_wrappers.py -q` → FAIL (no `RecordingEstate`/`CheckoutEstate`).

- [ ] **Step 3: Write minimal implementation** (append to `groundloop/adapters/estate.py`; reuse the existing imports `json`/`shutil`/`subprocess`/`Path`, and `RepoRef`/`WorkTree`)

```python
class RecordingEstate:
    """A RepoEstate decorator: delegates catalog()/materialize() to an inner estate and records a
    MaterializeOutcome (present, n_files) per materialize so the offline grader can judge fix
    gradeability without re-reading disk. Pure adapter — no core edit."""

    def __init__(self, inner):
        self.inner = inner
        self._outcomes: dict[str, "MaterializeOutcome"] = {}

    def catalog(self):
        return self.inner.catalog()

    def materialize(self, repo: RepoRef) -> WorkTree:
        from groundloop.run.record import MaterializeOutcome
        wt = self.inner.materialize(repo)
        d = Path(wt.path)
        n = 0
        if d.is_dir():
            for _ in d.rglob("*"):                 # capped: we only need present vs empty + a small count
                n += 1
                if n >= 2:                          # >=1 real entry beyond an empty dir is enough signal
                    break
        self._outcomes[repo.name] = MaterializeOutcome(repo=repo.name, path=str(d),
                                                       present=n > 0, n_files=n)
        return wt

    def outcome_for(self, name: str):
        return self._outcomes.get(name)


class CheckoutEstate(MockEstate):
    """Catalog from catalog.json (MockEstate) + a materialize() that checks out a plain-file repo
    snapshot from <fixtures_root>/<repo> into a fresh work-tree and git-inits it (the GitFixtureEstate
    recipe). No snapshot -> empty dir (honest localize/apply abstain). For `gloop run --repos`."""

    def __init__(self, catalog_path: str, fixtures_root: str, work_root: str):
        super().__init__(catalog_path, work_root)
        self.fixtures_root = Path(fixtures_root)

    def materialize(self, repo: RepoRef) -> WorkTree:
        dst = self.work_root / repo.name
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        src = self.fixtures_root / repo.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "run"],
                      ["add", "-A"], ["commit", "-q", "-m", "base"]):
                subprocess.run(["git", "-C", str(dst), *a], check=True)
        return WorkTree(repo=repo, path=str(dst))
```

Note the `MaterializeOutcome` `n_files` here is a capped indicator (0 = empty, ≥1 = present); `present` is the
load-bearing field. This avoids a full stat-walk of large checkouts.

- [ ] **Step 4: Run test to verify it passes** — `... pytest tests/run/test_estate_wrappers.py -q` → PASS.
- [ ] **Step 5: Commit** — `git add groundloop/adapters/estate.py tests/run/test_estate_wrappers.py && git commit -m "feat(estate): RecordingEstate (materialize outcomes) + CheckoutEstate (--repos)"`

---

## Task 3: Batch runner (`groundloop/run/batch.py`)

**Files:**
- Create: `groundloop/run/batch.py`
- Test: `tests/run/test_batch.py` (reuse `tests/conftest.py` fixtures if present; else build a tiny dataset inline)

`run_dataset` iterates `load_cases`, calls the frozen `run_ticket`, computes `patch_applies` against the
materialized worktree, and writes one record per case with the recorded outcome for `chosen`.

- [ ] **Step 1: Write the failing test**

```python
# tests/run/test_batch.py
import json
from pathlib import Path
from groundloop.core.types import RepoRef
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.adapters.estate import MockEstate, RecordingEstate
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.run.batch import run_dataset
from groundloop.run.record import RunRecordIO


class _StubIndex:
    def rank_repos(self, signals, catalog):
        from groundloop.core.types import RepoScore
        return [RepoScore(r, 1.0 - i * 0.1) for i, r in enumerate(catalog)]
    def retrieve(self, repo, query):
        return ["Main.kt"]


def _dataset(tmp_path):
    root = tmp_path / "ds"
    (root / "GEI-1").mkdir(parents=True)
    (root / "GEI-1" / "ticket.json").write_text(json.dumps(
        {"id": "GEI-1", "summary": "audio glitch", "description": "d", "component": "Audio", "logs": []}))
    (root / "GEI-1" / "_oracle").mkdir()
    (root / "GEI-1" / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "alpha", "expected_files": ["Main.kt"]}))     # BOOBY-TRAP: must not be read
    cat = root / "catalog.json"
    cat.write_text(json.dumps([{"name": "alpha"}, {"name": "beta"}]))
    return str(root), str(cat)


def test_run_dataset_writes_oracle_free_records(tmp_path):
    ds, cat = _dataset(tmp_path)
    out = tmp_path / "out"
    issues = MockJira(ds)
    estate = RecordingEstate(MockEstate(cat, str(tmp_path / "work")))
    n = run_dataset(ds, issues=issues, extractor=AndroidSignalExtractor(), estate=estate,
                    index=_StubIndex(), fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                    changes=MockGerrit(str(out / "changes.jsonl"), issues),
                    match_arm="component", out=str(out))
    assert n == 1
    doc = RunRecordIO.read(str(out / "runs" / "GEI-1.json"))
    assert doc.chosen == "alpha" and doc.locations == ["Main.kt"]
    assert doc.materialize.repo == "alpha"                             # outcome for CHOSEN attached
    blob = json.loads((out / "runs" / "GEI-1.json").read_text())
    assert "owning_repo" not in json.dumps(blob)                      # oracle-blind: never leaked
```

- [ ] **Step 2: Run test to verify it fails** — FAIL (no `groundloop.run.batch`).

- [ ] **Step 3: Write minimal implementation**

```python
# groundloop/run/batch.py
"""Oracle-blind batch driver for the real loop: for each case, run the frozen run_ticket and persist an
oracle-free run-record. Grading is a separate offline pass (gloop grade-run)."""
from __future__ import annotations

from groundloop.core.types import RepoRef
from groundloop.core.workflow import run_ticket
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.patch import patch_applies
from groundloop.run.record import MaterializeOutcome, RunRecordIO


def run_dataset(dataset: str, *, issues, extractor, estate, index, fixer, changes, match_arm: str,
                out: str) -> int:
    cases = load_cases(dataset)                                        # never reads _oracle/
    for case in cases:
        rec = run_ticket(case.case_id, issues=issues, extractor=extractor, estate=estate,
                         index=index, fixer=fixer, changes=changes)
        outcome = None
        if hasattr(estate, "outcome_for"):
            outcome = estate.outcome_for(rec.chosen.name)
        if outcome is None:                                           # non-recording estate fallback
            outcome = MaterializeOutcome(rec.chosen.name, "", False, 0)
        applies = patch_applies(rec.patch.diff, outcome.path) if outcome.present else False
        RunRecordIO.write(f"{out}/runs/{case.case_id}.json", rec, materialize=outcome,
                          match_arm=match_arm, patch_applies=applies)
    return len(cases)
```

- [ ] **Step 4: Run test to verify it passes** — PASS.
- [ ] **Step 5: Commit** — `git add groundloop/run/batch.py tests/run/test_batch.py && git commit -m "feat(run): oracle-blind run_dataset batch driver over the frozen run_ticket"`

*(If `AndroidSignalExtractor`'s import path differs, the implementer must grep `class AndroidSignalExtractor`
and use the real path — do not invent it.)*

---

## Task 4: Grader core — match + localize-as-run + auto counts (`groundloop/run/grade_run.py`)

**Files:**
- Create: `groundloop/run/grade_run.py`
- Test: `tests/run/test_grade_run_core.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/run/test_grade_run_core.py
import json
from pathlib import Path
from groundloop.run.record import RunRecordIO, MaterializeOutcome
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.grade_run import grade_run


def _write_case(ds_root, out_root, cid, ranked_names, chosen, locations, owning_repo, expected):
    cdir = Path(ds_root) / cid
    (cdir).mkdir(parents=True)
    (cdir / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                                  "component": "c", "logs": []}))
    (cdir / "_oracle").mkdir()
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owning_repo, "expected_files": expected}))
    patch = Patch(diff="", files=())
    rec = RunRecord(ticket_id=cid, ranked=[RepoScore(RepoRef(n), 1.0 - i * 0.1) for i, n in enumerate(ranked_names)],
                    chosen=RepoRef(chosen), locations=locations, patch=patch,
                    change=Change("gl", "s", cid, patch), bound=True, events=[])
    RunRecordIO.write(f"{out_root}/runs/{cid}.json", rec,
                      materialize=MaterializeOutcome(chosen, "", False, 0), match_arm="flood",
                      patch_applies=False)


def test_match_and_localize_as_run(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    _write_case(ds, out, "A", ["alpha", "beta"], "alpha", ["Main.kt"], "alpha", ["Main.kt"])  # match hit, loc hit
    _write_case(ds, out, "B", ["beta", "alpha"], "beta", ["Zzz.kt"], "alpha", ["Main.kt"])    # match miss, loc miss
    card = grade_run(out, ds)
    m = card["overall"]["match"]
    assert m["recall@1"] == 0.5 and m["n"] == 2                        # 1 of 2 -> AUTOMATIC count
    lz = card["overall"]["localize"]
    assert lz["as_run"]["file@1"] == 0.5                              # A hit on chosen, B missed
    assert card["overall"]["counts"]["match_hits@1"] == 1             # explicit tally == recall*n
```

- [ ] **Step 2: Run test to verify it fails** — FAIL.

- [ ] **Step 3: Write minimal implementation** (part A — the `grade_run` skeleton + `_grade_subset` for match & as-run localize; fix and isolated come in Tasks 5–6)

```python
# groundloop/run/grade_run.py
"""Offline per-stage grader over run-records — the SOLE oracle read (load_eval_oracle), mirroring
fixeval. Emits match / localize(as-run + isolated) / fix(or honest-abstain) with automatic counts and a
by_bug_kind split. Never re-runs the loop; the only re-execution is the isolated-localize diagnostic."""
from __future__ import annotations

from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.metrics import recall_at_k, repo_rank
from groundloop.fixeval.patch import norm_path
from groundloop.run.record import RunRecordIO

_KS = (1, 3, 5)


def _match_block(rows):
    n = len(rows)
    hits = {k: sum(recall_at_k(r["ranked_names"], {r["owner"]}, k) for r in rows) for k in _KS}
    return {"n": n, **{f"recall@{k}": (hits[k] / n if n else 0.0) for k in _KS},
            "_hits1": hits[1]}


def _localize_as_run(rows):
    loc = [r for r in rows if r["expected"]]
    n = len(loc)
    def fk(k):
        if not n:
            return None
        return sum(recall_at_k([norm_path(x) for x in r["locations"]],
                               {norm_path(e) for e in r["expected"]}, k) for r in loc) / n
    return {f"file@{k}": fk(k) for k in _KS}


def _grade_subset(rows):
    mb = _match_block(rows)
    return {
        "match": {"n": mb["n"], **{f"recall@{k}": mb[f"recall@{k}"] for k in _KS},
                  "recall_rank_avg": (sum(r["rank"] for r in rows) / len(rows)) if rows else 0.0},
        "localize": {"as_run": _localize_as_run(rows), "isolated": None},   # isolated filled in Task 6
        "fix": None,                                                        # filled in Task 5
        "counts": {"n": mb["n"], "match_hits@1": round(mb["_hits1"])},
    }


def grade_run(runs_dir: str, dataset: str, *, index_db: str | None = None) -> dict:
    cases = load_cases(dataset)
    rows = []
    for c in cases:
        doc = RunRecordIO.read(f"{runs_dir}/runs/{c.case_id}.json")
        o = load_eval_oracle(c)                                        # the ONLY oracle read
        rows.append({
            "case_id": c.case_id, "case": c, "doc": doc, "owner": o.owning_repo,
            "bug_kind": o.bug_kind, "expected": list(o.expected_files),
            "ranked_names": [x["repo"] for x in doc.ranked],
            "rank": repo_rank([x["repo"] for x in doc.ranked], o.owning_repo),
            "locations": list(doc.locations),
        })
    card = {"n_cases": len(rows), "overall": _grade_subset(rows)}
    return card
```

- [ ] **Step 4: Run test to verify it passes** — PASS.
- [ ] **Step 5: Commit** — `git add groundloop/run/grade_run.py tests/run/test_grade_run_core.py && git commit -m "feat(run): grade_run core — match recall@k + as-run localize + automatic counts"`

---

## Task 5: Grader fix stage — honest-abstain + `grade_fix_all` reuse

**Files:**
- Modify: `groundloop/run/grade_run.py`
- Test: `tests/run/test_grade_run_fix.py`

Build a `FixRecord` per row and reuse `fixeval.scorecard.grade_fix_all`; exclude `materialize.present ==
False` rows as `UNGRADEABLE(no_source)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/run/test_grade_run_fix.py — extends the Task-4 harness
import json
from pathlib import Path
from groundloop.run.record import RunRecordIO, MaterializeOutcome
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.grade_run import grade_run


def _case(ds, out, cid, present, diff, files, owner, expected, applies):
    cdir = Path(ds) / cid; cdir.mkdir(parents=True)
    (cdir / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                                  "component": "c", "logs": []}))
    (cdir / "_oracle").mkdir()
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": expected, "required_apis": []}))
    patch = Patch(diff=diff, files=tuple(files))
    rec = RunRecord(ticket_id=cid, ranked=[RepoScore(RepoRef(owner), 0.9)], chosen=RepoRef(owner),
                    locations=list(files), patch=patch, change=Change("g", "s", cid, patch),
                    bound=True, events=[])
    RunRecordIO.write(f"{out}/runs/{cid}.json", rec,
                      materialize=MaterializeOutcome(owner, "/w", present, 3 if present else 0),
                      match_arm="flood", patch_applies=applies)


def test_empty_worktree_is_ungradeable_not_localization(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    # fabricated patch on an EMPTY worktree — the exact 10-case bug
    _case(ds, out, "E", present=False, diff="--- a/system/core/init/init.cpp\n+++ b/..\n",
          files=["system/core/init/init.cpp"], owner="alpha", expected=["Real.kt"], applies=False)
    fix = grade_run(out, ds)["overall"]["fix"]
    assert fix["n_ungradeable_no_source"] == 1
    assert fix["n_gradeable"] == 0
    # the fabricated file must NOT count as a localization hit anywhere
    assert fix["resolved_rate_strict"]["value"] in (None, 0.0)


def test_present_worktree_is_graded(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    _case(ds, out, "G", present=True, diff="--- a/Real.kt\n+++ b/Real.kt\n@@ -1 +1 @@\n-a\n+b\n",
          files=["Real.kt"], owner="alpha", expected=["Real.kt"], applies=True)
    fix = grade_run(out, ds)["overall"]["fix"]
    assert fix["n_gradeable"] == 1 and fix["n_ungradeable_no_source"] == 0
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement** — add a fix block to `grade_run.py`; feed the present-subset into `grade_fix_all`.

```python
# add to groundloop/run/grade_run.py
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all


def _fix_record(row):
    doc = row["doc"]
    return FixRecord(
        case_id=row["case_id"], arm="run", predicted_repo=doc.chosen, locations=list(doc.locations),
        patch_diff=doc.patch["diff"], patch_files=list(doc.patch["files"]),
        patch_emitted=bool(doc.patch["diff"].strip()), patch_applies=bool(doc.patch_applies),
        abstained=not bool(doc.patch["diff"].strip()), abstain_reason=None, refine_iters=0,
        cost_usd=0.0)


def _fix_block(rows, oracle_by_case):
    gradeable = [r for r in rows if r["doc"].materialize.present]
    ungradeable = [r for r in rows if not r["doc"].materialize.present]
    if not gradeable:
        return {"n_gradeable": 0, "n_ungradeable_no_source": len(ungradeable),
                "resolved_rate_strict": {"value": None, "n": 0},
                "fabrication_rate": {"value": None, "n": 0}, "patch_apply_rate": None}
    recs = [_fix_record(r) for r in gradeable]
    card = grade_fix_all(recs, oracle_by_case={r["case_id"]: oracle_by_case[r["case_id"]] for r in gradeable})
    arm = card["arms"]["run"]
    return {"n_gradeable": len(gradeable), "n_ungradeable_no_source": len(ungradeable),
            "file_recall@1": arm["file_recall@1"], "resolved_rate_strict": arm["resolved_rate_strict"],
            "fabrication_rate": arm["fabrication_rate"], "patch_apply_rate": arm["patch_apply_rate"]}
```

Thread `oracle_by_case` through `_grade_subset(rows, oracle_by_case)` and set `"fix": _fix_block(rows,
oracle_by_case)`. Build `oracle_by_case = {r["case_id"]: <EvalOracle from row> }` in `grade_run` (reuse the
already-loaded oracle — store `o` on the row as `row["oracle"]`).

- [ ] **Step 4: Run to verify it passes** — PASS.
- [ ] **Step 5: Commit** — `git add groundloop/run/grade_run.py tests/run/test_grade_run_fix.py && git commit -m "feat(run): fix grading via FixRecord+grade_fix_all with honest UNGRADEABLE(no_source)"`

---

## Task 6: Grader — isolated-localize diagnostic + by_bug_kind + markdown

**Files:**
- Modify: `groundloop/run/grade_run.py`
- Create: `groundloop/run/report.py` (the per-case markdown table)
- Test: `tests/run/test_grade_run_diag.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/run/test_grade_run_diag.py
import json
from pathlib import Path
from groundloop.run.record import RunRecordIO, MaterializeOutcome
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.grade_run import grade_run
from groundloop.run.report import render_run_markdown


class _FakeAtlas:
    """Stand-in for AtlasIndex: retrieve(repo, query) returns the oracle file only for the oracle repo."""
    def __init__(self, db): pass
    def retrieve(self, repo, query):
        return ["Real.kt"] if repo.name == "alpha" else ["Wrong.kt"]


def _case(ds, out, cid, chosen, owner, as_run_loc, expected, bug_kind):
    cdir = Path(ds) / cid; cdir.mkdir(parents=True)
    (cdir / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                                  "component": "c", "logs": []}))
    (cdir / "_oracle").mkdir()
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": expected, "bug_kind": bug_kind}))
    patch = Patch(diff="", files=())
    rec = RunRecord(ticket_id=cid, ranked=[RepoScore(RepoRef(chosen), 0.9)], chosen=RepoRef(chosen),
                    locations=as_run_loc, patch=patch, change=Change("g", "s", cid, patch),
                    bound=True, events=[])
    RunRecordIO.write(f"{out}/runs/{cid}.json", rec,
                      materialize=MaterializeOutcome(chosen, "", False, 0), match_arm="flood",
                      patch_applies=False)


def test_isolated_localize_differs_from_as_run(tmp_path, monkeypatch):
    import groundloop.run.grade_run as gr
    monkeypatch.setattr(gr, "AtlasIndex", _FakeAtlas)
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    # match MISSED (chosen=beta != owner=alpha): as-run localize runs on beta -> "Wrong.kt" (miss),
    # but the isolated diagnostic runs on the oracle repo alpha -> "Real.kt" (hit)
    _case(ds, out, "M", chosen="beta", owner="alpha", as_run_loc=["Wrong.kt"], expected=["Real.kt"],
          bug_kind="functional")
    card = grade_run(out, ds, index_db="atlas.db")
    assert card["overall"]["localize"]["as_run"]["file@1"] == 0.0     # contaminated by match miss
    assert card["overall"]["localize"]["isolated"]["file@1"] == 1.0   # the "7/10 not 0/10" correction
    assert "functional" in card["by_bug_kind"]
    md = render_run_markdown(card)
    assert "| M |" in md and "isolated" in md.lower()
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement**
  - In `grade_run.py`: `from groundloop.adapters.index.atlas import AtlasIndex` (module-level, so the test can
    monkeypatch `gr.AtlasIndex`). Add `_localize_isolated(rows, index_db)`: build one `AtlasIndex(index_db)`,
    and for each row with `expected`, call `idx.retrieve(RepoRef(row["owner"]), row["query"])` (the query is
    the ticket `summary`, read loop-visibly via the case dir's `ticket.json`), then `recall_at_k` vs
    `expected`. Set `localize["isolated"]` only when `index_db` is not None (else stays `None`).
  - Add `by_bug_kind`: `card["by_bug_kind"] = {bk: _grade_subset([r for r in rows if r["bug_kind"] == bk], ...)
    for bk in sorted({r["bug_kind"] for r in rows if r["bug_kind"]})}`. Each subset also gets the isolated
    block when `index_db` given.
  - `groundloop/run/report.py`: `render_run_markdown(card) -> str` — a header with the overall per-stage
    numbers + a per-case table `| case | arm-rank | localize as-run@1 | localize isolated@1 | fix |`. Reuse
    the shape of `docs/2026-07-11-functional-10case-e2e-findings.md`. Keep it dependency-free (string build).

  Read the ticket summary loop-visibly (add to each row in `grade_run`): `row["query"] = json.loads((Path
  (c.case_dir)/"ticket.json").read_text()).get("summary", "")`.

- [ ] **Step 4: Run to verify it passes** — PASS.
- [ ] **Step 5: Commit** — `git add groundloop/run/grade_run.py groundloop/run/report.py tests/run/test_grade_run_diag.py && git commit -m "feat(run): isolated-localize diagnostic + by_bug_kind split + per-case markdown"`

---

## Task 7: CLI wiring — `gloop run` batch mode + `gloop grade-run`

**Files:**
- Modify: `groundloop/cli/__init__.py` (the `run` subparser + dispatch at ~983 / ~1190; add a `grade-run` subparser + `_run_grade_run`)
- Test: `tests/run/test_cli_selfscore.py`

- [ ] **Step 1: Write the failing test** — a hermetic CLI smoke that runs the batch (canned) then grades it,
  building a 1-case dataset + a fixture atlas via the shared `tests/conftest.py` helpers if available (else a
  stub index path and `--index-db` omitted so `isolated` stays None).

```python
# tests/run/test_cli_selfscore.py  (sketch — implementer fills dataset via conftest atlas_harness if present)
from groundloop.cli import main


def test_run_batch_then_grade(tmp_path, monkeypatch, capsys, /):
    # ... build ds + catalog + an atlas fixture (reuse conftest.build_atlas_fixture) ...
    # gloop run --dataset ds --catalog cat --index-db atlas --match-arm flood --work W --changes ch --out RUN
    rc = main(["run", "--dataset", DS, "--catalog", CAT, "--index-db", ATLAS,
               "--work", str(tmp_path / "w"), "--changes", str(tmp_path / "ch.jsonl"),
               "--out", str(tmp_path / "run")])
    assert rc == 0 and (tmp_path / "run" / "runs").is_dir()
    # gloop grade-run --runs RUN --dataset ds --index-db atlas --out card.json
    rc = main(["grade-run", "--runs", str(tmp_path / "run"), "--dataset", DS,
               "--index-db", ATLAS, "--out", str(tmp_path / "card.json")])
    assert rc == 0 and (tmp_path / "card.json").is_file()
    assert (tmp_path / "card.md").is_file()
```

- [ ] **Step 2: Run to verify it fails** — FAIL.

- [ ] **Step 3: Implement (composition root)**
  - `run` subparser: make `--case` **optional** (remove from the required loop; add it as an optional arg
    with the other flags). Add `--out` (batch output dir), `--repos` (default `""`), `--fixer` (choices
    `["canned", "model"]`, default `"canned"`). Keep `--dataset`/`--catalog`/`--work`/`--changes` and the
    index group required.
  - Dispatch: in the `run` branch, after building `index`/`extractor` (unchanged arm logic), branch:
    - if `args.case`: keep the existing single-case path verbatim (back-compat).
    - elif `args.out`: batch. Build the estate — `RecordingEstate(CheckoutEstate(catalog, repos, work))` when
      `args.repos` else `RecordingEstate(MockEstate(catalog, work))`. Build the fixer — `canned` →
      `CannedFixEngine(CannedModel({"default": "patch"}))`; `model` → `ModelPatchEngine(GatewayModel(...))`
      built from `Settings.load()` exactly like `_run_fixeval:281-288` (fall back to a canned empty model
      with a printed warning if `KLOOP_PRODUCE_API_KEY` is unset). Call `run_dataset(...)`, print
      `runs written: N -> <out>/runs`.
    - else: `print("gloop run: pass --case <id> or --out <dir> (batch)")`, `return 2`.
  - `grade-run` subparser + `_run_grade_run(args)`: `--runs`, `--dataset`, `--index-db` (optional), `--out`
    required. Call `grade_run(args.runs, args.dataset, index_db=args.index_db or None)`, write `card.json` +
    `card.md` (`render_run_markdown`), print the overall one-liner (match recall@1, localize as-run/isolated
    @1, fix n_gradeable/n_ungradeable). Add `if args.cmd == "grade-run": return _run_grade_run(args)`.

- [ ] **Step 4: Run to verify it passes** — PASS; also run the FULL suite `.venv/bin/python -m pytest -q`.
- [ ] **Step 5: Commit** — `git add groundloop/cli/__init__.py tests/run/test_cli_selfscore.py && git commit -m "feat(cli): gloop run batch mode (--out/--repos/--fixer) + gloop grade-run"`

---

## Task 8: Anti-leak invariants + docs

**Files:**
- Modify: `tests/test_invariants.py` (add the run-record/grader invariants), `docs/production-migration.md`
  (runbook step), `docs/STATUS.md` (a Done entry)
- Test: the invariants live in `tests/test_invariants.py`

- [ ] **Step 1: Write the failing invariant tests**

```python
# add to tests/test_invariants.py
def test_run_record_has_no_oracle_fields(tmp_path):
    """A written run-record must never contain owning_repo/expected_files/required_apis."""
    # build a 1-case dataset with a booby-trapped oracle, run_dataset, assert no oracle key in runs/*.json
    ...

def test_grade_run_is_sole_oracle_reader():
    """groundloop/run/batch.py must NOT import load_eval_oracle/load_oracle; grade_run.py may."""
    import pathlib
    batch = pathlib.Path("groundloop/run/batch.py").read_text()
    assert "load_eval_oracle" not in batch and "_oracle" not in batch
    grade = pathlib.Path("groundloop/run/grade_run.py").read_text()
    assert "load_eval_oracle" in grade                                # the sole reader
```

- [ ] **Step 2: Run to verify it fails** (or is red where expected) — the source-scan asserts should pass
  immediately if the code is clean; the dataset round-trip may need the helper. Confirm both run.

- [ ] **Step 3: Implement / finalize** — make the invariants pass (they should, by construction). Then docs:
  - `docs/production-migration.md`: add a section "Self-scoring the run" — `gloop run --dataset <10case>
    --catalog … --index-db $ATLAS --match-arm component --affinity … --repos <19-repo-mirror> --fixer model
    --out run-10` → `gloop grade-run --runs run-10 --dataset <10case> --index-db $ATLAS --out card.json`;
    note that `--repos` at the real mirror makes fix gradeable, and the scorecard replaces hand-tallying.
  - `docs/STATUS.md`: a "Self-scoring pipeline" Done entry pointing at the spec + this plan.

- [ ] **Step 4: Run the FULL suite + ruff** — `.venv/bin/python -m pytest -q` green; `.venv/bin/ruff check groundloop tests` clean.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "test(run): anti-leak invariants (oracle-free record, sole grader reader) + docs"`

---

## Verification (end-to-end acceptance)

1. **Persisted, oracle-free:** `gloop run --dataset … --out RUN` writes one `runs/<case>.json` per case
   carrying `locations` + `patch` + `patch_applies` + `materialize`, and **no oracle field** (red-tested).
2. **Per-stage scorecard:** `gloop grade-run --runs RUN --dataset … --index-db …` emits match
   `recall@1/@3/@5`, localize **as-run + isolated** `file@k`, fix `resolved_strict`/`fabrication` with an
   explicit `n_ungradeable_no_source`, a `by_bug_kind` split, and a `card.md` per-case table.
3. **The two 10-case failures are structurally impossible:** match counts are automatic (a `counts` block ==
   `recall*n`); a fabricated patch on an empty worktree is `UNGRADEABLE(no_source)`, never a localization
   (regression-locked in `test_grade_run_fix.py`); the isolated diagnostic reproduces "localize 7/10 not
   0/10" (`test_grade_run_diag.py`).
4. **Frozen/gated zero-diff:** no `groundloop/core/`, no `engines/atlas/store.py` schema, no
   `adapters/index/atlas.py::rank_repos`, no `owner_tokens.py`/`repo_routing.py`/`mine/`. `MockEstate`/
   `GitFixtureEstate` untouched (only additive `RecordingEstate`/`CheckoutEstate`).
5. **Green + clean:** full hermetic `pytest -q` + `ruff check` before the final merge.

## Critical files

- `groundloop/run/{record.py,batch.py,grade_run.py,report.py}` — the new units (+ `run/__init__.py`).
- `groundloop/adapters/estate.py` — additive `RecordingEstate` + `CheckoutEstate`.
- `groundloop/cli/__init__.py` — `run` batch mode + `grade-run` (composition root).
- Reused verbatim: `core.workflow.run_ticket`/`RunRecord`; `eval.dataset.{load_cases,load_eval_oracle}`;
  `eval.metrics.{recall_at_k,repo_rank}`; `fixeval.runner.FixRecord`; `fixeval.scorecard.grade_fix_all`;
  `fixeval.patch.{patch_applies,norm_path}`; `adapters/estate.{MockEstate,GitFixtureEstate}`.
