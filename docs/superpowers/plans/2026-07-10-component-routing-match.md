# Stage-1 Match via Component Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a JIRA-component→repo affinity prior as an additive Stage-1 match re-ranker (`ComponentPriorIndex`), with an offline affinity miner, a leave-one-out eval path (no train/test leak), and a synthetic-component proxy mechanism check — so production can run the real affinity build + 406-case LOO eval.

**Architecture:** A frozen-safe bolt-on. The component rides through the frozen `Signals` seam as a reserved `COMPONENT_MARK` token (`ComponentExtractor`); `ComponentPriorIndex` reads it, **strips it before the base index**, and adds `weight * affinity(component)[repo]` to the base scores. The affinity table is raw co-occurrence counts (so leave-one-out subtracts a case's own contribution exactly). The runtime index is **loop-blind** (reads only the component + the table); LOO is applied offline by the eval harness via a per-case `_LOOView`. Zero LLM/embed cost in the arm.

**Tech Stack:** Python 3.12, pytest, ruff. Spec: `docs/superpowers/specs/2026-07-10-component-routing-match-design.md`.

Tests: `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check groundloop tests`. Keep every line ≤110. Commit only when green + ruff clean; end messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

**Frozen / gated — never edit (may READ):** `groundloop/core/`, `engines/atlas/store.py` schema, `adapters/index/atlas.py` `rank_repos`, `owner_tokens.py`, `repo_routing.py`, all of `mine/` (the affinity miner is a NEW module under `domains/`, not an edit to the GitHub miner).

---

## Task 1: `ComponentAffinity` loader + leave-one-out

**Files:**
- Create: `groundloop/domains/android_ivi/component_affinity.py`
- Test: `tests/domains/test_component_affinity.py`

- [ ] **Step 1: Write the failing test**

```python
from groundloop.domains.android_ivi.component_affinity import ComponentAffinity


def _aff():
    return ComponentAffinity({"CarPlay": {"Core": 3, "Integ": 1}, "Audio": {"AudioSvc": 2}})


def test_affinity_normalizes():
    a = _aff().affinity("CarPlay")
    assert abs(a["Core"] - 0.75) < 1e-9 and abs(a["Integ"] - 0.25) < 1e-9


def test_affinity_leave_one_out_subtracts_one():
    a = _aff().affinity("CarPlay", exclude="Core")   # Core 3->2, Integ 1 -> total 3
    assert abs(a["Core"] - 2 / 3) < 1e-9 and abs(a["Integ"] - 1 / 3) < 1e-9


def test_affinity_loo_removes_sole_contributor():
    assert _aff().affinity("Audio", exclude="AudioSvc") == {}   # only contributor removed -> empty


def test_affinity_unknown_component_is_empty():
    assert _aff().affinity("Nope") == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/domains/test_component_affinity.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/domains/android_ivi/component_affinity.py`:

```python
"""Empirical JIRA-component -> owning-repo affinity prior. Stores RAW co-occurrence counts so
leave-one-out can subtract a case's own contribution before normalizing. Runtime reads only the
loop-visible component; the LOO `exclude` argument is eval/grader-side only (never the loop path)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ComponentAffinity:
    counts: dict[str, dict[str, int]]

    @classmethod
    def load(cls, path: str) -> "ComponentAffinity":
        raw = json.loads(Path(path).read_text())
        return cls({c: {r: int(n) for r, n in repos.items()} for c, repos in raw.items()})

    def affinity(self, component: str, *, exclude: str | None = None) -> dict[str, float]:
        """L1-normalized repo weights for `component`. If `exclude` is a repo, subtract one unit of
        its count first (leave-one-out). Unknown component / zero total -> empty."""
        repos = dict(self.counts.get(component, {}))
        if exclude and exclude in repos:
            repos[exclude] -= 1
            if repos[exclude] <= 0:
                del repos[exclude]
        total = sum(repos.values())
        if total <= 0:
            return {}
        return {r: n / total for r, n in repos.items() if n > 0}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/domains/test_component_affinity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/domains/android_ivi/component_affinity.py tests/domains/test_component_affinity.py
git commit -m "feat(android): ComponentAffinity — empirical component->repo prior with leave-one-out"
```

---

## Task 2: Offline affinity miner + `gloop mine-affinity`

**Files:**
- Create: `groundloop/domains/android_ivi/mine_component_affinity.py`
- Modify: `groundloop/cli/__init__.py` (`_run_mine_affinity` + subparser + dispatch)
- Test: `tests/domains/test_mine_component_affinity.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from groundloop.domains.android_ivi.mine_component_affinity import build_affinity


def _case(root, cid, component, owner, answerable=True):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                               "component": component}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "is_answerable": answerable}))


def test_build_affinity_counts_cooccurrence(tmp_path):
    _case(tmp_path, "a", "CarPlay", "Core")
    _case(tmp_path, "b", "CarPlay", "Core")
    _case(tmp_path, "c", "CarPlay", "Integ")
    _case(tmp_path, "d", "Audio", "AudioSvc")
    counts = build_affinity(str(tmp_path))
    assert counts["CarPlay"] == {"Core": 2, "Integ": 1}
    assert counts["Audio"] == {"AudioSvc": 1}


def test_build_affinity_skips_empty_component_and_negatives(tmp_path):
    _case(tmp_path, "e", "", "Core")                       # no component
    _case(tmp_path, "f", "WLAN", "__NOT_A_DEFECT__")       # negative owner
    _case(tmp_path, "g", "WLAN", "Net", answerable=False)  # unanswerable
    assert build_affinity(str(tmp_path)) == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/domains/test_mine_component_affinity.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/domains/android_ivi/mine_component_affinity.py`:

```python
"""Offline: build the component -> owning_repo affinity table from a dataset's loop-visible
ticket.component + offline oracle owning_repo. Population statistics, not per-ticket memory. Runs on
production over the full oracle; a standalone module (NOT the gated groundloop/mine/)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

_NEG_OWNERS = {"__NOT_A_DEFECT__", "__OUT_OF_FLEET__"}


def build_affinity(dataset_root: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in sorted(Path(dataset_root).iterdir()):
        tp, op = d / "ticket.json", d / "_oracle" / "oracle.json"
        if not (tp.is_file() and op.is_file()):
            continue
        comp = (json.loads(tp.read_text()).get("component") or "").strip()
        oracle = json.loads(op.read_text())
        owner = oracle.get("owning_repo")
        if not comp or not owner or owner in _NEG_OWNERS or not oracle.get("is_answerable", True):
            continue
        counts[comp][owner] += 1
    return {c: dict(repos) for c, repos in counts.items()}


def write_affinity(dataset_root: str, out_path: str) -> int:
    counts = build_affinity(dataset_root)
    Path(out_path).write_text(json.dumps(counts, indent=2, ensure_ascii=False, sort_keys=True))
    return sum(sum(r.values()) for r in counts.values())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/domains/test_mine_component_affinity.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the CLI** — in `groundloop/cli/__init__.py` add:

```python
def _run_mine_affinity(args) -> int:
    from groundloop.domains.android_ivi.mine_component_affinity import write_affinity
    n = write_affinity(args.dataset, args.out)
    print(f"mine-affinity: {n} (component,owner) pairs -> {args.out}")
    return 0
```

Subparser (near `mine`):

```python
    ma = sub.add_parser("mine-affinity", help="offline: build component->repo affinity json from a dataset")
    ma.add_argument("--dataset", required=True, help="dataset root (ticket.json component + _oracle owner)")
    ma.add_argument("--out", required=True, help="component_affinity.json output path")
```

Dispatch (in `main`):

```python
    if args.cmd == "mine-affinity":
        return _run_mine_affinity(args)
```

- [ ] **Step 6: Test the CLI + commit** — append:

```python
def test_cli_mine_affinity(tmp_path, capsys):
    import groundloop.cli as cli
    _case(tmp_path, "a", "CarPlay", "Core")
    out = tmp_path / "aff.json"
    assert cli.main(["mine-affinity", "--dataset", str(tmp_path), "--out", str(out)]) == 0
    assert out.exists() and "1 (component,owner)" in capsys.readouterr().out
```

Run: `.venv/bin/python -m pytest tests/domains/test_mine_component_affinity.py -q && .venv/bin/ruff check groundloop tests`

```bash
git add groundloop/domains/android_ivi/mine_component_affinity.py groundloop/cli/__init__.py tests/domains/test_mine_component_affinity.py
git commit -m "feat(cli): gloop mine-affinity — offline component->repo affinity table builder"
```

---

## Task 3: `ComponentExtractor` + `component_of` / `strip_component`

**Files:**
- Create: `groundloop/domains/android_ivi/component_signals.py`
- Test: `tests/domains/test_component_signals.py`

- [ ] **Step 1: Write the failing test**

```python
from groundloop.core.types import Signals, Ticket
from groundloop.domains.android_ivi.component_signals import (
    COMPONENT_MARK, ComponentExtractor, component_of, strip_component)


class _Base:
    def extract(self, logs, ticket):
        return Signals(classes=("Foo",), errors=("NullPointerException",))


def test_extractor_appends_component_marker():
    sig = ComponentExtractor(_Base()).extract((), Ticket("t", "s", "d", component="CarPlay"))
    assert component_of(sig) == "CarPlay"
    assert "NullPointerException" in sig.errors            # base tokens preserved
    assert sig.classes == ("Foo",)


def test_strip_component_removes_marker_only():
    sig = ComponentExtractor(_Base()).extract((), Ticket("t", "s", "d", component="Audio"))
    stripped = strip_component(sig)
    assert component_of(stripped) == "" and "NullPointerException" in stripped.errors
    assert not any(e.startswith(COMPONENT_MARK) for e in stripped.errors)


def test_empty_component_is_noop():
    sig = ComponentExtractor(_Base()).extract((), Ticket("t", "s", "d", component=""))
    assert component_of(sig) == "" and sig.errors == ("NullPointerException",)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/domains/test_component_signals.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/domains/android_ivi/component_signals.py`:

```python
"""Carry the JIRA component through the frozen Signals seam for the component-prior re-ranker. The
component rides as a reserved COMPONENT_MARK token in Signals.errors; ComponentPriorIndex reads it
(component_of) and strips it (strip_component) before the base index sees the query."""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket

COMPONENT_MARK = "\x00comp\x00"


def component_of(signals: Signals) -> str:
    for e in signals.errors:
        if e.startswith(COMPONENT_MARK):
            return e[len(COMPONENT_MARK):]
    return ""


def strip_component(signals: Signals) -> Signals:
    return replace(signals, errors=tuple(e for e in signals.errors if not e.startswith(COMPONENT_MARK)))


class ComponentExtractor:
    """Wraps a base SignalExtractor; appends the ticket's JIRA component as a reserved marker token."""

    def __init__(self, base):
        self.base = base

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        sig = self.base.extract(logs, ticket)
        comp = (ticket.component or "").strip()
        if not comp:
            return sig
        return replace(sig, errors=sig.errors + (COMPONENT_MARK + comp,))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/domains/test_component_signals.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/domains/android_ivi/component_signals.py tests/domains/test_component_signals.py
git commit -m "feat(android): ComponentExtractor — carry JIRA component through the Signals seam"
```

---

## Task 4: `ComponentPriorIndex` (additive re-ranker)

**Files:**
- Create: `groundloop/adapters/index/component_prior.py`
- Test: `tests/index/test_component_prior.py`

- [ ] **Step 1: Write the failing test**

```python
from groundloop.adapters.index.component_prior import ComponentPriorIndex
from groundloop.domains.android_ivi.component_affinity import ComponentAffinity
from groundloop.domains.android_ivi.component_signals import COMPONENT_MARK
from groundloop.core.types import RepoRef, RepoScore, Signals

CAT = [RepoRef("Core"), RepoRef("Integ"), RepoRef("Noise")]


class _Base:
    """Ranks by a fixed score map; strips nothing. Records the signals it was handed."""
    def __init__(self, scores):
        self.scores = scores
        self.seen = None

    def rank_repos(self, signals, catalog):
        self.seen = signals
        return sorted((RepoScore(r, self.scores.get(r.name, 0.0)) for r in catalog),
                      key=lambda s: s.score, reverse=True)

    def retrieve(self, repo, query):
        return ["f"]


def _sig(component):
    return Signals(errors=(COMPONENT_MARK + component,)) if component else Signals()


def test_prior_boosts_component_repo_and_strips_marker():
    base = _Base({"Noise": 1.0, "Core": 0.1})            # base alone ranks Noise first
    aff = ComponentAffinity({"CarPlay": {"Core": 4, "Integ": 1}})
    idx = ComponentPriorIndex(base, aff, weight=1.0)
    ranked = idx.rank_repos(_sig("CarPlay"), CAT)
    assert ranked[0].repo.name == "Core"                 # prior overturns the size-biased base
    assert not any(e.startswith(COMPONENT_MARK) for e in base.seen.errors)  # base never saw the marker


def test_no_component_is_pure_base():
    base = _Base({"Noise": 1.0})
    idx = ComponentPriorIndex(base, ComponentAffinity({}), weight=1.0)
    assert idx.rank_repos(_sig(""), CAT)[0].repo.name == "Noise"


def test_retrieve_delegates():
    idx = ComponentPriorIndex(_Base({}), ComponentAffinity({}), weight=1.0)
    assert idx.retrieve(RepoRef("Core"), "q") == ["f"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_component_prior.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/adapters/index/component_prior.py`:

```python
"""ComponentPriorIndex: additive JIRA-component->repo prior on top of any base CodeIndex. Reads the
component from the reserved Signals marker, strips it before the base (so the component string never
enters the base FTS/cosine query and can't be double-counted), and boosts base scores by the affinity
weight. A CodeIndex swapped at the composition root; loop-blind — reads only the component + the
affinity object it was given (the LOO exclusion lives in an eval-side affinity view, not here)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.component_signals import component_of, strip_component

_COMPONENT_WEIGHT = 1.0    # calibration seed; prior should dominate ranking (recall@3=0.90). Frozen on prod.


class ComponentPriorIndex:
    def __init__(self, base_index, affinity, *, weight: float = _COMPONENT_WEIGHT):
        self.base = base_index
        self.affinity = affinity                 # any object exposing .affinity(component) -> {repo: weight}
        self.weight = weight

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        comp = component_of(signals)
        ranked = self.base.rank_repos(strip_component(signals), catalog)
        boost = self.affinity.affinity(comp) if comp else {}
        allowed = {r.name for r in catalog}
        out = [RepoScore(rs.repo, rs.score + self.weight * boost.get(rs.repo.name, 0.0), rs.evidence)
               for rs in ranked if rs.repo.name in allowed]
        out.sort(key=lambda s: s.score, reverse=True)
        return out

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self.base.retrieve(repo, query)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_component_prior.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/index/component_prior.py tests/index/test_component_prior.py
git commit -m "feat(index): ComponentPriorIndex — additive component prior re-ranker (loop-blind)"
```

---

## Task 5: `component` funceval arm + `--affinity`/`--loo` + LOO pass + red-tests

**Files:**
- Modify: `groundloop/funceval/runner.py` (component records + LOO view), `groundloop/funceval/arms.py` (optional), `groundloop/cli/__init__.py` (`funceval --affinity/--loo`)
- Test: `tests/funceval/test_component_arm.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.funceval.runner import run_funceval


def _case(ds, cid, component, owner):
    d = ds / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "x", "description": "x",
                                               "component": component}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "is_answerable": True, "bug_kind": "functional"}))


def _setup(tmp_path):
    ds = tmp_path / "ds"
    _case(ds, "c1", "MapUI", "organicmaps")
    _case(ds, "c2", "MapUI", "organicmaps")
    _case(ds, "c3", "CamUI", "cameraview")
    (ds / "catalog.json").write_text(json.dumps(
        [{"name": "organicmaps"}, {"name": "cameraview"}, {"name": "android-gpuimage-plus"}]))
    aff = tmp_path / "aff.json"
    aff.write_text(json.dumps({"MapUI": {"organicmaps": 2}, "CamUI": {"cameraview": 1}}))
    return ds, aff, build_atlas_fixture(str(tmp_path / "a.db"))


def test_component_arm_full_table_ranks_owner(tmp_path):
    ds, aff, atlas = _setup(tmp_path)
    from groundloop.engines.atlas.embed import StubEmbedder
    prof = build_atlas_fixture(str(tmp_path / "p.db"))     # reuse fixture as a stand-in profile db
    card = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                        arms=("component",), affinity_path=str(aff), loo=False)
    arm = card["attribution"]["arms"]["component"]
    assert arm["forced"]["recall@1"]["value"] == 1.0      # component prior ranks the owner #1


def test_loo_is_load_bearing(tmp_path):
    # c3 is the SOLE contributor to CamUI -> under LOO its own boost vanishes, so it can no longer be
    # attributed by the prior alone; full-table mode still attributes it. Proves LOO actually excludes.
    ds, aff, atlas = _setup(tmp_path)
    from groundloop.engines.atlas.embed import StubEmbedder
    prof = build_atlas_fixture(str(tmp_path / "p.db"))
    full = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                        arms=("component",), affinity_path=str(aff), loo=False)
    loo = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                       arms=("component",), affinity_path=str(aff), loo=True)
    r_full = full["attribution"]["arms"]["component"]["forced"]["recall@1"]["value"]
    r_loo = loo["attribution"]["arms"]["component"]["forced"]["recall@1"]["value"]
    assert r_loo < r_full                                  # LOO removes the memorized sole-contributor win
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/funceval/test_component_arm.py -q`
Expected: FAIL — `run_funceval` has no `affinity_path`/`loo`, no `component` arm.

- [ ] **Step 3: Implement** — in `groundloop/funceval/runner.py`, add the LOO view, the component-records pass, and thread `affinity_path`/`loo` through `run_funceval`. Add these above `run_funceval` and extend it:

```python
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.component_prior import ComponentPriorIndex
from groundloop.domains.android_ivi.component_affinity import ComponentAffinity
from groundloop.domains.android_ivi.component_signals import ComponentExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.abstain import decide
from groundloop.eval.dataset import case_catalog
from groundloop.eval.runner import MatchRecord


class _LOOView:
    """Per-case leave-one-out affinity view: excludes this case's own (component, owner) contribution.
    Eval/grader-side ONLY (it knows the owner); never used on the production runtime path."""

    def __init__(self, affinity: ComponentAffinity, owner: str):
        self._aff = affinity
        self._owner = owner

    def affinity(self, component: str) -> dict:
        return self._aff.affinity(component, exclude=self._owner)


def _component_records(cases, issues, global_catalog, index_db, affinity, *, loo: bool):
    extractor = ComponentExtractor(AndroidSignalExtractor())
    base = AtlasIndex(index_db)
    recs = []
    for case in cases:
        catalog = case_catalog(case) or global_catalog
        ticket = issues.fetch(case.case_id)
        view = affinity
        if loo:                                            # grader-side owner read (offline eval only)
            owner = load_eval_oracle(case).owning_repo
            view = _LOOView(affinity, owner)
        idx = ComponentPriorIndex(base, view)
        ranked = idx.rank_repos(extractor.extract(ticket.logs, ticket), catalog)
        d = decide(ranked, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1])
        recs.append(MatchRecord(case.case_id, "component", [r.repo.name for r in ranked],
                                [r.score for r in ranked], d.predicted, d.margin, d.top1_score))
    return recs
```

Then extend `run_funceval`'s signature and body — add `affinity_path: str | None = None, loo: bool = False`, split the non-component arms (via `build_functional_arms`/`EvalRunner`) from the `component` arm (via `_component_records`), and grade the union:

```python
def run_funceval(dataset: str, profile_db: str, index_db: str, *, embedder,
                 arms=("functional", "dispatch", "flood", "faultslice", "routing"),
                 affinity_path: str | None = None, loo: bool = False) -> dict:
    cases = load_cases(dataset)
    catalog_path = str(Path(dataset) / "catalog.json")
    issues = MockJira(dataset)
    estate = MockEstate(catalog_path, dataset + "/_work")
    global_catalog = estate.catalog()
    records = []
    std_arms = tuple(a for a in arms if a != "component")
    if std_arms:
        runner = EvalRunner(issues=issues, estate=estate, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1])
        records += runner.run(cases, build_functional_arms(profile_db, index_db, embedder=embedder,
                                                            names=std_arms))
    if "component" in arms:
        if affinity_path is None:
            raise ValueError("the 'component' arm requires --affinity")
        affinity = ComponentAffinity.load(affinity_path)
        records += _component_records(cases, issues, global_catalog, index_db, affinity, loo=loo)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    return {"attribution": grade_all(records, oracle_by_case=oracle_by_case)}
```

(Keep the existing imports; add `load_eval_oracle` to the `from groundloop.eval.dataset import ...` line if not already there.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/funceval/test_component_arm.py tests/funceval -q`
Expected: PASS (existing funceval tests unaffected — `component` is opt-in via `affinity_path`).

- [ ] **Step 5: Wire the CLI** — in `groundloop/cli/__init__.py` `_run_funceval`, thread the new args into the `run_funceval(...)` call and add them to the subparser:

```python
    card = run_funceval(args.dataset, args.profile_db, args.index_db, embedder=emb,
                        arms=tuple(args.arms.split(",")),
                        affinity_path=(args.affinity or None), loo=args.loo)
```

Subparser additions (in the `funceval` block):

```python
    fn.add_argument("--affinity", default="", help="component_affinity.json for the 'component' arm")
    fn.add_argument("--loo", action="store_true", help="leave-one-out affinity (no train/test leak)")
```

- [ ] **Step 6: Anti-leak + LOO red-tests** — create `tests/index/test_component_antileak.py`:

```python
import inspect

from groundloop.adapters.index import component_prior
from groundloop.domains.android_ivi import component_affinity, component_signals


def test_component_runtime_modules_read_no_oracle():
    for mod in (component_prior, component_affinity, component_signals):
        src = inspect.getsource(mod)
        for banned in ("_oracle", "oracle.json", "load_eval_oracle", "owning_repo", "expected_files"):
            assert banned not in src, f"{mod.__name__} must not reference {banned}"
```

Run: `.venv/bin/python -m pytest tests/index/test_component_antileak.py tests/funceval -q && .venv/bin/ruff check groundloop tests`
Expected: PASS + clean. (The runtime modules are oracle-free; the LOO owner read lives only in `funceval/runner.py`'s `_component_records`, which is offline eval code like `grade_all`.)

- [ ] **Step 7: Commit**

```bash
git add groundloop/funceval/runner.py groundloop/cli/__init__.py tests/funceval/test_component_arm.py tests/index/test_component_antileak.py
git commit -m "feat(funceval): component arm + gloop funceval --affinity/--loo (grader-side leave-one-out)"
```

---

## Task 6: `gloop run --match-arm`

**Files:**
- Modify: `groundloop/cli/__init__.py` (the `run` subparser + the `run` dispatch in `main`)
- Test: `tests/test_cli.py` (extend) or `tests/funceval/test_component_arm.py`

- [ ] **Step 1: Write the failing test** — append to `tests/funceval/test_component_arm.py`:

```python
def test_cli_run_match_arm_component(tmp_path):
    import json
    import groundloop.cli as cli
    from tests.fixtures.atlas_fixture import build_atlas_fixture
    ds = tmp_path / "ds"
    _case(ds, "c1", "MapUI", "organicmaps")
    (ds / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "cameraview"}]))
    aff = tmp_path / "aff.json"
    aff.write_text(json.dumps({"MapUI": {"organicmaps": 3}}))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    rc = cli.main(["run", "c1", "--dataset", str(ds), "--catalog", str(ds / "catalog.json"),
                   "--index-db", atlas, "--work", str(tmp_path / "work"),
                   "--changes", str(tmp_path / "ch.jsonl"),
                   "--match-arm", "component", "--affinity", str(aff)])
    assert rc == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/funceval/test_component_arm.py -k match_arm -q`
Expected: FAIL — no `--match-arm`.

- [ ] **Step 3: Implement** — in the `run` subparser (in `build_parser`), add:

```python
    r.add_argument("--match-arm", choices=["flood", "routing", "component"], default="flood",
                   help="Stage-1 match index: flood (AtlasIndex) | routing (FaultRoutingIndex) | component")
    r.add_argument("--affinity", default="", help="component_affinity.json (for --match-arm component)")
```

In `main`, replace the `run` branch's index/extractor construction so the arm selects the pair (keep `flood` = today's behavior):

```python
    if args.cmd == "run":
        from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
        extractor = AndroidSignalExtractor()
        if args.index_db:
            index = AtlasIndex(args.index_db)
            if args.match_arm == "routing":
                from groundloop.adapters.index.fault_routing import FaultRoutingIndex
                from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor
                index, extractor = FaultRoutingIndex(args.index_db), FaultSignalExtractor()
            elif args.match_arm == "component":
                from groundloop.adapters.index.component_prior import ComponentPriorIndex
                from groundloop.domains.android_ivi.component_affinity import ComponentAffinity
                from groundloop.domains.android_ivi.component_signals import ComponentExtractor
                if not args.affinity:
                    print("gloop run --match-arm component: --affinity is required")
                    return 2
                index = ComponentPriorIndex(AtlasIndex(args.index_db), ComponentAffinity.load(args.affinity))
                extractor = ComponentExtractor(AndroidSignalExtractor())
        else:
            index = TokenIndex(args.index)
        issues = MockJira(args.dataset)
        rec = run_ticket(args.case, issues=issues, extractor=extractor,
                         estate=MockEstate(args.catalog, args.work), index=index,
                         fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                         changes=MockGerrit(args.changes, issues))
        print(f"case={rec.ticket_id} matched={rec.chosen.name} change={rec.change.change_id}")
        return 0
```

(Preserve the exact existing arg names used by the current `run` branch — `args.case`, `args.dataset`, `args.catalog`, `args.work`, `args.changes`, `args.index`, `args.index_db`. Only the index/extractor selection changes.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/funceval/test_component_arm.py tests/test_cli.py -q && .venv/bin/ruff check groundloop tests`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/funceval/test_component_arm.py
git commit -m "feat(cli): gloop run --match-arm {flood,routing,component}"
```

---

## Task 7 (orchestrator runbook — proxy mechanism check, not TDD)

> Executed by the orchestrator after Tasks 1–6 are green + merged. Proves the miner + re-ranker + honest LOO **mechanism** on a synthetic-component proxy; the real number is production's.

- [ ] **Step 1:** Full suite + ruff green; frozen-surface zero-diff (`git diff --name-only <base>..HEAD | grep -E 'core/|store.py|atlas.py|owner_tokens|repo_routing|/mine/'` → empty).
- [ ] **Step 2:** Stamp coarse, **many-to-one** synthetic components onto the functional proxy set (a component maps to several repos, never a 1:1 owner alias). A small stamping pass over `/home/vinc/gl-eval/functional-clean` writing `ticket.component` from an owner→component taxonomy with deliberate overlap (e.g. organicmaps+osmand → `Navigation`, oboe+media3 → `Media`, cameraview+gpuimage → `Camera`), plus a fraction with blank/ambiguous components.
- [ ] **Step 3:** `gloop mine-affinity --dataset functional-clean --out component-affinity.json`; then
  `gloop funceval --dataset functional-clean --profile-db textprofiles-9.db --index-db atlas-9.db --arms functional,component --affinity component-affinity.json --loo`.
- [ ] **Step 4:** Confirm under **LOO** the `component` arm's recall@1 exceeds the `functional` (text) base on the synthetic set, and that removing `--loo` inflates it (memorization delta visible) — the mechanism is honest. Write `docs/2026-07-10-component-routing-findings.md` (mechanism check + the caveat that real efficacy is the production 406 LOO run). Update `docs/STATUS.md`; merge; push.

Production-side (you): real `component_affinity.json` over the full oracle; `gloop funceval --affinity … --loo` on the 406; Step-3 `XCUSBMediaService` index; Step-4 CarPlay (gated on the 406 evidence).

---

## Critical files
- `groundloop/domains/android_ivi/component_affinity.py` — `ComponentAffinity` (+ LOO).
- `groundloop/domains/android_ivi/mine_component_affinity.py` — offline miner.
- `groundloop/domains/android_ivi/component_signals.py` — `ComponentExtractor`/`component_of`/`strip_component`.
- `groundloop/adapters/index/component_prior.py` — `ComponentPriorIndex`.
- `groundloop/funceval/runner.py` — `component` arm + `_LOOView` + `_component_records`.
- `groundloop/cli/__init__.py` — `mine-affinity`, `funceval --affinity/--loo`, `run --match-arm`.
