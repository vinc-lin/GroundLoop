# Type-2 Eval Harness (E1-C) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build `groundloop/eval/` — the oracle-blind multi-ticket evaluation harness that drives the mined dataset through membership arms over the real `AtlasIndex`, applies a margin abstain policy, and grades **strictly offline** into a two-view scorecard (forced recall@k ceiling + selective/grounded-refusal), exposed as `gloop eval`.

**Architecture:** Pure edge composition (`core/` frozen). The runner touches ONLY loop-visible inputs (`ticket.json`, `logs/`, `catalog.json`) and produces oracle-free `MatchRecord`s; a separate `scorecard` pass is the sole reader of `_oracle/oracle.json`. Membership matching goes through `AtlasIndex.rank_repos` directly (cheap, isolates Stage-1) — no `run_ticket`. Arms = `membership × {text-only, +logs}`; semantic (E2) and judge (E3) drop in as additional index adapters later.

**Tech Stack:** Python 3.12, pytest (hermetic: reuses `tests/fixtures/atlas_fixture.build_atlas_fixture` FTS5 atlas + the `gpuimage-352` fixture case). Reuses `AtlasIndex`, `AndroidSignalExtractor`, `MockJira`, `MockEstate`, and migrates knowledgeLoop `offline/metrics.py`.

**Canonical design:** [`docs/type2-evaluation.md`](../../type2-evaluation.md) §6 (arms), §7 (metrics/scorecard), §8 (harness), §9 (integrity). Eval stage **E1-C**; consumes the E1-A atlas + E1-B dataset.

---

## Verified integration types (from `groundloop/core/types.py`)

- `Signals(packages, classes, methods, symbols, libraries, errors)` + `.tokens() -> tuple[str,...]`.
- `RepoRef(name)`; `RepoScore(repo: RepoRef, score: float, evidence=())`.
- `Oracle(owning_repo: str, expected_files: tuple, required_apis: tuple)`.
- `Ticket(id, summary, description, component="", comments=(), logs=(), status="Open")`, `LogAttachment(path, kind, content)`.
- `AtlasIndex(db_path).rank_repos(signals, catalog) -> list[RepoScore]` (sorted desc by score).
- `MockEstate(catalog_path, work_root).catalog() -> list[RepoRef]` (reads `catalog.json` = `[{"name":...}]`).
- `MockJira(dataset_root).fetch(case_id) -> Ticket`.
- `AndroidSignalExtractor().extract(logs: Sequence[LogAttachment], ticket: Ticket) -> Signals`.

**Oracle-blindness contract:** the runner must NEVER read anything under `_oracle/`. Only `scorecard` reads `_oracle/oracle.json`. A Type-1 test (Task 7) extends the `Path.read_text` read-spy from `tests/test_invariants.py` over `EvalRunner.run` to enforce this.

---

## File Structure

- **Create** `groundloop/eval/__init__.py`
- **Create** `groundloop/eval/dataset.py` — `load_cases(root)`, `load_oracle(case)`, `CaseRef`.
- **Create** `groundloop/eval/metrics.py` — migrated `recall_at_k/success_at_k/mrr/ndcg_at_k` + `wilson`, `phi_c`, `repo_rank`.
- **Create** `groundloop/eval/extractors.py` — `TextOnlyExtractor`.
- **Create** `groundloop/eval/abstain.py` — `decide(ranked, *, tau_margin, tau_score)`.
- **Create** `groundloop/eval/arms.py` — `Arm`, `build_arms(index, ...)`.
- **Create** `groundloop/eval/runner.py` — `EvalRunner`, `MatchRecord`.
- **Create** `groundloop/eval/scorecard.py` — `grade_all`, `score_match`.
- **Create** `groundloop/eval/report.py` — `render_markdown`.
- **Modify** `groundloop/cli/__init__.py` — `gloop eval` subcommand.
- **Create** `tests/eval/__init__.py` + one test file per module + `tests/eval/test_oracle_blind.py`.

**Commands:** test `.venv/bin/python -m pytest tests/eval/<f>.py -q`; full `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check groundloop tests`. Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1: Dataset loader (oracle-blind at load)

**Files:** Create `groundloop/eval/__init__.py` (empty), `groundloop/eval/dataset.py`; Test `tests/eval/__init__.py` (empty) + `tests/eval/test_dataset.py`.

- [ ] **Step 1: Failing test** — `tests/eval/test_dataset.py`:

