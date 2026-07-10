# Functional-Bug Matching Arm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a text-primary (title+description similarity) + optional-log + honest-abstention matching arm that attributes no-crash functional bugs (wrong UI text, audio, CarPlay/projection) to the owning repo, plus a crash-vs-functional eval split — all as a frozen-safe bolt-on.

**Architecture:** A new `(extractor, index)` Arm composed at the CLI root (like v2's `flood/faultslice/routing`), zero edits to `core/`/`EvalRunner`/`AtlasIndex.rank_repos`. Ticket prose rides through the frozen `Signals` seam as a reserved `symbols[0]` slot; a lightweight per-repo bge-m3 text-profile store (no 12 GB atlas rebuild) backs max-cosine ranking; an optional log-token FTS channel RRF-fuses in; `decide()` abstains. A `bug_kind` (crash|functional) offline oracle field + a `by_bug_kind` split in `grade_all` report the two classes separately.

**Tech Stack:** Python 3.12, sqlite (atlas `Store`), bge-m3 via `GatewayEmbedder`/`StubEmbedder`, pytest, ruff.

Spec: `docs/superpowers/specs/2026-07-10-functional-bug-match-design.md`. Run tests with `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check groundloop tests`. Commit only when green + ruff clean; end messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

**Frozen / gated — never edit:** `groundloop/core/`, `engines/atlas/store.py` schema, `AtlasIndex.rank_repos`, `owner_tokens.py`, `repo_routing.py`, `mine/` (incl. `mine/emit.py`). READ-only where seeding.

---

## Phase 1 — Eval `bug_kind` split scaffolding + labeling

### Task 1.1: Add `bug_kind` to the offline `EvalOracle`

**Files:**
- Modify: `groundloop/eval/dataset.py` (EvalOracle + load_eval_oracle)
- Test: `tests/eval/test_dataset.py`

- [ ] **Step 1: Write the failing test** — append to `tests/eval/test_dataset.py`:

```python
def test_eval_oracle_reads_bug_kind(tmp_path):
    import json
    from groundloop.eval.dataset import CaseRef, load_eval_oracle
    d = tmp_path / "c1"
    (d / "_oracle").mkdir(parents=True)
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "oboe", "is_answerable": True, "bug_kind": "functional"}))
    o = load_eval_oracle(CaseRef(case_id="c1", case_dir=str(d)))
    assert o.bug_kind == "functional"


def test_eval_oracle_bug_kind_defaults_none(tmp_path):
    import json
    from groundloop.eval.dataset import CaseRef, load_eval_oracle
    d = tmp_path / "c2"
    (d / "_oracle").mkdir(parents=True)
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "oboe"}))
    assert load_eval_oracle(CaseRef(case_id="c2", case_dir=str(d))).bug_kind is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_dataset.py -k bug_kind -q`
Expected: FAIL — `EvalOracle` has no field `bug_kind`.

- [ ] **Step 3: Implement** — in `groundloop/eval/dataset.py`, add the field to `EvalOracle` and read it in `load_eval_oracle`:

```python
@dataclass(frozen=True)
class EvalOracle:
    owning_repo: str
    is_answerable: bool = True
    negative_class: str | None = None
    bug_kind: str | None = None                 # 'crash' | 'functional' | None (offline-only split)
    expected_files: tuple[str, ...] = ()
    required_apis: tuple[str, ...] = ()
```

In `load_eval_oracle`, add `bug_kind=raw.get("bug_kind")` to the constructor call:

```python
    return EvalOracle(
        owning_repo=raw["owning_repo"],
        is_answerable=bool(raw.get("is_answerable", True)),
        negative_class=raw.get("negative_class"),
        bug_kind=raw.get("bug_kind"),
        expected_files=tuple(raw.get("expected_files", [])),
        required_apis=tuple(raw.get("required_apis", [])),
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_dataset.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/dataset.py tests/eval/test_dataset.py
git commit -m "feat(eval): bug_kind field on EvalOracle (offline crash|functional split)"
```

### Task 1.2: Surface `bug_kind` per-record in `score_match`

**Files:**
- Modify: `groundloop/eval/scorecard.py` (score_match)
- Test: `tests/eval/test_scorecard.py`

- [ ] **Step 1: Write the failing test** — append:

```python
def test_score_match_surfaces_bug_kind():
    from groundloop.eval.scorecard import score_match
    from groundloop.eval.runner import MatchRecord
    from groundloop.eval.dataset import EvalOracle
    rec = MatchRecord(case_id="c", arm="a", ranked_names=["oboe"], scores=[1.0],
                      predicted="oboe", margin=1.0, top1_score=1.0)
    m = score_match(rec, EvalOracle("oboe", bug_kind="functional"))
    assert m["bug_kind"] == "functional"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_scorecard.py -k bug_kind -q`
Expected: FAIL — KeyError `bug_kind`.

- [ ] **Step 3: Implement** — in `score_match`, add the read (mirrors `negative_class`) and the returned key:

```python
def score_match(rec: MatchRecord, oracle) -> dict:
    owner = oracle.owning_repo
    is_answerable = bool(getattr(oracle, "is_answerable", True))
    negative_class = getattr(oracle, "negative_class", None)
    bug_kind = getattr(oracle, "bug_kind", None)
    rank = repo_rank(rec.ranked_names, owner)
    answered = rec.predicted is not None
    return {
        "case_id": rec.case_id,
        "repo_rank": rank,
        "recall@1": bool(rec.ranked_names[:1] == [owner]),
        "answered": answered,
        "correct": bool(answered and rec.predicted == owner),
        "answerable": is_answerable,
        "negative_class": negative_class,
        "bug_kind": bug_kind,
        "ranked_names": rec.ranked_names,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_scorecard.py -q`
Expected: PASS (existing tests unaffected — additive key).

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/scorecard.py tests/eval/test_scorecard.py
git commit -m "feat(eval): surface bug_kind per-record in score_match"
```

### Task 1.3: `by_bug_kind` grouping in `grade_all` (full metrics per subset)

**Files:**
- Modify: `groundloop/eval/scorecard.py` (extract `_grade_records`, add `by_bug_kind`)
- Test: `tests/eval/test_scorecard.py`

- [ ] **Step 1: Write the failing test** — append:

```python
def test_grade_all_splits_by_bug_kind():
    from groundloop.eval.scorecard import grade_all
    from groundloop.eval.runner import MatchRecord
    from groundloop.eval.dataset import EvalOracle
    recs = [
        MatchRecord("c1", "a", ["oboe", "newpipe"], [2.0, 1.0], "oboe", 1.0, 2.0),     # functional hit
        MatchRecord("c2", "a", ["newpipe", "oboe"], [2.0, 1.0], "newpipe", 1.0, 2.0),  # crash hit
    ]
    oracles = {"c1": EvalOracle("oboe", bug_kind="functional"),
               "c2": EvalOracle("newpipe", bug_kind="crash")}
    card = grade_all(recs, oracle_by_case=oracles, ks=(1,), c_values=(1.0,))
    bbk = card["arms"]["a"]["by_bug_kind"]
    assert set(bbk) == {"functional", "crash"}
    assert bbk["functional"]["forced"]["recall@1"]["value"] == 1.0
    assert bbk["functional"]["n"] == 1
    assert bbk["crash"]["selective"]["coverage"] == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_scorecard.py -k by_bug_kind -q`
Expected: FAIL — no `by_bug_kind` key.

- [ ] **Step 3: Implement** — refactor the per-arm body of `grade_all` into a helper and add the split. Replace the `for arm, ms in by_arm.items():` loop body plus add `_grade_records` above `grade_all`:

```python
def _grade_records(ms, ks, c_values) -> dict:
    n = len(ms)
    ans = [m for m in ms if m["answerable"]]
    na = len(ans)
    forced = {"n_answerable": na}
    for k in ks:
        hits = sum(1 for m in ans if m["repo_rank"] and m["repo_rank"] <= k)
        forced[f"recall@{k}"] = _wrap(hits, na)
    ranks = [m["repo_rank"] for m in ans if m["repo_rank"]]
    forced["mrr"] = sum(1.0 / r for r in ranks) / na if na else 0.0
    forced["mean_repo_rank"] = (sum(ranks) / len(ranks)) if ranks else 0.0

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
    return {"n": n, "forced": forced, "selective": selective, "per_class": per_class}


def grade_all(records, *, oracle_by_case, ks=(1, 3, 5), c_values=(0.5, 1.0, 2.0)) -> dict:
    by_arm: dict[str, list] = defaultdict(list)
    for rec in records:
        by_arm[rec.arm].append(score_match(rec, oracle_by_case[rec.case_id]))

    arms: dict[str, dict] = {}
    for arm, ms in by_arm.items():
        block = _grade_records(ms, ks, c_values)
        kinds: dict[str, list] = defaultdict(list)
        for m in ms:
            if m.get("bug_kind"):
                kinds[m["bug_kind"]].append(m)
        if kinds:
            block["by_bug_kind"] = {bk: _grade_records(sub, ks, c_values)
                                    for bk, sub in kinds.items()}
        arms[arm] = block
    return {"arms": arms, "n_cases": len({m["case_id"] for ms in by_arm.values() for m in ms})}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/ -q`
Expected: PASS — existing `test_grade_all_aggregates_per_arm` / negatives tests still green (arm-level shape unchanged; `by_bug_kind` only added when present).

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/scorecard.py tests/eval/test_scorecard.py
git commit -m "feat(eval): by_bug_kind subset grading (full forced+selective per crash|functional)"
```

### Task 1.4: Render `by_bug_kind` rows in the markdown report

**Files:**
- Modify: `groundloop/eval/report.py`
- Test: `tests/eval/test_report.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/eval/test_report.py`:

```python
from groundloop.eval.report import render_markdown


def _sub(recall1, cov):
    return {"n": 1, "forced": {"recall@1": {"value": recall1}, "mrr": 0.0},
            "selective": {"coverage": cov, "selective_accuracy": {"value": recall1},
                          "phi_c": {"1.0": recall1}}}


def test_render_includes_bug_kind_section():
    card = {"n_cases": 2, "arms": {"functional": {
        "n": 2, "forced": {"recall@1": {"value": 0.5}, "mrr": 0.5},
        "selective": {"coverage": 1.0, "selective_accuracy": {"value": 0.5}, "phi_c": {"1.0": 0.5}},
        "by_bug_kind": {"functional": _sub(0.9, 1.0), "crash": _sub(0.1, 1.0)}}}}
    md = render_markdown(card)
    assert "by bug_kind" in md
    assert "functional / functional" in md and "0.90" in md


def test_render_without_bug_kind_unchanged():
    card = {"n_cases": 1, "arms": {"a": {
        "n": 1, "forced": {"recall@1": {"value": 1.0}, "mrr": 1.0},
        "selective": {"coverage": 1.0, "selective_accuracy": {"value": 1.0}, "phi_c": {"1.0": 1.0}}}}}
    assert "by bug_kind" not in render_markdown(card)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_report.py -q`
Expected: FAIL — no "by bug_kind" section.

- [ ] **Step 3: Implement** — replace `render_markdown` in `groundloop/eval/report.py`:

```python
"""Render a scorecard dict to a compact markdown table (docs/type2-evaluation.md §7.4)."""
from __future__ import annotations


def _row(name: str, a: dict) -> str:
    f, s = a["forced"], a["selective"]
    return (f"| {name} | {a['n']} | {f['recall@1']['value']:.2f} | {f['mrr']:.2f} | "
            f"{s['coverage']:.2f} | {s['selective_accuracy']['value']:.2f} | {s['phi_c']['1.0']:.2f} |")


def render_markdown(card: dict) -> str:
    head = ["| arm | n | recall@1 | mrr | coverage | sel-acc | Phi_1 |",
            "|---|---|---|---|---|---|---|"]
    lines = ["# Type-2 scorecard", "", f"cases: {card.get('n_cases', 0)}", "", *head]
    for arm, a in card["arms"].items():
        lines.append(_row(arm, a))

    split = [(arm, bk, sub) for arm, a in card["arms"].items()
             for bk, sub in a.get("by_bug_kind", {}).items()]
    if split:
        lines += ["", "## by bug_kind", "", "| arm / kind | n | recall@1 | mrr | coverage | sel-acc | Phi_1 |",
                  "|---|---|---|---|---|---|---|"]
        for arm, bk, sub in split:
            lines.append(_row(f"{arm} / {bk}", sub))
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_report.py tests/eval/test_cli_eval.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/eval/report.py tests/eval/test_report.py
git commit -m "feat(eval): render per-bug_kind rows in the scorecard markdown"
```

### Task 1.5: `bug_kind` labeling pass + `gloop label-bugkind`

**Files:**
- Create: `groundloop/eval/label_bug_kind.py`
- Modify: `groundloop/cli/__init__.py` (add `_run_label_bugkind` + subparser + dispatch)
- Test: `tests/eval/test_label_bug_kind.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/eval/test_label_bug_kind.py`:

```python
import json
from pathlib import Path

from groundloop.eval.label_bug_kind import stamp_bug_kind


def _case(root, cid, oracle):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle))
    return d


def test_stamp_crash_when_fault_frame_present(tmp_path):
    _case(tmp_path, "crash1", {"owning_repo": "oboe", "fault_frame": "a.B.c"})
    _case(tmp_path, "func1", {"owning_repo": "newpipe"})
    n = stamp_bug_kind(str(tmp_path))
    assert n == 2
    crash = json.loads((tmp_path / "crash1" / "_oracle" / "oracle.json").read_text())
    func = json.loads((tmp_path / "func1" / "_oracle" / "oracle.json").read_text())
    assert crash["bug_kind"] == "crash"
    assert func["bug_kind"] == "functional"


def test_stamp_is_idempotent_and_preserves_keys(tmp_path):
    _case(tmp_path, "c", {"owning_repo": "oboe", "expected_files": ["x.java"], "fault_frame": "a.B.c"})
    stamp_bug_kind(str(tmp_path))
    stamp_bug_kind(str(tmp_path))
    o = json.loads((tmp_path / "c" / "_oracle" / "oracle.json").read_text())
    assert o["bug_kind"] == "crash" and o["expected_files"] == ["x.java"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/eval/test_label_bug_kind.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/eval/label_bug_kind.py`:

```python
"""Offline labeling pass: stamp bug_kind (crash|functional) into each case's _oracle/oracle.json.
crash = a fault anchor was extracted (fault_frame present); functional = prose-only / no anchor.
OFFLINE artifact — bug_kind is never read by the loop (only by the scorecard). Idempotent."""
from __future__ import annotations

import json
from pathlib import Path


def _classify(oracle: dict) -> str:
    return "crash" if oracle.get("fault_frame") else "functional"


def stamp_bug_kind(dataset_root: str) -> int:
    n = 0
    for d in sorted(Path(dataset_root).iterdir()):
        op = d / "_oracle" / "oracle.json"
        if not op.is_file():
            continue
        oracle = json.loads(op.read_text())
        oracle["bug_kind"] = _classify(oracle)
        op.write_text(json.dumps(oracle, indent=2, ensure_ascii=False))
        n += 1
    return n
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/eval/test_label_bug_kind.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the CLI** — in `groundloop/cli/__init__.py` add the runner (near `_run_eval`):

```python
def _run_label_bugkind(args) -> int:
    from groundloop.eval.label_bug_kind import stamp_bug_kind
    n = stamp_bug_kind(args.dataset)
    print(f"label-bugkind: stamped {n} cases -> {args.dataset}")
    return 0
```

Add the subparser (near the `eval` subparser block):

```python
    lb = sub.add_parser("label-bugkind", help="offline: stamp bug_kind (crash|functional) into oracle.json")
    lb.add_argument("--dataset", required=True, help="dataset root (case dirs with _oracle/oracle.json)")
```

Add the dispatch line (in `main`, near `if args.cmd == "eval":`):

```python
    if args.cmd == "label-bugkind":
        return _run_label_bugkind(args)
```

- [ ] **Step 6: Test the CLI wiring + commit** — append to `tests/eval/test_label_bug_kind.py`:

```python
def test_cli_label_bugkind(tmp_path, capsys):
    from groundloop.cli import main
    _case(tmp_path, "c", {"owning_repo": "oboe", "fault_frame": "a.B.c"})
    assert main(["label-bugkind", "--dataset", str(tmp_path)]) == 0
    assert "stamped 1" in capsys.readouterr().out
```

Run: `.venv/bin/python -m pytest tests/eval/test_label_bug_kind.py -q && .venv/bin/ruff check groundloop tests`
Expected: PASS + clean.

```bash
git add groundloop/eval/label_bug_kind.py groundloop/cli/__init__.py tests/eval/test_label_bug_kind.py
git commit -m "feat(eval): gloop label-bugkind offline crash|functional stamping pass"
```

---

## Phase 2 — Functional extractor + repo-text profile + FunctionalTextIndex (text-cosine)

### Task 2.1: `FunctionalTextExtractor` (prose → reserved `symbols[0]`)

**Files:**
- Create: `groundloop/domains/android_ivi/functional_signals.py`
- Test: `tests/domains/test_functional_signals.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/domains/test_functional_signals.py`:

```python
from groundloop.core.types import LogAttachment, Ticket
from groundloop.domains.android_ivi.functional_signals import (
    PROSE_MARK, FunctionalTextExtractor, prose_query)


def test_extractor_packs_summary_and_description_into_symbols():
    t = Ticket(id="t", summary="No sound on Bluetooth", description="Audio stutters in podcasts")
    sig = FunctionalTextExtractor().extract((), t)
    assert len(sig.symbols) == 1 and sig.symbols[0].startswith(PROSE_MARK)
    q = prose_query(sig)
    assert "bluetooth" in q and "podcasts" in q          # summary AND description, lowercased
    assert not sig.packages and not sig.classes           # no crash tokens for a prose-only ticket


def test_extractor_keeps_optional_log_tokens_out_of_symbols():
    t = Ticket(id="t", summary="audio underrun", description="stutter")
    log = LogAttachment(path="l", kind="logcat", content="W AAudio: liboboe.so onAudioReady underrun")
    sig = FunctionalTextExtractor().extract((log,), t)
    assert "liboboe.so" in sig.libraries                  # log .so is captured as optional evidence
    assert len(sig.symbols) == 1 and sig.symbols[0].startswith(PROSE_MARK)   # symbols stays prose-only
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/domains/test_functional_signals.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/domains/android_ivi/functional_signals.py`:

```python
"""Functional (no-crash) matching: pack ticket summary+description prose into the frozen Signals
seam so a text-similarity index can rank repos when there is no fault frame. Prose rides as the
single reserved element Signals.symbols[0], prefixed with PROSE_MARK so a dispatcher can tell a
prose query from crash symbols. Optional log tokens (audio/connection) ride in the other fields."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import LogAttachment, Signals, Ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor

PROSE_MARK = "\x00fn\x00"      # reserves symbols[0] as a prose query (crash symbols never start with it)


def normalize_prose(ticket: Ticket) -> str:
    return " ".join((ticket.summary + " " + ticket.description).lower().split())


def prose_query(signals: Signals) -> str:
    """Recover the prose query from a functional Signals (strips PROSE_MARK). '' if none."""
    if signals.symbols and signals.symbols[0].startswith(PROSE_MARK):
        return signals.symbols[0][len(PROSE_MARK):]
    return ""


def pack_prose(ticket: Ticket, logs: Sequence[LogAttachment]) -> Signals:
    prose = normalize_prose(ticket)
    # optional log evidence only (empty description so ticket prose is NOT double-counted here)
    inner = AndroidSignalExtractor().extract(logs, Ticket(id=ticket.id, summary="", description=""))
    return Signals(symbols=(PROSE_MARK + prose,),
                   packages=inner.packages, classes=inner.classes, methods=inner.methods,
                   libraries=inner.libraries, errors=inner.errors)   # drop inner.symbols (reserved)


class FunctionalTextExtractor:
    """SignalExtractor for the `functional` arm — prose query + optional log tokens."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        return pack_prose(ticket, logs)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/domains/test_functional_signals.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/domains/android_ivi/functional_signals.py tests/domains/test_functional_signals.py
git commit -m "feat(android): FunctionalTextExtractor — prose into reserved Signals.symbols[0]"
```

### Task 2.2: Repo-text profile builder (small bge-m3 profile db)

**Files:**
- Create: `groundloop/adapters/index/text_profile.py`
- Test: `tests/index/test_text_profile.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/index/test_text_profile.py`:

```python
from groundloop.adapters.index.text_profile import build_text_profiles, gather_repo_texts
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.engines.atlas.store import Store


def test_build_text_profiles_writes_repo_vectors(tmp_path):
    db = str(tmp_path / "profiles.db")
    build_text_profiles({"oboe": ["audio playback streaming", "low latency"],
                         "newpipe": ["video player youtube"]}, db, StubEmbedder(dim=16))
    store = Store(db)
    qvec = StubEmbedder(dim=16).embed(["audio playback"])[0]
    hits = store.vector_search(qvec, k=5, repos=["oboe", "newpipe"])
    assert hits and hits[0][0].repo == "oboe"          # audio query nearest to oboe profile


def test_gather_repo_texts_reads_readme(tmp_path):
    repo = tmp_path / "myrepo"
    (repo / "app").mkdir(parents=True)
    (repo / "README.md").write_text("# MyRepo\nHandles audio playback and Bluetooth routing.")
    (repo / "app" / "build.gradle").write_text('android { namespace "com.acme.audio" }')
    chunks = gather_repo_texts(str(repo))
    joined = " ".join(chunks).lower()
    assert "audio playback" in joined and "com.acme.audio" in joined
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_text_profile.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/adapters/index/text_profile.py`:

```python
"""Lightweight per-repo TEXT profile store: embed cheap, always-available repo text (README,
manifest namespace/applicationId, module & package identifiers) with bge-m3 into a SMALL atlas.db
(kind='profile' units). This is NOT the 12 GB code atlas — the identical builder runs in production.
Anti-leak: reads only public repo text, never a case oracle (see the red-test)."""
from __future__ import annotations

import os
import re

from groundloop.engines.atlas.store import Store, Unit

_NS = re.compile(r'(?:namespace|applicationId)\s*[=(]?\s*["\']([\w.]+)["\']')


def gather_repo_texts(repo_root: str) -> list[str]:
    """Assemble profile chunks from README(s) + gradle namespace/applicationId + module identifiers."""
    chunks: list[str] = []
    for base, _dirs, files in os.walk(repo_root):
        rel = os.path.relpath(base, repo_root)
        if any(p in rel.split(os.sep) for p in (".git", "build", "node_modules")):
            continue
        seg = rel.replace(os.sep, " ").replace("-", " ").replace("_", " ")
        if seg.strip() and seg != ".":
            chunks.append(seg.strip())                       # module/package path identifiers
        for fn in files:
            low = fn.lower()
            if low.startswith("readme"):
                try:
                    chunks.append(open(os.path.join(base, fn), encoding="utf-8",
                                       errors="ignore").read()[:4000])
                except OSError:
                    pass
            elif low.startswith("build.gradle") or low == "androidmanifest.xml":
                try:
                    txt = open(os.path.join(base, fn), encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                chunks += _NS.findall(txt)
    seen: dict[str, None] = {}
    for c in chunks:
        c = c.strip()
        if c:
            seen.setdefault(c, None)
    return list(seen)


def build_text_profiles(profiles: dict[str, list[str]], dest_db: str, embedder) -> str:
    """Embed each repo's text chunks and write a small profile atlas.db keyed by repo."""
    store = Store(dest_db)
    for repo, chunks in profiles.items():
        chunks = [c for c in chunks if c and c.strip()] or [repo]     # never leave a repo empty
        vecs = embedder.embed(chunks)
        units = [Unit(repo=repo, kind="profile", name=f"{repo}#{i}", qualified_name=None,
                      file=None, repo_head="profile", text=chunk, meta={})
                 for i, chunk in enumerate(chunks)]
        store.reindex_repo(repo, list(zip(units, vecs)), repo_head="profile")
    return dest_db
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_text_profile.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/index/text_profile.py tests/index/test_text_profile.py
git commit -m "feat(index): lightweight bge-m3 repo-text profile builder (README+manifest+ids)"
```

### Task 2.3: `FunctionalTextIndex` — text-cosine ranking

**Files:**
- Create: `groundloop/adapters/index/functional_text.py`
- Test: `tests/index/test_functional_text.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/index/test_functional_text.py`:

```python
from groundloop.adapters.index.functional_text import FunctionalTextIndex
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.core.types import RepoRef
from groundloop.domains.android_ivi.functional_signals import FunctionalTextExtractor
from groundloop.core.types import Ticket
from groundloop.engines.atlas.embed import StubEmbedder

CATALOG = [RepoRef("oboe"), RepoRef("newpipe")]


def _profile_db(tmp_path):
    return build_text_profiles(
        {"oboe": ["audio playback streaming low latency"], "newpipe": ["video player youtube feed"]},
        str(tmp_path / "profiles.db"), StubEmbedder(dim=16))


def test_functional_index_ranks_by_prose_similarity(tmp_path):
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16))
    sig = FunctionalTextExtractor().extract((), Ticket("t", "audio playback", "no sound streaming"))
    ranked = idx.rank_repos(sig, CATALOG)
    assert ranked[0].repo.name == "oboe" and ranked[0].score > 0


