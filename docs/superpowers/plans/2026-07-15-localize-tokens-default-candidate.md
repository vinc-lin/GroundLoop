# `--localize tokens` — Signal-Aware FTS5 Localize (default candidate) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Ship the validated file@1 lever — the extracted code tokens in the localize FTS5 query — as an opt-in `--localize tokens` Candidate (no embedder), so a `[production]` read can decide whether to promote it to the default localize.

**Why:** The 2026-07-14 `[proxy]` A/B showed the dispatch win was ENTIRELY Bug 2 (code-tokens-in-FTS5: carplay 0→0.494), while the semantic branch was neutral-to-negative. `--localize tokens` keeps only the winning part — and unlike `dispatch`/`semantic` it needs **no gateway embedder**, making it a viable default.

**Architecture:** New composition-root `SignalQueryIndex` (stash signals in `rank_repos`; rewrite the retrieve query to `code_query(signals)`, fallback to the passed prose query). No `core/`/schema edit. Reachable via `--localize tokens`, **not** default (governance-gated).

**Tech Stack:** Python 3.12, pytest, ruff (110). Branch `localize-tokens-default-candidate` off master (`f9aed3e`).

---

## Task 1: `SignalQueryIndex` + `--localize tokens` wiring + grade-run + tests

**Files:**
- Create: `groundloop/adapters/index/signal_query.py`
- Modify: `groundloop/cli/__init__.py` (argparse `--localize` choices line 775; wiring after line 1190), `groundloop/run/grade_run.py` (`_localize_index_for`, line 30)
- Test: `tests/test_signal_query.py`, and extend `tests/run/test_grade_run_dispatch.py` for the tokens arm.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_signal_query.py`:

```python
from groundloop.core.types import RepoRef, RepoScore, Signals


class _FakeMatch:
    def __init__(self):
        self.seen = None
    def rank_repos(self, signals, catalog):
        self.seen = signals
        return [RepoScore(RepoRef("r"), 1.0)]


class _EchoRetriever:
    def retrieve(self, repo, query):
        return [f"q={query}"]


def _sq():
    from groundloop.adapters.index.signal_query import SignalQueryIndex
    return SignalQueryIndex(_FakeMatch(), _EchoRetriever())


def test_rank_repos_delegates_and_stashes():
    sq = _sq(); sig = Signals(classes=("com.x.Foo",))
    assert sq.rank_repos(sig, [RepoRef("r")])[0].repo.name == "r"
    assert sq._match.seen is sig and sq._last_signals is sig


def test_retrieve_uses_code_tokens_not_prose():
    sq = _sq()
    sq.rank_repos(Signals(classes=("com.x.Foo",), methods=("bar",)), [RepoRef("r")])
    assert sq.retrieve(RepoRef("r"), "the wifi name is wrong") == ["q=com.x.Foo bar"]


def test_retrieve_falls_back_to_prose_when_no_code_tokens():
    sq = _sq()
    sq.rank_repos(Signals(), [RepoRef("r")])          # no code tokens
    assert sq.retrieve(RepoRef("r"), "wrong label") == ["q=wrong label"]


def test_retrieve_without_signals_uses_passed_query():
    sq = _sq()
    assert sq.retrieve(RepoRef("r"), "wrong label") == ["q=wrong label"]


def test_note_signals_seeds_for_out_of_loop_callers():
    sq = _sq()
    sq.note_signals(Signals(classes=("com.x.Foo",)))
    assert sq.retrieve(RepoRef("r"), "prose") == ["q=com.x.Foo"]


def test_argparse_accepts_localize_tokens():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(["run", "--localize", "tokens", "--dataset", "d",
                                    "--catalog", "c", "--work", "w", "--changes", "ch", "--index-db", "x"])
    assert ns.localize == "tokens"