```python
import json
from pathlib import Path

from groundloop.eval.dataset import load_cases, load_oracle, CaseRef
from groundloop.core.types import Oracle


def _mk_case(root, cid, owner):
    d = Path(root) / cid
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps(
        {"id": cid, "summary": "s", "description": "d", "component": "", "logs": []}))
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": ["a/b.java"], "required_apis": ["f"],
         "owning_repo_sha": "deadbeef", "is_answerable": True}))


def test_load_cases_finds_case_dirs(tmp_path):
    _mk_case(tmp_path, "GP-1", "gpuimage")
    _mk_case(tmp_path, "ND-2", "newpipe")
    (tmp_path / "catalog.json").write_text("[]")   # not a case dir
    cases = load_cases(str(tmp_path))
    assert {c.case_id for c in cases} == {"GP-1", "ND-2"}
    assert all(isinstance(c, CaseRef) for c in cases)


def test_load_oracle_reads_hidden_oracle_and_drops_extra_keys(tmp_path):
    _mk_case(tmp_path, "GP-1", "gpuimage")
    (case,) = [c for c in load_cases(str(tmp_path)) if c.case_id == "GP-1"]
    oracle = load_oracle(case)
    assert isinstance(oracle, Oracle)
    assert oracle.owning_repo == "gpuimage"
    assert oracle.expected_files == ("a/b.java",)     # list -> tuple
    assert oracle.required_apis == ("f",)
    # extra keys (owning_repo_sha, is_answerable) dropped, no crash


def test_load_cases_does_not_read_oracle(tmp_path, monkeypatch):
    _mk_case(tmp_path, "GP-1", "gpuimage")
    import pathlib
    reads = []
    orig = pathlib.Path.read_text

    def spy(self, *a, **k):
        reads.append(str(self))
        return orig(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", spy)
    load_cases(str(tmp_path))
    assert not any("_oracle" in r for r in reads), f"load_cases read the oracle: {reads}"
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/eval/dataset.py`:

```python
"""Dataset loading for the Type-2 eval. `load_cases` is oracle-blind; only `load_oracle`
(used solely by the offline scorecard) touches _oracle/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from groundloop.core.types import Oracle

_ORACLE_KEYS = ("owning_repo", "expected_files", "required_apis")


@dataclass(frozen=True)
class CaseRef:
    case_id: str
    case_dir: str


def load_cases(root: str) -> list[CaseRef]:
    """Discover case dirs (those containing ticket.json). Never reads _oracle/."""
    out: list[CaseRef] = []
    for d in sorted(Path(root).iterdir()):
        if d.is_dir() and (d / "ticket.json").is_file():
            out.append(CaseRef(case_id=d.name, case_dir=str(d)))
    return out


def load_oracle(case: CaseRef) -> Oracle:
    """Read the hidden oracle. OFFLINE-GRADE ONLY — never call from the runner/arm path."""
    import json
    raw = json.loads((Path(case.case_dir) / "_oracle" / "oracle.json").read_text())
    return Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                     for k, v in raw.items() if k in _ORACLE_KEYS})
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): oracle-blind dataset loader`).

---

## Task 2: Metrics (migrate + Wilson + Phi_c)

**Files:** Create `groundloop/eval/metrics.py`; Test `tests/eval/test_metrics.py`.

- [ ] **Step 1: Failing test** — `tests/eval/test_metrics.py`:

```python
import math
from groundloop.eval.metrics import (recall_at_k, success_at_k, mrr, ndcg_at_k,
                                      wilson, phi_c, repo_rank)


def test_migrated_file_metrics():
    assert recall_at_k(["a", "b", "c"], {"a", "z"}, 2) == 0.5
    assert success_at_k(["a", "b"], {"b"}, 2) == 1.0
    assert mrr(["x", "a"], {"a"}) == 0.5
    assert abs(ndcg_at_k(["a"], {"a"}, 1) - 1.0) < 1e-9


def test_repo_rank_exact_match():
    assert repo_rank(["b", "a", "c"], "a") == 2
    assert repo_rank(["b", "c"], "a") == 0        # absent


def test_wilson_bounds_within_0_1_and_centered():
    lo, hi = wilson(7, 10)
    assert 0.0 <= lo <= 0.7 <= hi <= 1.0
    lo0, hi0 = wilson(0, 0)                        # n=0 -> [0,1]
    assert (lo0, hi0) == (0.0, 1.0)


def test_phi_c_rewards_abstain_over_wrong_guess():
    # records: (answered, correct, answerable)
    correct = [{"answered": True, "correct": True, "answerable": True}]
    wrong = [{"answered": True, "correct": False, "answerable": True}]
    abstain = [{"answered": False, "correct": False, "answerable": True}]
    assert phi_c(correct, c=1.0) == 1.0
    assert phi_c(wrong, c=1.0) == -1.0
    assert phi_c(abstain, c=1.0) == 0.0
    # abstaining (0) strictly beats guessing wrong (-1)
    assert phi_c(abstain, c=1.0) > phi_c(wrong, c=1.0)
    # abstain on an UNANSWERABLE ticket is the correct action -> +1
    oof = [{"answered": False, "correct": False, "answerable": False}]
    assert phi_c(oof, c=1.0) == 1.0
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/eval/metrics.py` (migrate `offline/metrics.py` + add):