def test_functional_index_empty_query_all_zero(tmp_path):
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16))
    sig = FunctionalTextExtractor().extract((), Ticket("t", "", ""))
    ranked = idx.rank_repos(sig, CATALOG)
    assert all(r.score == 0.0 for r in ranked)


def test_retrieve_returns_list(tmp_path):
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16))
    assert isinstance(idx.retrieve(RepoRef("oboe"), "audio"), list)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_functional_text.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/adapters/index/functional_text.py` (text-cosine only; the log channel is Task 3.1):

```python
"""FunctionalTextIndex: rank repos by bge-m3 cosine between the ticket prose query and each repo's
text profile (max cosine per repo). A CodeIndex (rank_repos + retrieve) swapped at the composition
root. The optional log-FTS RRF channel is added in Phase 3. rank_repos in atlas.py is untouched."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import prose_query
from groundloop.engines.atlas.store import Store


class FunctionalTextIndex:
    def __init__(self, profile_db: str, embedder, atlas_db: str | None = None):
        self.profile = Store(profile_db)
        self.embedder = embedder
        self.atlas_db = atlas_db          # optional log-FTS channel (Phase 3)

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        best: dict[str, float] = {name: 0.0 for name in allowed}
        q = prose_query(signals)
        if q.strip():
            qvec = self.embedder.embed([q])[0]
            for unit, cos in self.profile.vector_search(qvec, k=50, repos=list(allowed)):
                if unit.repo in best:
                    best[unit.repo] = max(best[unit.repo], cos)
        ranked = [RepoScore(RepoRef(name), float(score)) for name, score in best.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        qvec = self.embedder.embed([query])[0]
        files: list[str] = []
        for unit, _ in self.profile.vector_search(qvec, k=20, repos=[repo.name]):
            if unit.file and unit.file not in files:
                files.append(unit.file)
        return files
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_functional_text.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/index/functional_text.py tests/index/test_functional_text.py
git commit -m "feat(index): FunctionalTextIndex — bge-m3 max-cosine over repo-text profiles"
```

### Task 2.4: `gloop build-textprofile` CLI

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_run_build_textprofile` + subparser + dispatch)
- Test: `tests/index/test_cli_build_textprofile.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/index/test_cli_build_textprofile.py`:

```python
import json
from pathlib import Path


def test_cli_build_textprofile_hermetic(tmp_path, monkeypatch, capsys):
    from groundloop.cli import main
    # a 2-repo corpus dir with README + a catalog
    for repo, body in {"oboe": "audio playback", "newpipe": "video player"}.items():
        (tmp_path / "corpus" / repo).mkdir(parents=True)
        (tmp_path / "corpus" / repo / "README.md").write_text(body)
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([{"name": "oboe"}, {"name": "newpipe"}]))
    # force the hermetic StubEmbedder (no gateway)
    monkeypatch.setenv("KLOOP_TEXTPROFILE_STUB", "1")
    out = tmp_path / "profiles.db"
    rc = main(["build-textprofile", "--corpus", str(tmp_path / "corpus"),
               "--catalog", str(cat), "--out", str(out)])
    assert rc == 0 and out.exists()
    assert "profiles: 2 repos" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_cli_build_textprofile.py -q`
Expected: FAIL — unknown command.

- [ ] **Step 3: Implement** — add to `groundloop/cli/__init__.py`:

```python
def _run_build_textprofile(args) -> int:
    import json
    import os
    from pathlib import Path
    from groundloop.adapters.index.text_profile import build_text_profiles, gather_repo_texts
    names = [c["name"] for c in json.loads(Path(args.catalog).read_text())]
    profiles = {n: gather_repo_texts(os.path.join(args.corpus, n))
                for n in names if os.path.isdir(os.path.join(args.corpus, n))}
    if os.environ.get("KLOOP_TEXTPROFILE_STUB") == "1":
        from groundloop.engines.atlas.embed import StubEmbedder
        emb = StubEmbedder()
    else:
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        emb = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
    build_text_profiles(profiles, args.out, emb)
    print(f"profiles: {len(profiles)} repos -> {args.out}")
    return 0
```

Subparser (near `build-atlas`):

```python
    bp = sub.add_parser("build-textprofile", help="build the lightweight bge-m3 repo-text profile db")
    bp.add_argument("--corpus", required=True, help="dir with one subdir per repo (README/manifest/ids)")
    bp.add_argument("--catalog", required=True, help="catalog.json listing repo names to profile")
    bp.add_argument("--out", required=True, help="destination profile atlas.db path")
```

Dispatch (in `main`):

```python
    if args.cmd == "build-textprofile":
        return _run_build_textprofile(args)
```

- [ ] **Step 4: Run to verify it passes + lint**

Run: `.venv/bin/python -m pytest tests/index/test_cli_build_textprofile.py -q && .venv/bin/ruff check groundloop tests`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/index/test_cli_build_textprofile.py
git commit -m "feat(cli): gloop build-textprofile (repo-text profile db; stub or gateway embedder)"
```

---

## Phase 3 — Optional-log RRF fusion + abstention calibration

### Task 3.1: Optional log-FTS channel in `FunctionalTextIndex`

**Files:**
- Modify: `groundloop/adapters/index/functional_text.py`
- Test: `tests/index/test_functional_text.py`

- [ ] **Step 1: Write the failing test** — append to `tests/index/test_functional_text.py`:

```python
def test_log_channel_injects_repo_missed_by_prose(tmp_path):
    from tests.fixtures.atlas_fixture import build_atlas_fixture
    from groundloop.core.types import Signals
    from groundloop.domains.android_ivi.functional_signals import PROSE_MARK
    prof = build_text_profiles({"organicmaps": ["maps navigation"], "android-gpuimage-plus": ["image filter"]},
                               str(tmp_path / "profiles.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "atlas.db"))       # has org.wysaid... for gpuimage
    idx = FunctionalTextIndex(prof, StubEmbedder(dim=16), atlas_db=atlas)
    cat = [RepoRef("organicmaps"), RepoRef("android-gpuimage-plus")]
    # prose about maps (favors organicmaps) BUT a log token pointing at gpuimage's CGE symbol
    sig = Signals(symbols=(PROSE_MARK + "screen goes black on map view",),
                  classes=("org.wysaid.nativePort.CGEImageHandler",))
    ranked = idx.rank_repos(sig, cat)
    names = [r.repo.name for r in ranked if r.score > 0]
    assert "android-gpuimage-plus" in names           # union: log FTS injected the CGE owner
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_functional_text.py -k log_channel -q`
Expected: FAIL — no log channel yet (gpuimage stays 0).

- [ ] **Step 3: Implement** — update `functional_text.py`: add imports and the fusion in `rank_repos`:

```python
from dataclasses import replace

from groundloop.adapters.index.atlas import AtlasIndex
```

Add a module constant after the imports:

```python
_LOG_WEIGHT = 0.15     # optional log evidence is supporting, not primary (calibration seed)
```

Update `__init__` to cache the log-channel index once (so it isn't rebuilt per case), then replace `rank_repos` with the fused version:

```python
    def __init__(self, profile_db: str, embedder, atlas_db: str | None = None):
        self.profile = Store(profile_db)
        self.embedder = embedder
        self._atlas = AtlasIndex(atlas_db) if atlas_db else None   # optional log-FTS channel

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        best: dict[str, float] = {name: 0.0 for name in allowed}
        q = prose_query(signals)
        if q.strip():
            qvec = self.embedder.embed([q])[0]
            for unit, cos in self.profile.vector_search(qvec, k=50, repos=list(allowed)):
                if unit.repo in best:
                    best[unit.repo] = max(best[unit.repo], cos)

        # optional log-FTS channel: rank-decayed bonus, UNIONs a prose-missed owner in
        log_signals = replace(signals, symbols=())          # drop the reserved prose slot
        if self._atlas is not None and log_signals.tokens():
            fts = self._atlas.rank_repos(log_signals, catalog)
            for i, x in enumerate(r for r in fts if r.score > 0):
                if x.repo.name in best:
                    best[x.repo.name] += _LOG_WEIGHT / (1 + i)

        ranked = [RepoScore(RepoRef(name), float(score)) for name, score in best.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked
```

(This replaces the Task 2.3 `__init__`, which stored `self.atlas_db`; `retrieve` still uses `self.profile`.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_functional_text.py -q`
Expected: PASS (all prior text-cosine tests still pass — `atlas_db=None` path unchanged).

- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/index/functional_text.py tests/index/test_functional_text.py
git commit -m "feat(index): FunctionalTextIndex optional log-FTS channel (rank-decayed bonus + union)"
```

### Task 3.2: Abstention threshold constant for the functional score scale

**Files:**
- Create: `groundloop/funceval/__init__.py` (empty package marker)
- Create: `groundloop/funceval/arms.py` (`TAU_FUNC` + placeholder builder filled in Task 4.2)
- Test: `tests/funceval/test_abstain_scale.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/funceval/test_abstain_scale.py`:

```python
from groundloop.core.types import RepoRef, RepoScore
from groundloop.eval.abstain import decide
from groundloop.funceval.arms import TAU_FUNC


def test_tau_func_abstains_on_flat_and_answers_on_clear():
    tm, ts = TAU_FUNC
    flat = [RepoScore(RepoRef("a"), 0.30), RepoScore(RepoRef("b"), 0.29)]     # tiny margin -> abstain
    clear = [RepoScore(RepoRef("a"), 0.40), RepoScore(RepoRef("b"), 0.10)]    # wide margin -> answer
    assert decide(flat, tau_margin=tm, tau_score=ts).predicted is None
    assert decide(clear, tau_margin=tm, tau_score=ts).predicted == "a"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/funceval/test_abstain_scale.py -q`
Expected: FAIL — `groundloop.funceval` missing.

- [ ] **Step 3: Implement** — create `groundloop/funceval/__init__.py` (empty), and `groundloop/funceval/arms.py`:

```python
"""Arm construction for the functional-bug eval. Calibration seeds live here; freeze on a calib
split after the first proxy run (spec §6). Full builder is filled in Task 4.2."""
from __future__ import annotations

# functional score scale = cosine (0..1) + rank-decayed log bonus; margin gate must be reachable.
TAU_FUNC = (0.05, 0.0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/funceval/test_abstain_scale.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/funceval/__init__.py groundloop/funceval/arms.py tests/funceval/test_abstain_scale.py
git commit -m "feat(funceval): TAU_FUNC abstain-threshold seed for the functional score scale"
```

---

## Phase 4 — `gloop funceval` (functional + dispatch + ablation arms)

### Task 4.1: `DispatchExtractor` + `DispatchIndex` (crash-anchor → fault; prose-only → functional)

**Files:**
- Modify: `groundloop/domains/android_ivi/functional_signals.py` (DispatchExtractor)
- Modify: `groundloop/adapters/index/functional_text.py` (DispatchIndex)
- Test: `tests/index/test_dispatch.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/index/test_dispatch.py`:

```python
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.adapters.index.functional_text import DispatchIndex, FunctionalTextIndex
from groundloop.adapters.index.fault_routing import FaultRoutingIndex
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.core.types import LogAttachment, RepoRef, Ticket
from groundloop.domains.android_ivi.functional_signals import DispatchExtractor, PROSE_MARK
from groundloop.engines.atlas.embed import StubEmbedder

CAT = [RepoRef("organicmaps"), RepoRef("android-gpuimage-plus")]
_CRASH = ("E AndroidRuntime: FATAL EXCEPTION: main\n"
          "\tat app.organicmaps.Framework.nativeThrow(Framework.java:10)")


def _dispatch(tmp_path):
    prof = build_text_profiles({"organicmaps": ["maps navigation offline"],
                                "android-gpuimage-plus": ["image gpu filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    return DispatchIndex(FaultRoutingIndex(atlas), FunctionalTextIndex(prof, StubEmbedder(dim=16), atlas))


def test_dispatch_extractor_routes_crash_vs_prose():
    crash = DispatchExtractor().extract((LogAttachment("l", "logcat", _CRASH),),
                                        Ticket("t", "crash", "boom"))
    prose = DispatchExtractor().extract((), Ticket("t", "wrong label on settings", "UI text bug"))
    assert not (crash.symbols and crash.symbols[0].startswith(PROSE_MARK))   # crash -> fault signals
    assert prose.symbols and prose.symbols[0].startswith(PROSE_MARK)         # no anchor -> prose


def test_dispatch_index_sends_crash_to_fault_and_prose_to_functional(tmp_path):
    idx = _dispatch(tmp_path)
    ex = DispatchExtractor()
    crash_sig = ex.extract((LogAttachment("l", "logcat", _CRASH),), Ticket("t", "x", "y"))
    prose_sig = ex.extract((), Ticket("t", "offline maps navigation broken", "no route"))
    assert idx.rank_repos(crash_sig, CAT)[0].repo.name == "organicmaps"      # fault routing wins
    assert idx.rank_repos(prose_sig, CAT)[0].repo.name == "organicmaps"      # text sim wins
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/index/test_dispatch.py -q`
Expected: FAIL — `DispatchExtractor` / `DispatchIndex` missing.

- [ ] **Step 3: Implement DispatchExtractor** — append to `groundloop/domains/android_ivi/functional_signals.py`:

```python
from groundloop.domains.android_ivi.fault_signals import fault_record_for_logs, signals_from_fault


class DispatchExtractor:
    """Route discriminator carried in Signals: a crash ANCHOR -> fault Signals (no prose mark);
    no anchor -> prose Signals (symbols[0] starts with PROSE_MARK). Lets a Signals-only index route."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        fr = fault_record_for_logs(logs)
        if fr is not None:
            return signals_from_fault(fr)
        return pack_prose(ticket, logs)