```

Append to `tests/run/test_grade_run_dispatch.py`:

```python
def test_localize_index_for_tokens_needs_no_embedder(tmp_path):
    import json as _json
    from groundloop.run.grade_run import _localize_index_for
    from groundloop.adapters.index.signal_query import SignalQueryIndex
    (tmp_path / "manifest.json").write_text(_json.dumps({"localize": "tokens"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)   # embedder=None
    assert isinstance(idx, SignalQueryIndex) and arm == "tokens"
```

- [ ] **Step 2: Run — verify failures.** `.venv/bin/python -m pytest tests/test_signal_query.py tests/run/test_grade_run_dispatch.py -q` → FAIL (module/choice/arm missing).

- [ ] **Step 3a: Create `groundloop/adapters/index/signal_query.py`:**

```python
"""SignalQueryIndex: a composition-root CodeIndex that keeps rank_repos on the match index (stashing
the signals) and rewrites the localize query to the extracted CODE tokens (code_query) — the validated
file@1 lever: a crash stack / logcat naming the fault class → FTS5 exact-matches it. Falls back to the
passed prose query when no code tokens exist. No semantic branch, no embedder: the 2026-07-14 [proxy]
A/B showed bge-m3 on prose is neutral-to-negative at file@1 while tokens-in-FTS5 lifted functional
file@1 0.010->0.161. run/batch.py runs cases sequentially so the stash is race-free; note_signals()
seeds it for out-of-loop callers (grade-run's isolated diagnostic). No core/ or schema edit."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import code_query


class SignalQueryIndex:
    def __init__(self, match, fts_localize):
        self._match = match
        self._fts = fts_localize
        self._last_signals: Signals | None = None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        q = code_query(self._last_signals) if self._last_signals is not None else ""
        return self._fts.retrieve(repo, q or query)

    def note_signals(self, signals: Signals) -> None:
        self._last_signals = signals
```

- [ ] **Step 3b: CLI — add the choice** (line 775): `choices=["atlas", "semantic", "dispatch", "tokens"]`, and extend the help with: `| tokens (signal-aware FTS5: query the extracted code tokens, fallback prose; no embedder — the validated file@1 lever)`.

- [ ] **Step 3c: CLI — add the wiring branch** immediately AFTER the `elif localize_req == "dispatch":` block (after line 1190), same indentation:

```python
            elif localize_req == "tokens":
                from groundloop.adapters.index.signal_query import SignalQueryIndex
                index = SignalQueryIndex(index, AtlasIndex(args.index_db))
```

- [ ] **Step 3d: grade_run** — in `_localize_index_for` (`groundloop/run/grade_run.py:30`), add a tokens branch BEFORE the `if arm in ("semantic","dispatch")` block (tokens needs no embedder):

```python
    if arm == "tokens":
        from groundloop.adapters.index.signal_query import SignalQueryIndex
        return SignalQueryIndex(AtlasIndex(index_db), AtlasIndex(index_db)), arm
```
(The existing `note_signals` seeding in `grade_run` is guarded by `hasattr` — `SignalQueryIndex` has it, so the isolated diagnostic seeds correctly.)

- [ ] **Step 4: Run new tests + full suite + ruff.** `.venv/bin/python -m pytest tests/test_signal_query.py tests/run/test_grade_run_dispatch.py -q && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests` → all green.

- [ ] **Step 5: Commit.**
```bash
git add groundloop/adapters/index/signal_query.py groundloop/cli/__init__.py groundloop/run/grade_run.py tests/test_signal_query.py tests/run/test_grade_run_dispatch.py
git commit -m "feat(localize): --localize tokens (signal-aware FTS5, no embedder) — the validated file@1 lever

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Governance docs — register the Candidate

- [ ] Add a `--localize tokens` **Candidate** entry to `docs/capabilities.md` (no embedder; the validated file@1 lever; awaiting a `[production]` read to promote to default) and a row in the `docs/workflows.md` localize feature map. Commit.

---

## Task 3 (validation, operator): A/B `--localize atlas` vs `--localize tokens`

- [ ] On the dev box (ext4, `.env`, `KLOOP_DEV=1`): `gloop run … --match-arm flood --localize atlas` vs `--localize tokens` over `functional-clean` (no embedder needed), then `gloop grade-run --index-db atlas-9.db`; compare functional isolated file@1/@5 (expect `tokens` ≥ the dispatch 0.161, since it drops the semantic drag). Record `[proxy]`. The GEI re-run (user) resolves `[production]`.