```python
"""Retrieval + selective-prediction metrics for the Type-2 scorecard.

recall_at_k/success_at_k/mrr/ndcg_at_k migrated verbatim from knowledgeLoop
offline/metrics.py (file-level any-of; used for Stage-2 localization). repo_rank/
wilson/phi_c are the Stage-1 + selective additions (docs/type2-evaluation.md §7)."""
from __future__ import annotations

import math


def recall_at_k(ranked_files: list, gold: set, k: int) -> float:
    if not gold:
        return 0.0
    return len(gold & set(ranked_files[:k])) / len(gold)


def success_at_k(ranked_files: list, gold: set, k: int) -> float:
    return 1.0 if (gold & set(ranked_files[:k])) else 0.0


def mrr(ranked_files: list, gold: set) -> float:
    for i, f in enumerate(ranked_files):
        if f in gold:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked_files: list, gold: set, k: int) -> float:
    if not gold:
        return 0.0
    dcg, seen = 0.0, set()
    for i, f in enumerate(ranked_files[:k]):
        if f in gold and f not in seen:
            seen.add(f)
            dcg += 1.0 / math.log2(i + 2)
    ideal = min(k, len(gold))
    idcg = sum(1.0 / math.log2(p + 1) for p in range(1, ideal + 1))
    return dcg / idcg if idcg else 0.0


def repo_rank(ranked_names: list, owning_repo: str) -> int:
    """1-indexed rank of the single owning repo; 0 if absent (Stage-1 exact match)."""
    return ranked_names.index(owning_repo) + 1 if owning_repo in ranked_names else 0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI for k successes in n trials. n=0 -> (0.0, 1.0)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def phi_c(records: list[dict], c: float = 1.0) -> float:
    """Effective Reliability (Whitehead et al.): per record with keys answered/correct/answerable —
    answered&correct=+1; answered&wrong=-c; abstain on answerable=0; abstain on unanswerable=+1;
    answered on unanswerable=-c. Mean over records. Empty -> 0.0."""
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        if r["answered"]:
            total += 1.0 if (r["answerable"] and r["correct"]) else -c
        else:
            total += 0.0 if r["answerable"] else 1.0
    return total / len(records)
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): metrics — migrate file metrics + Wilson CI + Phi_c`).

---

## Task 3: Text-only extractor + abstain policy

**Files:** Create `groundloop/eval/extractors.py`, `groundloop/eval/abstain.py`; Test `tests/eval/test_extractors.py`, `tests/eval/test_abstain.py`.

- [ ] **Step 1: Failing tests** —

`tests/eval/test_extractors.py`:
```python
from groundloop.eval.extractors import TextOnlyExtractor
from groundloop.core.types import Ticket, LogAttachment


def test_text_only_ignores_logs():
    log = LogAttachment(path="logs/0.txt", kind="logcat",
                        content="java.lang.UnsatisfiedLinkError at org.x.Y.z()")
    ticket = Ticket(id="t", summary="crash in filter", description="NullPointerException in prose")
    sig_txt = TextOnlyExtractor().extract((log,), ticket)
    # text-only must NOT pick up the log's UnsatisfiedLinkError...
    assert "UnsatisfiedLinkError" not in sig_txt.tokens()
    # ...but SHOULD still extract from summary/description
    assert any("NullPointerException" in t for t in sig_txt.tokens()) or \
        "NullPointerException" in ticket.description
```

