# Type-2 SP1a — Honest-Refusal Negative-Case Scoring (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Type-2 eval able to *score honest refusal* — un-strip the negative-case oracle fields, support per-ticket catalogs (OOF hold-out), give each arm its own abstain threshold, and add `abstention_recall_oof` + a per-negative-class breakdown to the scorecard — validated hermetically over realistic hand-authored negative fixtures across all four classes.

**Architecture:** Pure eval-layer + adapter edits; `core/` is FROZEN and untouched. The negative-case fields (`is_answerable`, `negative_class`, `held_out_repo`) ride as **extra keys** in `_oracle/oracle.json`, read only by a new eval-side `EvalOracle`/`load_eval_oracle` (the frozen `core.types.Oracle` never sees them). The runner gains an oracle-blind per-case catalog override (a loop-visible `catalog.json` in the case dir — never `_oracle/`). Scoring follows the two-bucket rule from the spec: Bucket-1 (`is_answerable=false`: out_of_fleet / coverage_gap / not_a_defect) → abstain scores `+1`; Bucket-2 (`is_answerable=true`: insufficient_signal + positives) → abstain scores `0`.

**Tech Stack:** Python 3.12, `.venv` (uv), pytest, ruff. Test cmd: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests` (line length 110).

**Spec:** `docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md` §1 (SP1). This plan implements SP1's schema + wiring (§1.3) and the scoring buckets (§1.1) over fixtures.

**Out of scope (next plan — SP1b):** the online `gloop mine` sourcing of real negatives (hold-out generation, temporal-gap via inverse admit-filter, prose-only admission, label-harvest), opaque `case_id` in the miner, and the leak red-test over mined output. This plan proves the *consumer + contract* hermetically; SP1b is the *producer*.

---

## File Structure

**Modify:**
- `groundloop/eval/dataset.py` — add `EvalOracle` + `load_eval_oracle` (negative fields) + `case_catalog` (per-case catalog loader). Keep existing `load_oracle`/`load_cases` untouched.
- `groundloop/eval/arms.py` — add per-arm `tau_margin`/`tau_score` to `Arm`; set per-strategy defaults in `build_arms`.
- `groundloop/eval/runner.py` — per-case catalog override + per-arm τ (fall back to runner default).
- `groundloop/eval/scorecard.py` — `score_match` reads `is_answerable`/`negative_class`; `grade_all` computes forced recall over the answerable subset, adds `abstention_recall_oof` + `per_class`.
- `groundloop/cli/__init__.py` — `_run_eval` uses `load_eval_oracle`; print line adds `oof_recall`.

**Create:**
- `tests/fixtures/android_ivi/negatives/oof-hold-1/` — an out_of_fleet hold-out fixture (reduced per-case `catalog.json`).
- `tests/fixtures/android_ivi/negatives/lowsig-1/` — an insufficient_signal fixture (global catalog).
- `tests/eval/test_negatives_dataset.py` — `load_eval_oracle` + `case_catalog` unit tests.
- `tests/eval/test_runner_percase.py` — per-case catalog + per-arm τ override.
- `tests/eval/test_negatives_scoring.py` — the two-bucket scoring + `abstention_recall_oof` + `per_class`.
- `tests/eval/test_negatives_fixtures.py` — fixtures load correctly and are oracle-blind (opaque id, no hidden fields loop-visible).
- `tests/eval/test_cli_eval_oof.py` — end-to-end `gloop eval` over a dataset with a negative → scorecard has the new keys.

---

### Task A1: `EvalOracle` + `load_eval_oracle` (negative oracle fields)

**Files:**
- Modify: `groundloop/eval/dataset.py`
- Test: `tests/eval/test_negatives_dataset.py`

- [ ] **Step 1: Write the failing test**

Create `tests/eval/test_negatives_dataset.py`:

```python
import json
from pathlib import Path

from groundloop.eval.dataset import CaseRef, load_eval_oracle