```

- [ ] **Step 4: Implement DispatchIndex** — in `groundloop/adapters/index/functional_text.py`, update the existing `functional_signals` import line to also bring in `PROSE_MARK` (it currently imports only `prose_query`):

```python
from groundloop.domains.android_ivi.functional_signals import PROSE_MARK, prose_query
```

Then append:

```python
class DispatchIndex:
    """Per-case composite: prose-marked Signals -> functional index; else -> fault index. The
    Signals-only discriminator (symbols[0] PROSE_MARK) mirrors DispatchExtractor's routing."""

    def __init__(self, fault_index, functional_index):
        self.fault = fault_index
        self.functional = functional_index

    def _is_functional(self, signals: Signals) -> bool:
        return bool(signals.symbols) and signals.symbols[0].startswith(PROSE_MARK)

    def rank_repos(self, signals: Signals, catalog):
        idx = self.functional if self._is_functional(signals) else self.fault
        return idx.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self.functional.retrieve(repo, query)
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/index/test_dispatch.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add groundloop/domains/android_ivi/functional_signals.py groundloop/adapters/index/functional_text.py tests/index/test_dispatch.py
git commit -m "feat(dispatch): DispatchExtractor+DispatchIndex (crash-anchor->fault, prose->functional)"
```

### Task 4.2: `build_functional_arms` (functional + dispatch + ablations)

**Files:**
- Modify: `groundloop/funceval/arms.py`
- Test: `tests/funceval/test_arms.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/funceval/test_arms.py`:

```python
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.funceval.arms import build_functional_arms