`tests/eval/test_abstain.py`:
```python
from groundloop.eval.abstain import decide
from groundloop.core.types import RepoScore, RepoRef


def _r(name, score):
    return RepoScore(RepoRef(name), float(score))


def test_predicts_top1_when_margin_and_score_clear():
    ranked = [_r("a", 5), _r("b", 2)]
    d = decide(ranked, tau_margin=2.0, tau_score=1.0)
    assert d.predicted == "a" and d.margin == 3.0 and d.top1_score == 5.0


def test_abstains_on_low_margin():
    ranked = [_r("a", 3), _r("b", 3)]      # margin 0
    d = decide(ranked, tau_margin=2.0, tau_score=1.0)
    assert d.predicted is None


def test_abstains_on_weak_top1_even_if_margin_ok():
    ranked = [_r("a", 0.5), _r("b", 0.0)]  # margin 0.5 but score below tau_score
    d = decide(ranked, tau_margin=0.3, tau_score=1.0)
    assert d.predicted is None


def test_single_candidate_margin_is_top_score():
    d = decide([_r("a", 4)], tau_margin=2.0, tau_score=1.0)
    assert d.predicted == "a" and d.margin == 4.0


def test_empty_ranked_abstains():
    d = decide([], tau_margin=2.0, tau_score=1.0)
    assert d.predicted is None
```

- [ ] **Step 2: Run → fail. Step 3: Implement** —

`groundloop/eval/extractors.py`:
```python
"""Signal-ablation extractor: text-only drops the failure logs (docs/type2-evaluation.md §6.2)."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor


class TextOnlyExtractor:
    """SignalExtractor that ignores logs — extracts from ticket summary/description only."""

    def __init__(self) -> None:
        self._inner = AndroidSignalExtractor()

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        return self._inner.extract((), ticket)     # drop logs
```

`groundloop/eval/abstain.py`:
```python
"""Margin-based abstain policy over a ranked RepoScore list (docs/type2-evaluation.md §7.2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from groundloop.core.types import RepoScore


@dataclass(frozen=True)
class Decision:
    predicted: Optional[str]     # repo name, or None = ABSTAIN
    margin: float
    top1_score: float


def decide(ranked: Sequence[RepoScore], *, tau_margin: float, tau_score: float) -> Decision:
    """Predict top-1 iff (top1 - top2) margin >= tau_margin AND top1 score >= tau_score; else abstain.
    Scale-robust: gates on the margin (raw FTS5 counts are uncalibrated)."""
    if not ranked:
        return Decision(predicted=None, margin=0.0, top1_score=0.0)
    top1 = ranked[0].score
    runner = ranked[1].score if len(ranked) > 1 else 0.0
    margin = top1 - runner if len(ranked) > 1 else top1
    predicted = ranked[0].repo.name if (margin >= tau_margin and top1 >= tau_score) else None
    return Decision(predicted=predicted, margin=margin, top1_score=top1)
```

- [ ] **Step 4: Run → pass** (`tests/eval` green). **Step 5: ruff + commit** (`feat(eval): TextOnlyExtractor + margin abstain policy`).

---

## Task 4: Arms factory

**Files:** Create `groundloop/eval/arms.py`; Test `tests/eval/test_arms.py`.

- [ ] **Step 1: Failing test** — `tests/eval/test_arms.py`:

```python
from groundloop.eval.arms import build_arms, Arm
from groundloop.core.types import Ticket, LogAttachment


class _FakeIndex:
    def rank_repos(self, signals, catalog):
        return []


def test_build_arms_membership_text_and_logs():
    arms = build_arms(membership_index=_FakeIndex())
    names = {a.name for a in arms}
    assert names == {"membership+text", "membership+logs"}
    assert all(isinstance(a, Arm) for a in arms)


def test_text_arm_drops_logs_logs_arm_keeps():
    arms = {a.name: a for a in build_arms(membership_index=_FakeIndex())}
    log = LogAttachment(path="l", kind="logcat", content="java.lang.UnsatisfiedLinkError")
    ticket = Ticket(id="t", summary="s", description="d")
    txt = arms["membership+text"].extractor.extract((log,), ticket)
    logs = arms["membership+logs"].extractor.extract((log,), ticket)
    assert "UnsatisfiedLinkError" not in txt.tokens()
    assert "UnsatisfiedLinkError" in logs.tokens()
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/eval/arms.py`:

```python
"""Arm construction: strategy x signal. v1 = membership x {text-only, +logs}
(docs/type2-evaluation.md §6). Semantic (E2) / judge (E3) add strategies later."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.extractors import TextOnlyExtractor


@dataclass(frozen=True)
class Arm:
    name: str
    index: Any        # a CodeIndex: .rank_repos(signals, catalog)
    extractor: Any    # .extract(logs, ticket) -> Signals


def build_arms(*, membership_index) -> list[Arm]:
    return [
        Arm("membership+text", membership_index, TextOnlyExtractor()),
        Arm("membership+logs", membership_index, AndroidSignalExtractor()),
    ]
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): arms factory (membership x text/+logs)`).