def _write_case(root: Path, cid: str, oracle: dict) -> CaseRef:
    d = root / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d", "logs": []}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle))
    return CaseRef(case_id=cid, case_dir=str(d))


def test_load_eval_oracle_reads_negative_fields(tmp_path):
    case = _write_case(tmp_path, "neg-1", {
        "owning_repo": "__OUT_OF_FLEET__", "is_answerable": False,
        "negative_class": "out_of_fleet", "expected_files": []})
    ev = load_eval_oracle(case)
    assert ev.is_answerable is False
    assert ev.negative_class == "out_of_fleet"
    assert ev.owning_repo == "__OUT_OF_FLEET__"


def test_load_eval_oracle_defaults_positive(tmp_path):
    case = _write_case(tmp_path, "pos-1", {"owning_repo": "cameraview", "expected_files": ["a.kt"]})
    ev = load_eval_oracle(case)
    assert ev.is_answerable is True and ev.negative_class is None
    assert ev.expected_files == ("a.kt",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_dataset.py -q`
Expected: FAIL with `ImportError: cannot import name 'load_eval_oracle'`.

- [ ] **Step 3: Add `EvalOracle` + `load_eval_oracle`**

In `groundloop/eval/dataset.py`, after the `load_oracle` function (end of file), append:

```python
@dataclass(frozen=True)
class EvalOracle:
    """The eval layer's view of the hidden oracle: the frozen-core owner + the negative-case fields
    (is_answerable / negative_class) that ride as EXTRA keys in oracle.json and are never read by the
    frozen core.types.Oracle. OFFLINE-GRADE ONLY."""
    owning_repo: str
    is_answerable: bool = True
    negative_class: str | None = None
    expected_files: tuple[str, ...] = ()


def load_eval_oracle(case: CaseRef) -> EvalOracle:
    """Read the hidden oracle including the negative-case fields. OFFLINE-GRADE ONLY — never call
    from the runner/arm path (it reads _oracle/)."""
    import json
    raw = json.loads((Path(case.case_dir) / "_oracle" / "oracle.json").read_text())
    return EvalOracle(
        owning_repo=raw["owning_repo"],
        is_answerable=bool(raw.get("is_answerable", True)),
        negative_class=raw.get("negative_class"),
        expected_files=tuple(raw.get("expected_files", [])),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_dataset.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/dataset.py tests/eval/test_negatives_dataset.py
git commit -m "feat(eval): EvalOracle + load_eval_oracle (negative-case oracle fields)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task A2: per-case catalog override (`case_catalog`)

**Files:**
- Modify: `groundloop/eval/dataset.py`
- Test: `tests/eval/test_negatives_dataset.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/eval/test_negatives_dataset.py`:

```python
from groundloop.eval.dataset import case_catalog


def test_case_catalog_reads_per_case_override(tmp_path):
    d = tmp_path / "oof-1"
    d.mkdir()
    (d / "ticket.json").write_text(json.dumps({"id": "oof-1", "logs": []}))
    (d / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "cameraview"}]))
    cat = case_catalog(CaseRef(case_id="oof-1", case_dir=str(d)))
    assert [r.name for r in cat] == ["organicmaps", "cameraview"]


def test_case_catalog_absent_returns_none(tmp_path):
    d = tmp_path / "pos-1"
    d.mkdir()
    (d / "ticket.json").write_text(json.dumps({"id": "pos-1", "logs": []}))
    assert case_catalog(CaseRef(case_id="pos-1", case_dir=str(d))) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_dataset.py -q`
Expected: FAIL with `ImportError: cannot import name 'case_catalog'`.

- [ ] **Step 3: Add `case_catalog`**

In `groundloop/eval/dataset.py`, append after `load_eval_oracle`:

```python
def case_catalog(case: CaseRef):
    """Loop-visible per-case candidate catalog (a catalog.json in the case dir), or None to fall back
    to the estate's global catalog. Used for OOF hold-out — the owner is removed from THIS ticket's
    candidate list. Reads only the loop-visible catalog.json, never _oracle/."""
    import json
    from groundloop.core.types import RepoRef
    p = Path(case.case_dir) / "catalog.json"
    if not p.is_file():
        return None
    return [RepoRef(r["name"]) for r in json.loads(p.read_text())]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_dataset.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/dataset.py tests/eval/test_negatives_dataset.py
git commit -m "feat(eval): per-case catalog override (OOF hold-out mechanism)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task A3: per-arm abstain thresholds (`Arm.tau_*` + runner override)

**Files:**
- Modify: `groundloop/eval/arms.py`, `groundloop/eval/runner.py`
- Test: `tests/eval/test_runner_percase.py`

- [ ] **Step 1: Write the failing test**

Create `tests/eval/test_runner_percase.py`:

```python
import json

from groundloop.core.types import RepoRef, RepoScore, Signals, Ticket
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef
from groundloop.eval.runner import EvalRunner


class _FakeIndex:
    """Rank each catalog repo by a fixed score map; unknown repos get 0.0 (deterministic)."""

    def __init__(self, scores):
        self.scores = scores

    def rank_repos(self, signals, catalog):
        return sorted((RepoScore(r, self.scores.get(r.name, 0.0)) for r in catalog),
                      key=lambda rs: rs.score, reverse=True)


class _FakeExtractor:
    def extract(self, logs, ticket):
        return Signals()


class _FakeIssues:
    def fetch(self, cid):
        return Ticket(id=cid, summary="", description="")


class _FakeEstate:
    def catalog(self):
        return [RepoRef("a"), RepoRef("b"), RepoRef("c")]


def _case(tmp_path, cid, catalog=None):
    d = tmp_path / cid
    d.mkdir()
    (d / "ticket.json").write_text(json.dumps({"id": cid, "logs": []}))
    if catalog is not None:
        (d / "catalog.json").write_text(json.dumps([{"name": n} for n in catalog]))
    return CaseRef(case_id=cid, case_dir=str(d))


def test_per_case_catalog_overrides_global(tmp_path):
    case = _case(tmp_path, "oof", catalog=["b", "c"])          # 'a' (the top-scorer) held out
    arm = Arm("membership+logs", _FakeIndex({"a": 5.0, "b": 1.0, "c": 0.0}), _FakeExtractor())
    runner = EvalRunner(issues=_FakeIssues(), estate=_FakeEstate(), tau_margin=1.0, tau_score=1.0)
    [rec] = runner.run([case], [arm])
    assert "a" not in rec.ranked_names and rec.ranked_names == ["b", "c"]


def test_per_arm_tau_overrides_runner_default(tmp_path):
    case = _case(tmp_path, "c")                                # global catalog (a,b,c)
    # cosine-like scores < 1.0: the runner default (tau_score 1.0) would abstain; the arm tau_score=0.0 answers
    arm = Arm("semantic+logs", _FakeIndex({"a": 0.6, "b": 0.1, "c": 0.0}), _FakeExtractor(),
              tau_margin=0.05, tau_score=0.0)
    runner = EvalRunner(issues=_FakeIssues(), estate=_FakeEstate(), tau_margin=1.0, tau_score=1.0)
    [rec] = runner.run([case], [arm])
    assert rec.predicted == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_runner_percase.py -q`
Expected: FAIL — `TypeError` (Arm has no `tau_margin`) and the runner ignores per-case catalog.

- [ ] **Step 3a: Add `tau_*` to `Arm` and set per-strategy defaults**

Replace the `Arm` dataclass and `build_arms` in `groundloop/eval/arms.py` with:

```python
@dataclass(frozen=True)
class Arm:
    name: str
    index: Any        # a CodeIndex: .rank_repos(signals, catalog)
    extractor: Any    # .extract(logs, ticket) -> Signals
    tau_margin: float | None = None   # per-arm abstain thresholds; None -> runner default
    tau_score: float | None = None


# Per-strategy abstain thresholds so refusal is REACHABLE on each score scale: FTS5 integer evidence
# counts (membership) vs bge-m3 cosine ~0.3-0.7 (semantic) vs the judge ladder. (docs SP1 §1.3 item 4)
_TAU = {"membership": (1.0, 1.0), "semantic": (0.05, 0.0), "judge": (1.0, 0.0)}


def build_arms(*, membership_index, semantic_index=None, judge_index=None) -> list[Arm]:
    mm, msc = _TAU["membership"]
    arms = [
        Arm("membership+text", membership_index, TextOnlyExtractor(), mm, msc),
        Arm("membership+logs", membership_index, AndroidSignalExtractor(), mm, msc),
    ]
    if semantic_index is not None:
        sm, ssc = _TAU["semantic"]
        arms += [
            Arm("semantic+text", semantic_index, TextOnlyExtractor(), sm, ssc),
            Arm("semantic+logs", semantic_index, AndroidSignalExtractor(), sm, ssc),
        ]
    if judge_index is not None:
        jm, jsc = _TAU["judge"]
        arms += [
            Arm("judge+text", judge_index, TextOnlyExtractor(), jm, jsc),
            Arm("judge+logs", judge_index, AndroidSignalExtractor(), jm, jsc),
        ]
    return arms
```

- [ ] **Step 3b: Use per-case catalog + per-arm τ in the runner**

In `groundloop/eval/runner.py`, replace the import line `from groundloop.eval.dataset import CaseRef` with:

```python
from groundloop.eval.dataset import CaseRef, case_catalog
```

and replace the entire `run` method body with:

```python
    def run(self, cases: Sequence[CaseRef], arms: Sequence[Arm]) -> list[MatchRecord]:
        global_catalog = self.estate.catalog()
        records: list[MatchRecord] = []
        for case in cases:
            catalog = case_catalog(case) or global_catalog        # per-case override (OOF hold-out)
            ticket = self.issues.fetch(case.case_id)              # loop-visible only
            for arm in arms:
                signals = arm.extractor.extract(ticket.logs, ticket)
                ranked = arm.index.rank_repos(signals, catalog)
                tm = arm.tau_margin if arm.tau_margin is not None else self.tau_margin
                ts = arm.tau_score if arm.tau_score is not None else self.tau_score
                d = decide(ranked, tau_margin=tm, tau_score=ts)
                records.append(MatchRecord(
                    case_id=case.case_id, arm=arm.name,
                    ranked_names=[r.repo.name for r in ranked],
                    scores=[r.score for r in ranked],
                    predicted=d.predicted, margin=d.margin, top1_score=d.top1_score))
        return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_runner_percase.py tests/eval/test_arms.py tests/eval/test_runner.py -q`
Expected: PASS (existing arm/runner tests still green — `tau_*` default to `None`).

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/arms.py groundloop/eval/runner.py tests/eval/test_runner_percase.py
git commit -m "feat(eval): per-arm abstain thresholds + per-case catalog in the runner" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task A4: scorecard — `is_answerable`, `abstention_recall_oof`, per-class breakdown

**Files:**
- Modify: `groundloop/eval/scorecard.py`
- Test: `tests/eval/test_negatives_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/eval/test_negatives_scoring.py`:

```python
from groundloop.eval.dataset import EvalOracle
from groundloop.eval.runner import MatchRecord
from groundloop.eval.scorecard import grade_all


def _rec(cid, arm, ranked, predicted):
    return MatchRecord(cid, arm, ranked, [float(len(ranked) - i) for i in range(len(ranked))],
                       predicted, 3.0, 5.0)


def test_bucket1_abstain_scores_plus_one():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_all([_rec("c", "a", ["x", "y"], None)], oracle_by_case={"c": oo}, c_values=(1.0,))
    sel = card["arms"]["a"]["selective"]
    assert sel["phi_c"]["1.0"] == 1.0                          # abstain on unanswerable = +1
    assert sel["abstention_recall_oof"]["value"] == 1.0
    assert card["arms"]["a"]["per_class"]["out_of_fleet"]["abstain_rate"] == 1.0


def test_bucket1_answer_is_penalized():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_all([_rec("c", "a", ["x", "y"], "x")], oracle_by_case={"c": oo}, c_values=(1.0,))
    sel = card["arms"]["a"]["selective"]
    assert sel["phi_c"]["1.0"] == -1.0                         # answered unanswerable = -c
    assert sel["abstention_recall_oof"]["value"] == 0.0


def test_bucket2_insufficient_signal_abstain_scores_zero():
    lo = EvalOracle("cameraview", is_answerable=True, negative_class="insufficient_signal")
    card = grade_all([_rec("c", "a", ["x", "cameraview"], None)], oracle_by_case={"c": lo}, c_values=(1.0,))
    sel = card["arms"]["a"]["selective"]
    assert sel["phi_c"]["1.0"] == 0.0                          # abstain on answerable = 0
    assert sel["abstention_recall_oof"]["n_unanswerable"] == 0  # answerable -> not in OOF denominator


def test_forced_recall_excludes_unanswerable():
    recs = [_rec("p", "a", ["cameraview", "x"], "cameraview"),          # positive hit
            _rec("o", "a", ["x", "y"], None)]                            # OOF abstain
    oracles = {"p": EvalOracle("cameraview"),
               "o": EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")}
    card = grade_all(recs, oracle_by_case=oracles, ks=(1,), c_values=(1.0,))
    f = card["arms"]["a"]["forced"]
    assert f["n_answerable"] == 1 and f["recall@1"]["value"] == 1.0     # OOF not in the denominator
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_scoring.py -q`
Expected: FAIL — `KeyError: 'abstention_recall_oof'` / `'per_class'` / `'n_answerable'`.

- [ ] **Step 3: Update `score_match` and `grade_all`**

In `groundloop/eval/scorecard.py`, replace the `score_match` function and the `grade_all` function with:

```python
def score_match(rec: MatchRecord, oracle) -> dict:
    owner = oracle.owning_repo
    is_answerable = bool(getattr(oracle, "is_answerable", True))
    negative_class = getattr(oracle, "negative_class", None)
    rank = repo_rank(rec.ranked_names, owner)
    answered = rec.predicted is not None
    return {
        "case_id": rec.case_id,
        "repo_rank": rank,
        "recall@1": bool(rec.ranked_names[:1] == [owner]),   # forced view (abstain-agnostic)
        "answered": answered,
        "correct": bool(answered and rec.predicted == owner),
        "answerable": is_answerable,
        "negative_class": negative_class,
        "ranked_names": rec.ranked_names,
    }


def _wrap(k: int, n: int) -> dict:
    return {"value": (k / n if n else 0.0), "wilson95": list(wilson(k, n))}


def grade_all(records, *, oracle_by_case, ks=(1, 3, 5), c_values=(0.5, 1.0, 2.0)) -> dict:
    by_arm: dict[str, list] = defaultdict(list)
    for rec in records:
        by_arm[rec.arm].append(score_match(rec, oracle_by_case[rec.case_id]))

    arms: dict[str, dict] = {}
    for arm, ms in by_arm.items():
        n = len(ms)
        # FORCED view: recall/mrr over the ANSWERABLE subset (an OOF case can never be recall@1)
        ans = [m for m in ms if m["answerable"]]
        na = len(ans)
        forced = {"n_answerable": na}
        for k in ks:
            hits = sum(1 for m in ans if m["repo_rank"] and m["repo_rank"] <= k)
            forced[f"recall@{k}"] = _wrap(hits, na)
        ranks = [m["repo_rank"] for m in ans if m["repo_rank"]]
        forced["mrr"] = sum(1.0 / r for r in ranks) / na if na else 0.0
        forced["mean_repo_rank"] = (sum(ranks) / len(ranks)) if ranks else 0.0

        # SELECTIVE view over ALL cases (Phi_c handles answerable vs unanswerable)
        answered = [m for m in ms if m["answered"]]
        correct_answered = sum(1 for m in answered if m["correct"])
        unans = [m for m in ms if not m["answerable"]]
        abst_unans = sum(1 for m in unans if not m["answered"])
        selective = {
            "coverage": len(answered) / n if n else 0.0,
            "selective_accuracy": _wrap(correct_answered, len(answered)),
            "selective_risk": 1.0 - (correct_answered / len(answered)) if answered else 0.0,
            "phi_c": {str(c): phi_c(ms, c=c) for c in c_values},
            "abstention_recall_oof": {"value": (abst_unans / len(unans) if unans else None),
                                      "n_unanswerable": len(unans)},
        }

        # Per negative_class breakdown (for Bucket-1, abstaining is the correct action)
        per_class: dict[str, dict] = {}
        for m in ms:
            cls = m["negative_class"]
            if cls is None:
                continue
            b = per_class.setdefault(cls, {"n": 0, "abstained": 0})
            b["n"] += 1
            b["abstained"] += 0 if m["answered"] else 1
        for b in per_class.values():
            b["abstain_rate"] = b["abstained"] / b["n"] if b["n"] else 0.0

        arms[arm] = {"n": n, "forced": forced, "selective": selective, "per_class": per_class}
    return {"arms": arms, "n_cases": len({m["case_id"] for ms in by_arm.values() for m in ms})}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_scoring.py tests/eval/test_scorecard.py -q`
Expected: PASS — new tests pass AND the existing `test_scorecard.py` stays green (its cases are answerable, so forced-over-answerable == forced-over-all).

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/scorecard.py tests/eval/test_negatives_scoring.py
git commit -m "feat(eval): scorecard abstention_recall_oof + per-class + answerable-only forced recall" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task A5: realistic negative fixtures + oracle-blindness invariant

**Files:**
- Create: `tests/fixtures/android_ivi/negatives/oof-hold-1/{ticket.json,logs/000.txt,catalog.json,_oracle/oracle.json}`
- Create: `tests/fixtures/android_ivi/negatives/lowsig-1/{ticket.json,_oracle/oracle.json}`
- Test: `tests/eval/test_negatives_fixtures.py`

The existing micro-fleet catalog is `["android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview"]` (`tests/fixtures/android_ivi/catalog.json`). The hold-out fixture holds out `cameraview`; the low-signal fixture's real owner is `organicmaps`.

- [ ] **Step 1: Write the failing test**

Create `tests/eval/test_negatives_fixtures.py`:

```python
import json
from pathlib import Path

from groundloop.eval.dataset import CaseRef, case_catalog, load_eval_oracle

NEG = Path(__file__).parent.parent / "fixtures" / "android_ivi" / "negatives"
CATALOG_NAMES = {"android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview"}


def _ref(name: str) -> CaseRef:
    d = NEG / name
    return CaseRef(case_id=d.name, case_dir=str(d))


def test_oof_holdout_fixture_excludes_owner_from_catalog():
    case = _ref("oof-hold-1")
    ev = load_eval_oracle(case)
    assert ev.is_answerable is False and ev.negative_class == "out_of_fleet"
    cat = [r.name for r in case_catalog(case)]
    assert ev.owning_repo not in cat and len(cat) >= 2       # owner held out of THIS ticket's candidates


def test_lowsig_fixture_is_answerable_with_global_catalog():
    case = _ref("lowsig-1")
    ev = load_eval_oracle(case)
    assert ev.is_answerable is True and ev.negative_class == "insufficient_signal"
    assert case_catalog(case) is None                        # falls back to the global catalog


def test_negative_fixtures_are_oracle_blind():
    for name in ("oof-hold-1", "lowsig-1"):
        d = NEG / name
        assert not any(c in name for c in CATALOG_NAMES), f"case dir {name} embeds an owner name"
        tj = (d / "ticket.json").read_text()
        raw = json.loads(tj)
        for field in ("id", "summary", "description", "component"):
            assert not any(c in str(raw.get(field, "")) for c in CATALOG_NAMES), \
                f"owner leaked into loop-visible ticket.{field}"
        for hidden in ("is_answerable", "negative_class", "held_out_repo", "owning_repo"):
            assert hidden not in tj, f"{hidden} leaked into loop-visible ticket.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_fixtures.py -q`
Expected: FAIL — the fixture files do not exist yet (`FileNotFoundError`).

- [ ] **Step 3: Create the fixture files**

Create `tests/fixtures/android_ivi/negatives/oof-hold-1/ticket.json`:

```json
{
  "id": "NEG-OOF-1",
  "summary": "Live preview freezes intermittently on some devices",
  "description": "After the app runs for a while the on-screen live preview stops updating until restart. No crash is shown; the UI just stops refreshing.",
  "component": "",
  "status": "Open",
  "comments": [],
  "logs": [{"path": "logs/000.txt", "kind": "logcat"}]
}
```

Create `tests/fixtures/android_ivi/negatives/oof-hold-1/logs/000.txt`:

```text
01-02 03:04:05.678 1234 1250 W SurfaceView: updateWindow -- surface not valid, retrying
01-02 03:04:06.101 1234 1250 I Choreographer: Skipped 42 frames! The main thread has too much work.
01-02 03:04:06.550 1234 1250 W FrameTracker: dropped frames while rendering preview
```

Create `tests/fixtures/android_ivi/negatives/oof-hold-1/catalog.json` (owner `cameraview` held out):

```json
[{"name": "android-gpuimage-plus"}, {"name": "organicmaps"}, {"name": "androidx-media"}]
```

Create `tests/fixtures/android_ivi/negatives/oof-hold-1/_oracle/oracle.json`:

```json
{
  "owning_repo": "cameraview",
  "expected_files": [],
  "required_apis": [],
  "is_answerable": false,
  "negative_class": "out_of_fleet",
  "held_out_repo": "cameraview"
}
```

Create `tests/fixtures/android_ivi/negatives/lowsig-1/ticket.json`:

```json
{
  "id": "NEG-LOWSIG-1",
  "summary": "Navigation sometimes reroutes for no reason",
  "description": "While driving, the route occasionally recalculates even when I stay on the road. Happens randomly, I do not have logs.",
  "component": "",
  "status": "Open",
  "comments": [],
  "logs": []
}
```

Create `tests/fixtures/android_ivi/negatives/lowsig-1/_oracle/oracle.json`:

```json
{
  "owning_repo": "organicmaps",
  "expected_files": ["src/main/java/app/route/RoutePlanner.java"],
  "required_apis": [],
  "is_answerable": true,
  "negative_class": "insufficient_signal"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_negatives_fixtures.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/android_ivi/negatives tests/eval/test_negatives_fixtures.py
git commit -m "test(eval): realistic OOF-holdout + insufficient-signal negative fixtures (oracle-blind)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task A6: wire `gloop eval` to the negative oracle + report `oof_recall`

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_run_eval`)
- Test: `tests/eval/test_cli_eval_oof.py`

- [ ] **Step 1: Write the failing test**

Create `tests/eval/test_cli_eval_oof.py`:

```python
import json
import shutil
from pathlib import Path

from groundloop.cli import main
from tests.fixtures.atlas_fixture import build_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures" / "android_ivi"


def test_eval_cli_scores_oof_case(tmp_path):
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(FIX / "gpuimage-352", ds / "GP-352")              # a positive case
    shutil.copytree(FIX / "negatives" / "oof-hold-1", ds / "oof-hold-1")  # an OOF negative
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "scorecard.json"
    rc = main(["eval", "--dataset", str(ds), "--catalog", str(FIX / "catalog.json"),
               "--index-db", db, "--out", str(out)])
    assert rc == 0
    card = json.loads(out.read_text())
    sel = card["arms"]["membership+logs"]["selective"]
    assert sel["abstention_recall_oof"]["n_unanswerable"] == 1        # the OOF case counted
    assert "n_answerable" in card["arms"]["membership+logs"]["forced"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_cli_eval_oof.py -q`
Expected: FAIL — `KeyError: 'abstention_recall_oof'` (the CLI still loads the plain `Oracle`, so every case is treated answerable and `n_unanswerable` is 0 / the key path differs).

- [ ] **Step 3: Use `load_eval_oracle` and print `oof_recall`**

In `groundloop/cli/__init__.py`, inside `_run_eval`:

Change the dataset import line from:

```python
    from groundloop.eval.dataset import load_cases, load_oracle
```

to:

```python
    from groundloop.eval.dataset import load_cases, load_eval_oracle
```

Change the offline-grade line from:

```python
    oracle_by_case = {c.case_id: load_oracle(c) for c in cases}     # OFFLINE grade — oracle read here only
```

to:

```python
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}  # OFFLINE grade — oracle read here only
```

Replace the per-arm print loop:

```python
    for arm, a in card["arms"].items():
        print(f"{arm}: recall@1={a['forced']['recall@1']['value']:.2f} "
              f"coverage={a['selective']['coverage']:.2f} phi_1={a['selective']['phi_c']['1.0']:.2f}")
    return 0
```

with:

```python
    for arm, a in card["arms"].items():
        oof = a["selective"]["abstention_recall_oof"]["value"]
        oof_s = "n/a" if oof is None else f"{oof:.2f}"
        print(f"{arm}: recall@1={a['forced']['recall@1']['value']:.2f} "
              f"coverage={a['selective']['coverage']:.2f} phi_1={a['selective']['phi_c']['1.0']:.2f} "
              f"oof_recall={oof_s}")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_cli_eval_oof.py tests/eval/test_cli_eval.py -q`
Expected: PASS — new test passes; the existing `test_cli_eval.py` stays green (the print line still contains `recall@1=`/`coverage=`/`phi_1=`; only an extra `oof_recall=` field is appended).

- [ ] **Step 5: Full suite + lint, then commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all green; the 5 gated-live skips remain skipped).

Run: `.venv/bin/ruff check groundloop tests`
Expected: `All checks passed!`

```bash
git add groundloop/cli/__init__.py tests/eval/test_cli_eval_oof.py
git commit -m "feat(eval): gloop eval reads the negative oracle + reports oof_recall" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (performed against the spec)

**1. Spec coverage (SP1 §1.3 wiring items):**
- Un-strip `is_answerable`/`negative_class` → Task A1 (`EvalOracle`/`load_eval_oracle`). ✅
- Per-ticket catalog → Task A2 (`case_catalog`) + A3 (runner uses it). ✅
- `score_match` passes `is_answerable` → Task A4. ✅
- Per-arm calibrated τ → Task A3 (`Arm.tau_*` + `_TAU` defaults; runner override). ✅ (Calibration *on the calib split* is deferred to SP1b's dataset; the mechanism + reachable-refusal defaults land here.)
- `abstention_recall_oof` + per-class breakdown → Task A4. ✅
- Leak red-test over mined negatives → **deferred to SP1b** (this plan asserts oracle-blindness over hand-authored fixtures in Task A5, not mined output). Noted in "Out of scope."
- Two scoring buckets (§1.1) → Task A4 tests (Bucket-1 abstain=+1 / answer=−c; Bucket-2 abstain=0). ✅

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — every step has complete code. ✅

**3. Type consistency:** `EvalOracle(owning_repo, is_answerable, negative_class, expected_files)` defined in A1 and constructed identically in A4/A5 tests. `case_catalog` returns `list[RepoRef] | None` (A2), consumed as `case_catalog(case) or global_catalog` (A3). `Arm.tau_margin/tau_score` (A3) read in the runner as `arm.tau_margin`/`arm.tau_score`. Scorecard keys `forced.n_answerable`, `selective.abstention_recall_oof.{value,n_unanswerable}`, `per_class.<cls>.{n,abstained,abstain_rate}` are produced in A4 and asserted with the same names in A4/A6 tests. `score_match` uses `getattr(oracle, "is_answerable", True)` so the pre-existing `test_scorecard.py` (which passes a plain `core.types.Oracle`) stays green. ✅