def test_build_functional_arms_names_and_taus(tmp_path):
    prof = build_text_profiles({"organicmaps": ["maps"]}, str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    arms = {a.name: a for a in build_functional_arms(prof, atlas, embedder=StubEmbedder(dim=16))}
    assert {"functional", "dispatch", "flood", "faultslice", "routing"} <= set(arms)
    from groundloop.funceval.arms import TAU_FUNC
    assert (arms["functional"].tau_margin, arms["functional"].tau_score) == TAU_FUNC
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/funceval/test_arms.py -q`
Expected: FAIL — `build_functional_arms` missing.

- [ ] **Step 3: Implement** — replace `groundloop/funceval/arms.py` body (keep `TAU_FUNC`):

```python
"""Arm construction for the functional-bug eval. Calibration seeds live here; freeze on a calib
split after the first proxy run (spec §6)."""
from __future__ import annotations

from groundloop.adapters.index.fault_routing import FaultRoutingIndex
from groundloop.adapters.index.functional_text import DispatchIndex, FunctionalTextIndex
from groundloop.domains.android_ivi.functional_signals import DispatchExtractor, FunctionalTextExtractor
from groundloop.eval.arms import Arm
from groundloop.faulteval.arms import build_fault_arms

TAU_FUNC = (0.05, 0.0)


def build_functional_arms(profile_db: str, index_db: str, *, embedder,
                          names=("functional", "dispatch", "flood", "faultslice", "routing")) -> list[Arm]:
    ftext = FunctionalTextIndex(profile_db, embedder, atlas_db=index_db)
    made: list[Arm] = []
    for name in names:
        if name == "functional":
            made.append(Arm("functional", ftext, FunctionalTextExtractor(), *TAU_FUNC))
        elif name == "dispatch":
            disp = DispatchIndex(FaultRoutingIndex(index_db), ftext)
            made.append(Arm("dispatch", disp, DispatchExtractor(), *TAU_FUNC))
        elif name in ("flood", "faultslice", "routing"):
            made += build_fault_arms(index_db, names=(name,))       # reuse v2 ablation arms
    return made
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/funceval/test_arms.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/funceval/arms.py tests/funceval/test_arms.py
git commit -m "feat(funceval): build_functional_arms (functional+dispatch+flood/faultslice/routing)"
```

### Task 4.3: `run_funceval` runner (reuse EvalRunner + grade_all by_bug_kind)

**Files:**
- Create: `groundloop/funceval/runner.py`
- Test: `tests/funceval/test_runner.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/funceval/test_runner.py`:

```python
import json
from pathlib import Path

from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.funceval.runner import run_funceval


def _func_case(root, cid, owner, summary, files):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": summary, "description": summary}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True, "bug_kind": "functional"}))


def test_run_funceval_reports_by_bug_kind(tmp_path):
    ds = tmp_path / "ds"
    _func_case(ds, "f1", "organicmaps", "offline maps navigation route missing", ["x.java"])
    (ds / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "android-gpuimage-plus"}]))
    prof = build_text_profiles({"organicmaps": ["offline maps navigation route"],
                                "android-gpuimage-plus": ["gpu image filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    card = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                        arms=("functional", "dispatch"))
    assert {"functional", "dispatch"} <= set(card["attribution"]["arms"])
    bbk = card["attribution"]["arms"]["functional"]["by_bug_kind"]
    assert bbk["functional"]["forced"]["recall@1"]["value"] == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/funceval/test_runner.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/funceval/runner.py` (mirrors `faulteval/runner.py`):

```python
"""Functional-bug matching eval: reuse the Stage-1 EvalRunner + grade_all (with by_bug_kind) over a
labeled dataset. Offline oracle reads happen ONLY in grade_all — never in the runner arms."""
from __future__ import annotations

from pathlib import Path

from groundloop.adapters.estate import MockEstate
from groundloop.adapters.mock.jira import MockJira
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.runner import EvalRunner
from groundloop.eval.scorecard import grade_all
from groundloop.funceval.arms import TAU_FUNC, build_functional_arms


def run_funceval(dataset: str, profile_db: str, index_db: str, *, embedder,
                 arms=("functional", "dispatch", "flood", "faultslice", "routing")) -> dict:
    cases = load_cases(dataset)
    catalog_path = str(Path(dataset) / "catalog.json")
    issues = MockJira(dataset)
    estate = MockEstate(catalog_path, dataset + "/_work")
    runner = EvalRunner(issues=issues, estate=estate, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1])
    records = runner.run(cases, build_functional_arms(profile_db, index_db, embedder=embedder, names=arms))
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    return {"attribution": grade_all(records, oracle_by_case=oracle_by_case)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/funceval/test_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/funceval/runner.py tests/funceval/test_runner.py
git commit -m "feat(funceval): run_funceval (EvalRunner + grade_all by_bug_kind over labeled dataset)"
```

### Task 4.4: `gloop funceval` CLI

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_run_funceval` + subparser + dispatch)
- Test: `tests/funceval/test_cli_funceval.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/funceval/test_cli_funceval.py`:

```python
import json
from pathlib import Path

from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.engines.atlas.embed import StubEmbedder


def test_cli_funceval(tmp_path, monkeypatch, capsys):
    from groundloop.cli import main
    ds = tmp_path / "ds"
    d = ds / "f1"
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": "f1", "summary": "offline maps route", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "organicmaps", "is_answerable": True, "bug_kind": "functional"}))
    (ds / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "android-gpuimage-plus"}]))
    prof = build_text_profiles({"organicmaps": ["offline maps route navigation"],
                                "android-gpuimage-plus": ["image filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    monkeypatch.setenv("KLOOP_TEXTPROFILE_STUB", "1")     # force StubEmbedder in the CLI
    rc = main(["funceval", "--dataset", str(ds), "--profile-db", prof, "--index-db", atlas,
               "--arms", "functional,dispatch", "--out", str(tmp_path / "card.json")])
    assert rc == 0 and (tmp_path / "card.json").exists()
    assert "functional" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/funceval/test_cli_funceval.py -q`
Expected: FAIL — unknown command.

- [ ] **Step 3: Implement** — add to `groundloop/cli/__init__.py`:

```python
def _run_funceval(args) -> int:
    import json
    import os
    from pathlib import Path
    from groundloop.funceval.runner import run_funceval
    if os.environ.get("KLOOP_TEXTPROFILE_STUB") == "1":
        from groundloop.engines.atlas.embed import StubEmbedder
        emb = StubEmbedder()
    else:
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        emb = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
    card = run_funceval(args.dataset, args.profile_db, args.index_db, embedder=emb,
                        arms=tuple(args.arms.split(",")))
    Path(args.out).write_text(json.dumps(card, indent=2))
    for arm, a in card["attribution"]["arms"].items():
        line = f"{arm}: recall@1={a['forced']['recall@1']['value']:.2f} coverage={a['selective']['coverage']:.2f}"
        for bk, sub in a.get("by_bug_kind", {}).items():
            line += f" | {bk} recall@1={sub['forced']['recall@1']['value']:.2f}"
        print(line)
    return 0
```

Subparser (near `faulteval`):

```python
    fn = sub.add_parser("funceval", help="functional-bug matching eval (text-primary + optional logs)")
    fn.add_argument("--dataset", required=True, help="labeled dataset root (bug_kind in oracle.json)")
    fn.add_argument("--profile-db", required=True, help="repo-text profile db (gloop build-textprofile)")
    fn.add_argument("--index-db", required=True, help="atlas.db for the optional log-FTS channel + ablations")
    fn.add_argument("--arms", default="functional,dispatch,flood,faultslice,routing",
                    help="comma list of arms")
    fn.add_argument("--out", required=True, help="scorecard.json output path")
```

Dispatch (in `main`):

```python
    if args.cmd == "funceval":
        return _run_funceval(args)
```

- [ ] **Step 4: Run to verify it passes + lint**

Run: `.venv/bin/python -m pytest tests/funceval/ -q && .venv/bin/ruff check groundloop tests`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/funceval/test_cli_funceval.py
git commit -m "feat(cli): gloop funceval (functional-bug matching eval, per-bug_kind scorecard)"
```

---

## Phase 5 — `gloop synth --mode functional` + functional negatives

### Task 5.1: Functional synth (UI-text + CarPlay prose cases, no fault frame)

**Files:**
- Create: `groundloop/synth/functional.py`
- Test: `tests/synth/test_functional.py` (create)

- [ ] **Step 1: Write the failing test** — create `tests/synth/test_functional.py`:

```python
import json
from pathlib import Path

from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.functional import build_functional_case


def _src(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "orig", "description": "orig"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_functional_case_is_prose_only_no_fault_frame(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    src = _src(tmp_path, "U1", "android-gpuimage-plus",
               ["library/src/main/java/org/wysaid/view/ImageGLSurfaceView.java"])
    out = tmp_path / "ds"
    cid = build_functional_case(src, Store(db), str(out), klass="ui_text")
    assert cid == "U1"
    oracle = json.loads((out / "U1" / "_oracle" / "oracle.json").read_text())
    ticket = json.loads((out / "U1" / "ticket.json").read_text())
    assert oracle["bug_kind"] == "functional" and "fault_frame" not in oracle
    assert ticket["logs"] == []                          # UI-text: no logs at all
    assert oracle["owning_repo"] == "android-gpuimage-plus"


def test_carplay_case_has_optional_connection_log(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    src = _src(tmp_path, "C1", "organicmaps",
               ["android/app/src/main/java/app/organicmaps/car/CarAppSession.java"])
    out = tmp_path / "ds"
    build_functional_case(src, Store(db), str(out), klass="carplay")
    ticket = json.loads((out / "C1" / "ticket.json").read_text())
    log = (out / "C1" / ticket["logs"][0]["path"]).read_text() if ticket["logs"] else ""
    assert "connection" in log.lower() or "projection" in log.lower()      # non-crash connection log
    assert "FATAL EXCEPTION" not in log                                    # NOT a crash
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/synth/test_functional.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** — create `groundloop/synth/functional.py`:

```python
"""Functional (no-crash) synth: turn a mined positive into a prose-only ticket (UI-text) or a
prose + non-crash-log ticket (audio/CarPlay). Names the owner's real class/method from the atlas so
the case is groundable WITHOUT a crash frame; NO fault_frame is written. bug_kind='functional'.
A separate track (dataset_kind='functional_unscrubbed'). Deterministic per case id."""
from __future__ import annotations

import glob
import json
import os

from groundloop.synth.logs import _rng, crash_frames


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


_TEMPLATES = {
    "ui_text": ("Wrong label shown in {cls} screen",
                "The UI text under {cls}.{method} is incorrect / not localized. No crash occurs; "
                "the wrong string is simply displayed."),
    "audio": ("Audio stutters / drops when using {cls}",
              "Playback via {cls}.{method} underruns intermittently. No crash — audio just glitches."),
    "carplay": ("Projection connection drops in {cls}",
                "The CarPlay/Android-Auto session handled by {cls}.{method} fails to connect / "
                "disconnects. No crash is logged; the screen just goes blank."),
}
_AUDIO_LOG = "W AAudio  : liboboe.so onAudioReady buffer underrun (count=37)\n"
_CARPLAY_LOG = ("I CarConnection: projection connection state=CONNECTING\n"
                "W CarConnection: connection timeout after 5000ms; session not established\n")


def build_functional_case(src_case_dir: str, store, dest_root: str, *, klass: str = "ui_text") -> str | None:
    cid = os.path.basename(src_case_dir.rstrip("/"))
    with open(os.path.join(src_case_dir, "_oracle", "oracle.json"), encoding="utf-8") as fh:
        oracle = json.load(fh)
    owner, files = oracle.get("owning_repo"), oracle.get("expected_files") or []
    if not owner or not files:
        return None
    rng = _rng(cid)
    frames = crash_frames(store, owner, files, rng)
    if not frames:
        return None
    top = frames[0]
    fq = f"{top.package}.{top.cls}" if top.package else top.cls
    summary_t, desc_t = _TEMPLATES.get(klass, _TEMPLATES["ui_text"])
    summary = summary_t.format(cls=fq, method=top.method)
    description = desc_t.format(cls=fq, method=top.method)

    dest = os.path.join(dest_root, cid)
    logs_field: list[dict] = []
    if klass in ("audio", "carplay"):
        os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
        text = _AUDIO_LOG if klass == "audio" else _CARPLAY_LOG
        with open(os.path.join(dest, "logs", "000.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        logs_field = [{"path": "logs/000.txt", "kind": "logcat"}]

    with open(os.path.join(src_case_dir, "ticket.json"), encoding="utf-8") as fh:
        ticket = json.load(fh)
    ticket.update({"summary": summary, "description": description, "component": "", "logs": logs_field})
    _dump(os.path.join(dest, "ticket.json"), ticket)
    new_oracle = {**oracle, "bug_kind": "functional", "functional_class": klass}
    new_oracle.pop("fault_frame", None)
    new_oracle.pop("synth_log", None)
    _dump(os.path.join(dest, "_oracle", "oracle.json"), new_oracle)
    return cid


def build_functional_dataset(src_root: str, atlas_db: str, dest_root: str, catalog_names: list[str]) -> list[str]:
    from groundloop.engines.atlas.store import Store
    store = Store(atlas_db)
    classes = ("ui_text", "audio", "carplay")
    made: list[str] = []
    for i, d in enumerate(sorted(glob.glob(os.path.join(src_root, "*")))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "ticket.json")):
            cid = build_functional_case(d, store, dest_root, klass=classes[i % len(classes)])
            if cid:
                made.append(cid)
    _dump(os.path.join(dest_root, "catalog.json"), [{"name": n} for n in catalog_names])
    _dump(os.path.join(dest_root, "dataset_meta.json"),
          {"dataset_kind": "functional_unscrubbed"})
    return made
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/synth/test_functional.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/synth/functional.py tests/synth/test_functional.py
git commit -m "feat(synth): functional (no-crash) synth — UI-text/audio/CarPlay, bug_kind=functional"
```

### Task 5.2: Functional honest-refusal negatives

**Files:**
- Modify: `groundloop/synth/functional.py` (add `build_functional_negatives`)
- Test: `tests/synth/test_functional.py`

- [ ] **Step 1: Write the failing test** — append to `tests/synth/test_functional.py`:

```python
def test_functional_negatives_are_unanswerable(tmp_path):
    from groundloop.synth.functional import build_functional_negatives
    out = tmp_path / "neg"
    ids = build_functional_negatives(str(out), n=2)
    assert len(ids) == 2
    for cid in ids:
        oracle = json.loads((out / cid / "_oracle" / "oracle.json").read_text())
        ticket = json.loads((out / cid / "ticket.json").read_text())
        assert oracle["is_answerable"] is False and oracle["bug_kind"] == "functional"
        assert oracle["negative_class"] == "not_a_defect"
        assert oracle["owning_repo"] == "__NOT_A_DEFECT__" and ticket["logs"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/synth/test_functional.py -k negatives -q`
Expected: FAIL — function missing.

- [ ] **Step 3: Implement** — append to `groundloop/synth/functional.py`:

```python
_NEG_PROMPTS = [
    ("How do I change the app theme to dark mode?", "This is a usage question, not a defect."),
    ("Please add a feature to export playlists to CSV", "Feature request, not a defect."),
    ("Documentation for the settings screen is unclear", "Docs improvement, not a code defect."),
]


def build_functional_negatives(dest_root: str, *, n: int = 3) -> list[str]:
    """Mint functional honest-refusal negatives (not_a_defect): answerable=False, prose-only. Follows
    the four-class contract (owning_repo='__NOT_A_DEFECT__', expected_files=[]). Never leaks an owner."""
    made: list[str] = []
    for i in range(n):
        summary, desc = _NEG_PROMPTS[i % len(_NEG_PROMPTS)]
        cid = f"func-neg-{i}"
        dest = os.path.join(dest_root, cid)
        _dump(os.path.join(dest, "ticket.json"),
              {"id": cid, "summary": summary, "description": desc, "component": "", "logs": []})
        _dump(os.path.join(dest, "_oracle", "oracle.json"),
              {"owning_repo": "__NOT_A_DEFECT__", "expected_files": [], "is_answerable": False,
               "negative_class": "not_a_defect", "bug_kind": "functional"})
        made.append(cid)
    return made
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/synth/test_functional.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add groundloop/synth/functional.py tests/synth/test_functional.py
git commit -m "feat(synth): functional honest-refusal negatives (not_a_defect, bug_kind=functional)"
```

### Task 5.3: Wire `--mode functional` into `gloop synth`

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_run_synth` + `--mode` choices)
- Test: `tests/synth/test_cli_synth.py`

- [ ] **Step 1: Write the failing test** — append to `tests/synth/test_cli_synth.py`:

```python
def test_cli_synth_functional_mode(tmp_path):
    import json
    from pathlib import Path
    from groundloop.cli import main
    from tests.fixtures.atlas_fixture import build_atlas_fixture
    src = tmp_path / "src" / "U1"
    (src / "_oracle").mkdir(parents=True)
    (src / "ticket.json").write_text(json.dumps({"id": "U1", "summary": "s", "description": "d"}))
    (src / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "android-gpuimage-plus",
         "expected_files": ["library/src/main/java/org/wysaid/view/ImageGLSurfaceView.java"]}))
    (tmp_path / "src" / "catalog.json").write_text(json.dumps([{"name": "android-gpuimage-plus"}]))
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    out = tmp_path / "ds"
    rc = main(["synth", "--mode", "functional", "--src", str(tmp_path / "src"),
               "--atlas-db", db, "--out", str(out)])
    assert rc == 0
    oracle = json.loads((out / "U1" / "_oracle" / "oracle.json").read_text())
    assert oracle["bug_kind"] == "functional"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/synth/test_cli_synth.py -k functional -q`
Expected: FAIL — `functional` not a valid `--mode`.

- [ ] **Step 3: Implement** — in `groundloop/cli/__init__.py`: add `"functional"` to the `--mode` choices:

```python
    sy.add_argument("--mode", choices=["failurelog", "faultlog", "functional"], default="failurelog",
                    help="failurelog | faultlog | functional (no-crash prose + optional log)")
```

In `_run_synth`, add the branch (before the `failurelog` fallthrough, after the `faultlog` block):

```python
    if getattr(args, "mode", "failurelog") == "functional":
        from groundloop.synth.functional import build_functional_dataset
        made = build_functional_dataset(args.src, atlas_db, args.out, catalog_names)
        kinds: dict[str, int] = {}
        for cid in made:
            o = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
            k = o.get("functional_class", "?")
            kinds[k] = kinds.get(k, 0) + 1
        print(f"functional synth: {len(made)} cases -> {args.out}")
        for k in sorted(kinds):
            print(f"  {k}: {kinds[k]}")
        return 0
```

- [ ] **Step 4: Run to verify it passes + lint**

Run: `.venv/bin/python -m pytest tests/synth/ -q && .venv/bin/ruff check groundloop tests`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/synth/test_cli_synth.py
git commit -m "feat(cli): gloop synth --mode functional (no-crash UI-text/audio/CarPlay cases)"
```

### Task 5.4: Anti-leak red-tests for the new modules

**Files:**
- Test: `tests/index/test_functional_antileak.py` (create)

- [ ] **Step 1: Write the test** — create `tests/index/test_functional_antileak.py`:

```python
import inspect

from groundloop.adapters.index import functional_text, text_profile
from groundloop.domains.android_ivi import functional_signals


def test_functional_modules_read_no_oracle():
    for mod in (functional_text, text_profile, functional_signals):
        src = inspect.getsource(mod)
        for banned in ("_oracle", "oracle.json", "load_eval_oracle", "owning_repo", "expected_files"):
            assert banned not in src, f"{mod.__name__} must not reference {banned}"
```

- [ ] **Step 2: Run to verify it passes** (these modules genuinely never read the oracle)

Run: `.venv/bin/python -m pytest tests/index/test_functional_antileak.py -q`
Expected: PASS. If it fails, the implementation leaked an oracle reference — fix the module, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/index/test_functional_antileak.py
git commit -m "test(functional): anti-leak red-test — functional arm reads no oracle"
```

---

## Phase 6 — Proxy A/B + findings (orchestrator runbook, not TDD)

> This phase is executed by the orchestrator after all code tasks are green + merged. It builds the modest proxy slice, runs the A/B, and writes findings. It is **not** a hermetic test task; it uses the live env. Prefix every live command with `set -a; . ./.env; set +a` and run off ext4 (`/home/vinc` directly, not `/home/vinc/code`).

- [ ] **Step 1: Full suite + lint green**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: all pass, ruff clean, and the frozen/gated surfaces show zero diff:
`git diff --name-only origin/master | grep -E 'groundloop/core/|engines/atlas/store.py|adapters/index/atlas.py|owner_tokens.py|repo_routing.py|mine/'` → empty.

- [ ] **Step 2: Build the modest functional proxy slice** (off ext4, e.g. `/home/vinc/gl-eval`)

```bash
set -a; . ./.env; set +a
DS=/home/vinc/gl-eval/functional-clean
# functional cases from the mined positives (UI-text/audio/CarPlay), + label crash+functional
.venv/bin/gloop synth --mode functional --src /home/vinc/gl-eval/dataset-neg-synth-sub \
  --atlas-db /home/vinc/gl-eval/atlas-9.db --out $DS
.venv/bin/gloop label-bugkind --dataset $DS
# build the lightweight repo-text profile db over the local corpora
.venv/bin/gloop build-textprofile --corpus /mnt/x/code/corpora-local \
  --catalog $DS/catalog.json --out /home/vinc/gl-eval/textprofiles-9.db
```

- [ ] **Step 3: Run the A/B** (functional + dispatch vs flood/faultslice/routing, per bug_kind)

```bash
set -a; . ./.env; set +a
.venv/bin/gloop funceval --dataset /home/vinc/gl-eval/functional-clean \
  --profile-db /home/vinc/gl-eval/textprofiles-9.db --index-db /home/vinc/gl-eval/atlas-9.db \
  --arms functional,dispatch,flood,faultslice,routing \
  --out /home/vinc/gl-eval/funceval-card.json | tee /home/vinc/gl-eval/funceval-ab.log
```

Read `funceval-card.json` → `arms.<arm>.by_bug_kind.functional.forced.recall@1`. **Acceptance:** on the functional subset, `dispatch`/`functional` recall@1 **materially exceeds `flood`**, and `flood`'s size-bias misses convert to abstentions (functional-subset coverage < 1.0 with higher selective-accuracy). On any crash cases present, `dispatch` matches `routing` (no regression).

- [ ] **Step 4: Write findings + push**

Write `docs/2026-07-10-functional-bug-match-findings.md` (mirror the v2 findings doc): the per-`bug_kind` A/B table, the abstention behavior on the functional negatives, the honest proxy-vs-production caveats (component dropped; text/abstention efficacy proxy-checked, production-confirmed). Update `docs/STATUS.md`. Commit, merge the feature branch `--no-ff`, verify green, push `origin master`, delete the branch. Update the `functional-bug-match-track` memory with the result.

---

## Critical files

- `groundloop/domains/android_ivi/functional_signals.py` — `FunctionalTextExtractor`, `DispatchExtractor`, `pack_prose`/`prose_query`, `PROSE_MARK`.
- `groundloop/adapters/index/text_profile.py` — `build_text_profiles`, `gather_repo_texts`.
- `groundloop/adapters/index/functional_text.py` — `FunctionalTextIndex`, `DispatchIndex`.
- `groundloop/funceval/{arms,runner}.py` — `build_functional_arms`, `run_funceval`, `TAU_FUNC`.
- `groundloop/synth/functional.py` — `build_functional_case`/`build_functional_dataset`/`build_functional_negatives`.
- `groundloop/eval/{dataset,scorecard,report,label_bug_kind}.py` — `bug_kind` field, `by_bug_kind` grading, renderer, labeling pass.
- `groundloop/cli/__init__.py` — `label-bugkind`, `build-textprofile`, `funceval` subparsers + `synth --mode functional`.