---

## Task 5: EvalRunner (oracle-blind)

**Files:** Create `groundloop/eval/runner.py`; Test `tests/eval/test_runner.py`.

- [ ] **Step 1: Failing test** — `tests/eval/test_runner.py` (uses the hermetic fixture atlas + gpuimage fixture case):

```python
import json
from pathlib import Path

from groundloop.eval.runner import EvalRunner, MatchRecord
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.estate import MockEstate
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _seed_case(root):
    d = Path(root) / "GP-352"
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({
        "id": "GP-352", "summary": "crash on GL thread applying filter",
        "description": "UnsatisfiedLinkError CGEImageHandler",
        "component": "", "logs": [{"path": "logs/c.txt", "kind": "logcat"}]}))
    (d / "logs" / "c.txt").write_text(
        "java.lang.UnsatisfiedLinkError: org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler")
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "android-gpuimage-plus"}))


def _catalog(root):
    p = Path(root) / "catalog.json"
    p.write_text(json.dumps([{"name": "android-gpuimage-plus"}, {"name": "organicmaps"},
                             {"name": "androidx-media"}, {"name": "cameraview"}]))
    return str(p)


def test_runner_produces_records_per_case_x_arm(tmp_path):
    _seed_case(tmp_path)
    cat = _catalog(tmp_path)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    arms = build_arms(membership_index=AtlasIndex(db))
    runner = EvalRunner(issues=MockJira(str(tmp_path)),
                        estate=MockEstate(cat, str(tmp_path / "work")),
                        tau_margin=0.5, tau_score=1.0)
    cases = load_cases(str(tmp_path))
    records = runner.run(cases, arms)

    assert len(records) == 2                      # 1 case x 2 arms
    assert {r.arm for r in records} == {"membership+text", "membership+logs"}
    logs_rec = next(r for r in records if r.arm == "membership+logs")
    # +logs arm should rank the owning repo first from the CGEImageHandler signal
    assert logs_rec.ranked_names[0] == "android-gpuimage-plus"
    assert isinstance(logs_rec, MatchRecord)


def test_runner_never_reads_oracle(tmp_path, monkeypatch):
    _seed_case(tmp_path)
    cat = _catalog(tmp_path)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    arms = build_arms(membership_index=AtlasIndex(db))
    runner = EvalRunner(issues=MockJira(str(tmp_path)),
                        estate=MockEstate(cat, str(tmp_path / "work")),
                        tau_margin=0.5, tau_score=1.0)

    import pathlib
    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])
    runner.run(load_cases(str(tmp_path)), arms)
    assert not any("_oracle" in r for r in reads), f"runner read the oracle: {reads}"
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/eval/runner.py`:

```python
"""Oracle-blind Stage-1 eval runner. Per (case x arm): fetch ticket, extract signals, rank repos
DIRECTLY (no run_ticket), apply the abstain policy. Never reads the oracle (docs §8.2/§9)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from groundloop.eval.abstain import decide
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef


@dataclass(frozen=True)
class MatchRecord:
    case_id: str
    arm: str
    ranked_names: list[str]
    scores: list[float]
    predicted: str | None      # None = abstain
    margin: float
    top1_score: float


class EvalRunner:
    def __init__(self, *, issues, estate, tau_margin: float, tau_score: float):
        self.issues = issues
        self.estate = estate
        self.tau_margin = tau_margin
        self.tau_score = tau_score

    def run(self, cases: Sequence[CaseRef], arms: Sequence[Arm]) -> list[MatchRecord]:
        catalog = self.estate.catalog()
        records: list[MatchRecord] = []
        for case in cases:
            ticket = self.issues.fetch(case.case_id)          # loop-visible only
            for arm in arms:
                signals = arm.extractor.extract(ticket.logs, ticket)
                ranked = arm.index.rank_repos(signals, catalog)
                d = decide(ranked, tau_margin=self.tau_margin, tau_score=self.tau_score)
                records.append(MatchRecord(
                    case_id=case.case_id, arm=arm.name,
                    ranked_names=[r.repo.name for r in ranked],
                    scores=[r.score for r in ranked],
                    predicted=d.predicted, margin=d.margin, top1_score=d.top1_score))
        return records
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): oracle-blind EvalRunner (rank_repos-direct)`).

---

## Task 6: Scorecard (offline grade) + report

**Files:** Create `groundloop/eval/scorecard.py`, `groundloop/eval/report.py`; Test `tests/eval/test_scorecard.py`.

- [ ] **Step 1: Failing test** — `tests/eval/test_scorecard.py`:

```python
from groundloop.eval.scorecard import score_match, grade_all
from groundloop.eval.runner import MatchRecord
from groundloop.core.types import Oracle


def _rec(arm, ranked, predicted, margin=3.0):
    return MatchRecord(case_id="c", arm=arm, ranked_names=ranked,
                       scores=[float(len(ranked) - i) for i in range(len(ranked))],
                       predicted=predicted, margin=margin, top1_score=5.0)


def test_score_match_forced_and_selective_fields():
    rec = _rec("membership+logs", ["gpuimage", "organicmaps", "cameraview"], "gpuimage")
    oracle = Oracle(owning_repo="gpuimage")
    m = score_match(rec, oracle)
    assert m["recall@1"] is True
    assert m["repo_rank"] == 1
    assert m["answered"] is True and m["correct"] is True and m["answerable"] is True


def test_score_match_abstain_and_wrong():
    abstain = score_match(_rec("a", ["organicmaps", "gpuimage"], None), Oracle(owning_repo="gpuimage"))
    assert abstain["answered"] is False and abstain["correct"] is False
    assert abstain["recall@1"] is False and abstain["repo_rank"] == 2   # forced view ignores abstain
    wrong = score_match(_rec("a", ["organicmaps", "gpuimage"], "organicmaps"),
                        Oracle(owning_repo="gpuimage"))
    assert wrong["answered"] is True and wrong["correct"] is False


def test_grade_all_aggregates_per_arm(tmp_path):
    # two cases through one arm: one correct-answered, one abstain
    recs = [
        MatchRecord("c1", "membership+logs", ["gpuimage", "cameraview"], [5.0, 1.0], "gpuimage", 4.0, 5.0),
        MatchRecord("c2", "membership+logs", ["cameraview", "gpuimage"], [2.0, 2.0], None, 0.0, 2.0),
    ]
    oracles = {"c1": Oracle(owning_repo="gpuimage"), "c2": Oracle(owning_repo="gpuimage")}
    card = grade_all(recs, oracle_by_case=oracles, ks=(1, 3))
    arm = card["arms"]["membership+logs"]
    assert arm["n"] == 2
    assert arm["forced"]["recall@1"]["value"] == 0.5      # c1 hits @1, c2 owner at rank2
    assert arm["selective"]["coverage"] == 0.5            # 1 answered of 2
    assert arm["selective"]["selective_accuracy"]["value"] == 1.0   # the 1 answered was correct
    assert arm["selective"]["phi_c"]["1.0"] == 0.5        # +1 (c1) + 0 (abstain c2) / 2
    assert "wilson95" in arm["forced"]["recall@1"]
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/eval/scorecard.py`:

```python
"""Offline grade pass — the ONLY reader of the oracle. Produces the two-view scorecard
(forced ceiling + selective) per arm (docs/type2-evaluation.md §7)."""
from __future__ import annotations

from collections import defaultdict

from groundloop.core.types import Oracle
from groundloop.eval.runner import MatchRecord
from groundloop.eval.metrics import repo_rank, wilson, phi_c


def score_match(rec: MatchRecord, oracle: Oracle, *, is_answerable: bool = True) -> dict:
    owner = oracle.owning_repo
    rank = repo_rank(rec.ranked_names, owner)
    answered = rec.predicted is not None
    return {
        "case_id": rec.case_id,
        "repo_rank": rank,
        "recall@1": bool(rec.ranked_names[:1] == [owner]),   # forced view (abstain-agnostic)
        "answered": answered,
        "correct": bool(answered and rec.predicted == owner),
        "answerable": is_answerable,
        "ranked_names": rec.ranked_names,
    }


def _wrap(k: int, n: int) -> dict:
    return {"value": (k / n if n else 0.0), "wilson95": list(wilson(k, n))}


def grade_all(records, *, oracle_by_case: dict[str, Oracle], ks=(1, 3, 5),
              c_values=(0.5, 1.0, 2.0)) -> dict:
    by_arm: dict[str, list] = defaultdict(list)
    for rec in records:
        oracle = oracle_by_case[rec.case_id]
        by_arm[rec.arm].append(score_match(rec, oracle))

    arms: dict[str, dict] = {}
    for arm, ms in by_arm.items():
        n = len(ms)
        forced = {}
        for k in ks:
            hits = sum(1 for m in ms if m["repo_rank"] and m["repo_rank"] <= k)
            forced[f"recall@{k}"] = _wrap(hits, n)
        ranks = [m["repo_rank"] for m in ms if m["repo_rank"]]
        forced["mrr"] = sum(1.0 / r for r in ranks) / n if n else 0.0
        forced["mean_repo_rank"] = (sum(ranks) / len(ranks)) if ranks else 0.0

        answered = [m for m in ms if m["answered"]]
        correct_answered = sum(1 for m in answered if m["correct"])
        selective = {
            "coverage": len(answered) / n if n else 0.0,
            "selective_accuracy": _wrap(correct_answered, len(answered)),
            "selective_risk": 1.0 - (correct_answered / len(answered)) if answered else 0.0,
            "phi_c": {str(c): phi_c(ms, c=c) for c in c_values},
        }
        arms[arm] = {"n": n, "forced": forced, "selective": selective}
    return {"arms": arms, "n_cases": len({m["case_id"] for ms in by_arm.values() for m in ms})}
```

`groundloop/eval/report.py`:
```python
"""Render a scorecard dict to a compact markdown table (docs/type2-evaluation.md §7.4)."""
from __future__ import annotations


def render_markdown(card: dict) -> str:
    lines = ["# Type-2 scorecard", "", f"cases: {card.get('n_cases', 0)}", "",
             "| arm | n | recall@1 | mrr | coverage | sel-acc | Phi_1 |",
             "|---|---|---|---|---|---|---|"]
    for arm, a in card["arms"].items():
        f, s = a["forced"], a["selective"]
        r1 = f["recall@1"]["value"]
        lines.append(f"| {arm} | {a['n']} | {r1:.2f} | {f['mrr']:.2f} | "
                     f"{s['coverage']:.2f} | {s['selective_accuracy']['value']:.2f} | "
                     f"{s['phi_c']['1.0']:.2f} |")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): offline scorecard (forced + selective) + markdown report`).

---

## Task 7: `gloop eval` CLI + oracle-blind integration test

**Files:** Modify `groundloop/cli/__init__.py`; Test `tests/eval/test_cli_eval.py` + `tests/eval/test_oracle_blind.py`.

- [ ] **Step 1: Failing tests** —

`tests/eval/test_cli_eval.py` (end-to-end through the CLI over the fixture):
```python
import json
from pathlib import Path
import groundloop.cli as cli
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _seed(root):
    d = Path(root) / "GP-352"
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({
        "id": "GP-352", "summary": "crash", "description": "UnsatisfiedLinkError CGEImageHandler",
        "component": "", "logs": [{"path": "logs/c.txt", "kind": "logcat"}]}))
    (d / "logs" / "c.txt").write_text("org.wysaid.nativePort.CGEImageHandler nativeCreateHandler")
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "android-gpuimage-plus"}))
    (Path(root) / "catalog.json").write_text(json.dumps(
        [{"name": "android-gpuimage-plus"}, {"name": "organicmaps"},
         {"name": "androidx-media"}, {"name": "cameraview"}]))


def test_gloop_eval_writes_scorecard(tmp_path):
    _seed(tmp_path)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "card.json"
    rc = cli.main(["eval", "--dataset", str(tmp_path), "--catalog", str(tmp_path / "catalog.json"),
                   "--index-db", db, "--out", str(out)])
    assert rc == 0
    card = json.loads(out.read_text())
    assert "arms" in card and "membership+logs" in card["arms"]
    assert (tmp_path / "card.md").is_file()   # markdown twin next to --out
```

`tests/eval/test_oracle_blind.py` (the integrity guard — the runner path never reads _oracle/):
```python
import json
from pathlib import Path
import pathlib

from groundloop.eval.runner import EvalRunner
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.estate import MockEstate
from tests.fixtures.atlas_fixture import build_atlas_fixture


def test_full_run_reads_no_oracle_and_no_bind_output(tmp_path, monkeypatch):
    d = Path(tmp_path) / "GP-352"
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps(
        {"id": "GP-352", "summary": "s", "description": "d", "component": "", "logs": []}))
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "android-gpuimage-plus"}))
    (Path(tmp_path) / "catalog.json").write_text(json.dumps(
        [{"name": "android-gpuimage-plus"}, {"name": "organicmaps"}, {"name": "cameraview"}]))
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))

    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])

    runner = EvalRunner(issues=MockJira(str(tmp_path)),
                        estate=MockEstate(str(Path(tmp_path) / "catalog.json"), str(tmp_path / "w")),
                        tau_margin=0.5, tau_score=1.0)
    runner.run(load_cases(str(tmp_path)), build_arms(membership_index=AtlasIndex(db)))
    assert not any("_oracle" in r for r in reads), f"leak: {reads}"
```

- [ ] **Step 2: Run → fail. Step 3: Implement** the CLI. In `groundloop/cli/__init__.py` add the subparser:

```python
    ev = sub.add_parser("eval", help="run the Type-2 eval over a mined dataset -> scorecard")
    ev.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    ev.add_argument("--catalog", required=True, help="path to catalog.json")
    ev.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    ev.add_argument("--out", required=True, help="scorecard.json output path (a .md twin is written too)")
    ev.add_argument("--tau-margin", type=float, default=1.0)
    ev.add_argument("--tau-score", type=float, default=1.0)
```

Add `_run_eval`:
```python
def _run_eval(args) -> int:
    import json
    from pathlib import Path
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.adapters.estate import MockEstate
    from groundloop.eval.dataset import load_cases, load_oracle
    from groundloop.eval.arms import build_arms
    from groundloop.eval.runner import EvalRunner
    from groundloop.eval.scorecard import grade_all
    from groundloop.eval.report import render_markdown

    cases = load_cases(args.dataset)
    runner = EvalRunner(issues=MockJira(args.dataset),
                        estate=MockEstate(args.catalog, args.dataset + "/_work"),
                        tau_margin=args.tau_margin, tau_score=args.tau_score)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)))
    oracle_by_case = {c.case_id: load_oracle(c) for c in cases}     # OFFLINE grade — oracle read here only
    card = grade_all(records, oracle_by_case=oracle_by_case)
    Path(args.out).write_text(json.dumps(card, indent=2))
    Path(args.out).with_suffix(".md").write_text(render_markdown(card))
    for arm, a in card["arms"].items():
        print(f"{arm}: recall@1={a['forced']['recall@1']['value']:.2f} "
              f"coverage={a['selective']['coverage']:.2f} phi_1={a['selective']['phi_c']['1.0']:.2f}")
    return 0
```

And dispatch: `if args.cmd == "eval": return _run_eval(args)`.

- [ ] **Step 4: Run → pass.** Then `.venv/bin/python -m pytest -q` (full suite green), `.venv/bin/ruff check groundloop tests`, `.venv/bin/gloop eval --help` (exit 0).
- [ ] **Step 5: Commit** (`feat(eval): gloop eval CLI + oracle-blind integration guard`).

---

## Self-Review

**Spec coverage (`type2-evaluation.md` §6–§9):** oracle-blind dataset load (Task 1) ✓; forced recall@k + mrr + Wilson CIs (Tasks 2, 6) ✓; Phi_c selective view + coverage + margin abstain (Tasks 2, 3, 6) ✓; membership × {text,+logs} arms (Tasks 3, 4) ✓; rank_repos-direct oracle-blind runner (Task 5) ✓; offline scorecard as the sole oracle reader (Task 6) ✓; `gloop eval` (Task 7) ✓; the invariant-#4 read-spy extended to `EvalRunner` (Tasks 5, 7) ✓. **Deferred (noted):** AURC/AUGRC + risk-coverage curve (Phi_c + Wilson lead at small N per §7.3 — add when the corpus grows); Stage-2 localization via a `run_ticket` fidelity slice (the migrated `recall_at_k`/`mrr` are ready for it); the unanswerable/OOF subset (`score_match` already takes `is_answerable`; the runner-side `catalog_holdout` filter + OOF cases are a fast-follow); per-repo confusion + per-stratum + cost (E2/E3 bring cost).

**Placeholder scan:** none — every module has complete code.

**Type consistency:** `CaseRef(case_id, case_dir)` (dataset) → runner/scorecard; `MatchRecord` fields consistent across runner/scorecard/report; `Decision(predicted, margin, top1_score)` (abstain) consumed by runner; `Arm(name, index, extractor)` (arms) consumed by runner; `Oracle` loaded only in scorecard/CLI-offline-pass; scorecard dict shape (`arms[name].forced.recall@k.{value,wilson95}` + `.selective.{coverage,selective_accuracy,phi_c}`) consistent between `grade_all`, the test asserts, and `render_markdown`.
