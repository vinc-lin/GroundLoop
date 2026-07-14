# Functional (no-crash) Localize Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift functional (no-crash) isolated localize `file@1` (currently 1/10) by routing prose-only/no-anchor tickets to bge-m3 semantic retrieval while leaving the crash FTS5 localize path byte-identical.

**Architecture:** A composition-root `LocalizeDispatchIndex` wraps the match index: `rank_repos` is delegated unchanged (and stashes the `Signals`); `retrieve` routes by a match-arm-independent discriminator `is_functional_localize` — prose-marked **or** no code anchor → semantic retriever, else → FTS5. `run/batch.py` runs `run_ticket` sequentially, so the stash is race-free; `note_signals()` seeds signals for out-of-loop callers (grade-run's isolated diagnostic). Wired via a new `--localize dispatch` choice. **Zero `core/` or schema edits.**

**Tech Stack:** Python 3.12, pytest, ruff (line 110); `.venv/bin/…`. Adapters in `groundloop/adapters/index/`; domain discriminator in `groundloop/domains/android_ivi/`; CLI composition root `groundloop/cli/__init__.py`; offline grader `groundloop/run/grade_run.py`.

**Spec:** `docs/superpowers/specs/2026-07-14-functional-localize-dispatch-design.md`

---

## File Structure

- **Create** `groundloop/adapters/index/localize_dispatch.py` — `LocalizeDispatchIndex` (the dispatch adapter). One responsibility: route localize by last-seen signals.
- **Modify** `groundloop/domains/android_ivi/functional_signals.py` — add `is_functional_localize(signals)` free function (the match-arm-independent discriminator). Co-located with `PROSE_MARK`/`DispatchExtractor`.
- **Modify** `groundloop/cli/__init__.py` — add `dispatch` to `--localize` choices (~line 1024) and a `dispatch` wiring branch in the localize block (~after line 1442).
- **Modify** `groundloop/run/grade_run.py` — the isolated-localize diagnostic reconstructs the run's localize index from `manifest.json` and seeds signals via `note_signals`.
- **Create** `tests/test_localize_dispatch.py` — Type-1 hermetic tests for the discriminator + adapter + argparse choice.
- **Create** `tests/run/test_grade_run_dispatch.py` — Type-1 test: grade-run reads `manifest.localize` and the atlas arm still computes isolated file@k (backward-compat + selection logic).
- **Create** `tests/e2e/test_localize_dispatch_live.py` — gated Type-2 mechanism check (real atlas + embedder).
- **Modify** `docs/capabilities.md`, `docs/workflows.md` — register `--localize dispatch` as a Candidate.

---

## Task 1: `is_functional_localize` discriminator

**Files:**
- Modify: `groundloop/domains/android_ivi/functional_signals.py` (add function after `prose_query`, ~line 25)
- Test: `tests/test_localize_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_localize_dispatch.py`:

```python
from groundloop.core.types import Signals
from groundloop.domains.android_ivi.functional_signals import (
    PROSE_MARK, is_functional_localize)


def test_is_functional_localize_prose_marked_is_true():
    # DispatchExtractor stuffs prose into symbols[0] behind PROSE_MARK
    sig = Signals(symbols=(PROSE_MARK + "carplay icon does nothing when tapped",))
    assert is_functional_localize(sig) is True


def test_is_functional_localize_no_anchor_is_true():
    # A prose-only ticket under a non-dispatch extractor: no code tells extracted
    assert is_functional_localize(Signals()) is True
    assert is_functional_localize(Signals(errors=("ANR",))) is True  # generic error != code anchor


def test_is_functional_localize_with_code_anchor_is_false():
    sig = Signals(classes=("com.x.CarPlaySession",), methods=("onConnect",),
                  libraries=("libcarplay.so",))
    assert is_functional_localize(sig) is False


def test_is_functional_localize_native_symbol_anchor_is_false():
    # A real native symbol (NOT prose-marked) is a crash anchor -> FTS5 path
    assert is_functional_localize(Signals(symbols=("IAP2Session",))) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q`
Expected: FAIL — `ImportError: cannot import name 'is_functional_localize'`

- [ ] **Step 3: Write minimal implementation**

In `groundloop/domains/android_ivi/functional_signals.py`, add after `prose_query` (after line 24):

```python
def is_functional_localize(signals) -> bool:
    """Localize-side discriminator: True iff localize should use the semantic (bge-m3) retriever
    instead of FTS5-over-symbols — the ticket is prose-marked (DispatchExtractor) OR carries no
    code anchor at all. MATCH-ARM-INDEPENDENT: unlike DispatchIndex._is_functional (PROSE_MARK
    only, correct only under the dispatch match arm), this also fires under the Core component/flood
    extractors, where a no-crash ticket yields anchorless Signals. No anchor => no symbol token to
    feed FTS5 => use the vector retriever. `errors` (generic exception names) are NOT anchors."""
    if signals.symbols and signals.symbols[0].startswith(PROSE_MARK):
        return True
    return not (signals.classes or signals.methods or signals.symbols
                or signals.libraries or signals.packages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add groundloop/domains/android_ivi/functional_signals.py tests/test_localize_dispatch.py
git commit -m "feat(localize): match-arm-independent is_functional_localize discriminator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `LocalizeDispatchIndex` adapter

**Files:**
- Create: `groundloop/adapters/index/localize_dispatch.py`
- Test: `tests/test_localize_dispatch.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_localize_dispatch.py`:

```python
from groundloop.core.types import RepoRef, RepoScore


class _FakeMatch:
    def __init__(self):
        self.seen = None
    def rank_repos(self, signals, catalog):
        self.seen = signals
        return [RepoScore(RepoRef("r"), 1.0)]


class _FakeRetriever:
    def __init__(self, tag):
        self.tag = tag
    def retrieve(self, repo, query):
        return [f"{self.tag}:{repo.name}"]


def _dispatch():
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    return LocalizeDispatchIndex(_FakeMatch(), _FakeRetriever("crash"), _FakeRetriever("func"))


def test_rank_repos_delegates_and_stashes_signals():
    d = _dispatch()
    sig = Signals(classes=("com.x.Foo",))
    out = d.rank_repos(sig, [RepoRef("r")])
    assert out[0].repo.name == "r"
    assert d._match.seen is sig            # delegated to the match index
    assert d._last_signals is sig          # stashed for the following retrieve


def test_retrieve_routes_functional_to_semantic_after_rank():
    d = _dispatch()
    d.rank_repos(Signals(), [RepoRef("r")])          # no-anchor -> functional
    assert d.retrieve(RepoRef("r"), "q") == ["func:r"]


def test_retrieve_routes_crash_to_fts5_after_rank():
    d = _dispatch()
    d.rank_repos(Signals(classes=("com.x.Foo",)), [RepoRef("r")])   # anchored -> crash
    assert d.retrieve(RepoRef("r"), "q") == ["crash:r"]


def test_retrieve_without_signals_falls_back_to_crash():
    d = _dispatch()
    assert d.retrieve(RepoRef("r"), "q") == ["crash:r"]   # no rank/seed -> safe FTS5 default


def test_note_signals_seeds_functional_route_for_out_of_loop_callers():
    d = _dispatch()
    d.note_signals(Signals(symbols=(PROSE_MARK + "prose",)))
    assert d.retrieve(RepoRef("r"), "q") == ["func:r"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q`
Expected: FAIL — `ModuleNotFoundError: groundloop.adapters.index.localize_dispatch`

- [ ] **Step 3: Write minimal implementation**

Create `groundloop/adapters/index/localize_dispatch.py`:

```python
"""LocalizeDispatchIndex: a composition-root CodeIndex that keeps rank_repos on the match index but
routes localize (retrieve) by the LAST-seen Signals — prose-only / no-anchor tickets to a semantic
(bge-m3) retriever, crash / anchored tickets to the FTS5 retriever. run_ticket calls rank_repos then
retrieve back-to-back per ticket and run/batch.py runs cases sequentially, so stashing the Signals in
rank_repos is race-free. note_signals() seeds the Signals for out-of-loop callers (grade-run's
isolated-localize diagnostic) that call retrieve without a preceding rank_repos. No core/ or schema
edit; the crash path is byte-identical to today's atlas FTS5 localize."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import is_functional_localize


class LocalizeDispatchIndex:
    def __init__(self, match, crash_localize, functional_localize):
        self._match = match
        self._crash = crash_localize
        self._functional = functional_localize
        self._last_signals: Signals | None = None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        sig = self._last_signals
        if sig is not None and is_functional_localize(sig):
            return self._functional.retrieve(repo, query)
        return self._crash.retrieve(repo, query)

    def note_signals(self, signals: Signals) -> None:
        self._last_signals = signals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/index/localize_dispatch.py tests/test_localize_dispatch.py
git commit -m "feat(localize): LocalizeDispatchIndex — signals-routed crash/functional retrieve

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Wire `--localize dispatch` into the CLI run path

**Files:**
- Modify: `groundloop/cli/__init__.py` (argparse ~line 1024; localize wiring block ~lines 1424–1442)
- Test: `tests/test_localize_dispatch.py` (append — argparse choice)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_localize_dispatch.py`:

```python
def test_argparse_accepts_localize_dispatch():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(["run", "--localize", "dispatch"])
    assert ns.localize == "dispatch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py::test_argparse_accepts_localize_dispatch -q`
Expected: FAIL — `SystemExit: 2` (argparse rejects the invalid choice `dispatch`)

- [ ] **Step 3a: Add the choice + help**

In `groundloop/cli/__init__.py`, change the `--localize` argument (~line 1024):

```python
    r.add_argument("--localize", choices=["atlas", "semantic", "dispatch"], default=None,
                   help="localize retriever, chosen independently of --match-arm (default resolved by "
                        "--profile: atlas in core, semantic in labs): atlas (FTS5) | semantic (bge-m3 vector, "
                        "needs KLOOP_EMBED_BASE_URL) | dispatch (per-ticket: prose-only/no-anchor -> bge-m3 "
                        "vector, crash/anchored -> FTS5; needs KLOOP_EMBED_BASE_URL). When it differs from the "
                        "match arm's native retrieve, the index is wrapped (SplitIndex / LocalizeDispatchIndex). "
                        "A labs-DEFAULTED semantic/dispatch localize degrades to atlas (warn) without an "
                        "embedder; explicit --localize semantic/dispatch fails closed.")
```

- [ ] **Step 3b: Add the dispatch wiring branch**

In the localize block, immediately **after** the existing `elif localize_req == "atlas" and arm_req == "semantic":` branch (the `SplitIndex(index, AtlasIndex(...))` case, ~line 1442), add:

```python
            elif localize_req == "dispatch":
                emb = _build_embedder()
                if emb is None:
                    if localize_explicit:
                        print("gloop run --localize dispatch: no embedder — set KLOOP_EMBED_BASE_URL "
                              "(bge-m3 gateway). The functional branch needs the vector index.")
                        return 2
                    # labs-DEFAULTED dispatch localize: degrade to atlas FTS5 (warn), record honestly.
                    print("gloop run (labs): --localize dispatch wanted but no embedder — falling back "
                          "to atlas FTS5 localize. Set KLOOP_EMBED_BASE_URL to engage dispatch localize.")
                    localize_req = "atlas"
                else:
                    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
                    index = LocalizeDispatchIndex(index, AtlasIndex(args.index_db),
                                                  SemanticAtlasIndex(args.index_db, emb))
```

(The manifest already records `localize=localize_req` at line 1489, so a degraded run honestly records `"atlas"` and an engaged run records `"dispatch"`. No manifest change needed.)

- [ ] **Step 4: Run test + full suite + ruff**

Run: `.venv/bin/python -m pytest tests/test_localize_dispatch.py -q && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: PASS (all green, ruff clean)

- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/test_localize_dispatch.py
git commit -m "feat(cli): --localize dispatch wiring (embedder-degrade to atlas, manifest honest)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: grade-run isolated diagnostic uses the run's localize index

**Files:**
- Modify: `groundloop/run/grade_run.py` (the isolated-diagnostic block ~lines 130–136; `grade_run` signature line 116)
- Modify: `groundloop/cli/__init__.py` (`_run_grade_run` ~line 1310 — pass the embedder)
- Test: `tests/run/test_grade_run_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/run/test_grade_run_dispatch.py`:

```python
import json
from groundloop.run.grade_run import _localize_index_for, _signals_from_doc
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals


def test_localize_index_for_reads_manifest_arm(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "atlas"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and arm == "atlas"


def test_localize_index_for_dispatch_without_embedder_degrades(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"localize": "dispatch"}))
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and "atlas" in arm   # no embedder -> FTS5 fallback


def test_localize_index_for_missing_manifest_defaults_atlas(tmp_path):
    idx, arm = _localize_index_for(str(tmp_path), "unused.db", None)
    assert isinstance(idx, AtlasIndex) and arm == "atlas"


def test_signals_from_doc_reconstructs_from_dict():
    class _Doc:
        signals = {"classes": ["com.x.Foo"], "symbols": [], "bogus": ["drop-me"]}
    sig = _signals_from_doc(_Doc())
    assert isinstance(sig, Signals) and sig.classes == ("com.x.Foo",)


def test_signals_from_doc_handles_missing_signals():
    class _Doc:
        signals = None
    assert _signals_from_doc(_Doc()) == Signals()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/run/test_grade_run_dispatch.py -q`
Expected: FAIL — `ImportError: cannot import name '_localize_index_for'`

- [ ] **Step 3a: Add helpers + wire the isolated diagnostic**

In `groundloop/run/grade_run.py`, add these helpers (near the top, after the imports):

```python
def _signals_from_doc(doc):
    """Reconstruct a Signals from the persisted run-record dict (JSON round-trip -> lists).
    Unknown keys are dropped; missing -> Signals defaults (anchorless -> functional route)."""
    from groundloop.core.types import Signals
    raw = getattr(doc, "signals", None) or {}
    fields = ("packages", "classes", "methods", "symbols", "libraries", "errors")
    return Signals(**{k: tuple(raw[k]) for k in fields if k in raw})


def _localize_index_for(runs_dir, index_db, embedder):
    """Build the isolated-diagnostic localize index matching the arm the run used (manifest.localize).
    Falls back to AtlasIndex (FTS5) when the arm needs an embedder and none is available."""
    arm = "atlas"
    mpath = Path(runs_dir) / "manifest.json"
    if mpath.exists():
        arm = json.loads(mpath.read_text()).get("localize", "atlas")
    if arm in ("semantic", "dispatch") and embedder is not None:
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        sem = SemanticAtlasIndex(index_db, embedder)
        if arm == "semantic":
            return sem, arm
        from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
        return LocalizeDispatchIndex(AtlasIndex(index_db), AtlasIndex(index_db), sem), arm
    fell_back = arm in ("semantic", "dispatch")     # wanted embedder, none available
    return AtlasIndex(index_db), (f"{arm}->atlas(no-embedder)" if fell_back else "atlas")
```

Then change `grade_run`'s signature and its isolated-diagnostic block. Signature (line 116):

```python
def grade_run(runs_dir: str, dataset: str, *, index_db: str | None = None, embedder=None) -> dict:
```

Replace the isolated-diagnostic block (lines 130–135, `if index_db: idx = AtlasIndex(index_db) ...`) with:

```python
    # The isolated-localize diagnostic: re-run retrieve on the ORACLE repo (grade-only, never the loop).
    # Reconstruct the localize index the run actually used (manifest.localize) and seed per-case signals.
    if index_db:
        idx, _iso_arm = _localize_index_for(runs_dir, index_db, embedder)
        for r in rows:
            if r["expected"]:
                if hasattr(idx, "note_signals"):
                    idx.note_signals(_signals_from_doc(r["doc"]))
                r["retrieved"] = idx.retrieve(RepoRef(r["owner"]), r["query"])
```

- [ ] **Step 3b: Pass the embedder from the CLI**

In `groundloop/cli/__init__.py`, in `_run_grade_run` (~line 1310), change:

```python
    card = grade_run(args.runs, args.dataset, index_db=args.index_db or None, embedder=_build_embedder())
```

- [ ] **Step 4: Run new test + backward-compat guard + full suite + ruff**

Run: `.venv/bin/python -m pytest tests/run/test_grade_run_dispatch.py tests/run/test_grade_run_diag.py -q && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests`
Expected: PASS — new tests green; `test_grade_run_diag.py` still green (atlas isolated path unchanged, `note_signals` skipped via `hasattr` for `AtlasIndex`); full suite green; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add groundloop/run/grade_run.py groundloop/cli/__init__.py tests/run/test_grade_run_dispatch.py
git commit -m "feat(grade-run): isolated diagnostic reconstructs the run's localize index + seeds signals

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Gated Type-2 e2e mechanism check

**Files:**
- Create: `tests/e2e/test_localize_dispatch_live.py`

- [ ] **Step 1: Write the gated test**

Create `tests/e2e/test_localize_dispatch_live.py`:

```python
"""Type-2 (gated live) mechanism check: with a real atlas.db + gateway embedder, --localize dispatch
routes a prose-only functional ticket to the semantic retriever and a crash ticket to FTS5. Not a
score threshold — a routing/mechanism assertion. Gated: needs KLOOP_ATLAS_DB + KLOOP_EMBED_BASE_URL."""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("KLOOP_ATLAS_DB") and os.environ.get("KLOOP_EMBED_BASE_URL")),
    reason="needs KLOOP_ATLAS_DB + KLOOP_EMBED_BASE_URL (Type-2 live)")


def _one_repo(db):
    from groundloop.engines.atlas.store import Store
    return Store(db).list_repo_states()[0][0]   # (repo, head, indexed_at, unit_count) rows


def test_dispatch_routes_functional_to_semantic_and_crash_to_fts5():
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    from groundloop.cli import _build_embedder
    from groundloop.core.types import RepoRef, Signals
    from groundloop.domains.android_ivi.functional_signals import PROSE_MARK

    db = os.environ["KLOOP_ATLAS_DB"]
    repo = RepoRef(_one_repo(db))
    d = LocalizeDispatchIndex(AtlasIndex(db), AtlasIndex(db),
                              SemanticAtlasIndex(db, _build_embedder()))

    # prose-only (no-anchor) -> functional (semantic) branch
    d.note_signals(Signals(symbols=(PROSE_MARK + "the settings screen shows the wrong label",)))
    func_hits = d.retrieve(repo, "the settings screen shows the wrong label")

    # crash anchor -> FTS5 branch (identical to AtlasIndex.retrieve)
    d.note_signals(Signals(classes=("com.x.Foo",)))
    crash_hits = d.retrieve(repo, "Foo")
    fts5_hits = AtlasIndex(db).retrieve(repo, "Foo")
    assert crash_hits == fts5_hits            # crash path byte-identical to atlas FTS5
    assert isinstance(func_hits, list)        # semantic branch executed (may be empty on a tiny atlas)
```

- [ ] **Step 2: Run gated (skips without env) + confirm collection**

Run: `.venv/bin/python -m pytest tests/e2e/test_localize_dispatch_live.py -q`
Expected: `1 skipped` (no live env) — confirms it collects/imports cleanly.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_localize_dispatch_live.py
git commit -m "test(e2e): gated Type-2 mechanism check for --localize dispatch routing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Register the Candidate in governance docs

**Files:**
- Modify: `docs/capabilities.md`, `docs/workflows.md`

- [ ] **Step 1: Add capability + feature-map rows**

In `docs/capabilities.md`, add a **Candidate** entry to the capability registry for `--localize dispatch`:

> **`--localize dispatch` (functional localize)** — Candidate. Per-ticket localize routing: prose-only/no-anchor → bge-m3 semantic retrieve, crash/anchored → FTS5 (byte-identical to `atlas`). Composition-root `LocalizeDispatchIndex`; no `core/`/schema edit. Reachable via the flag; **not** a default. Evidence: awaiting a `[proxy]` functional isolated `file@1`/`file@5` A/B (synth functional dataset) then a `[production]` GEI confirmation. Baseline: functional isolated `file@1 = 1/10`, `file@5 = 7/10` (`results-log.md`, 2026-07-11).

In `docs/workflows.md`, add `dispatch` to the localize row of the per-stage feature map (localize stage × retriever × state): `dispatch` — Candidate (functional, needs embedder).

- [ ] **Step 2: Commit**

```bash
git add docs/capabilities.md docs/workflows.md
git commit -m "docs(governance): register --localize dispatch as a Candidate (reachable != default)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Validation — proxy A/B protocol (operational, run after Task 6)

Not a code task; the measurement that decides whether `dispatch` earns a default. Requires a real
atlas + gateway embedder (dev box, off v9fs — run on ext4 per `docs/build-setup.md`).

1. Build a functional-localize dataset from mined positives:
   `gloop synth` functional path (`groundloop/synth/functional.py:build_functional_dataset`) → a
   dataset of prose-only + prose+non-crash-log cases carrying `expected_files`, `bug_kind=functional`.
2. Baseline vs treatment (same match arm, e.g. `--match-arm flood`, hold match constant):
   - `gloop run --index-db <atlas> --dataset <fn> --out <A> --localize atlas   --fixer canned`
   - `gloop run --index-db <atlas> --dataset <fn> --out <B> --localize dispatch --fixer canned`
3. Grade each and read the **functional** `by_bug_kind` **isolated** `file@1`/`file@5`:
   - `gloop grade-run --runs <A> --dataset <fn> --index-db <atlas> --out <A>.json`
   - `gloop grade-run --runs <B> --dataset <fn> --index-db <atlas> --out <B>.json`
4. Expect: `atlas` reproduces the low `file@1` shape; `dispatch` lifts functional `file@1`/`file@5`;
   **crash `by_bug_kind` unchanged** (regression guard). Log to `docs/results-log.md`, tag `[proxy]`.
5. If `file@5` lifts but `file@1` stays short → trigger the staged follow-ons (spec §7: B signal-tokens
   query, then C hybrid RRF + rerank). Production confirmation: GEI functional set, tag `[production]`.

---

## Self-Review (author checklist — done)

- **Spec coverage:** Component 1 → Tasks 1–2; Component 2 → Task 3; Component 3 → Task 4; Component 4 →
  Validation section; §5 testing → Tasks 1,2,4,5; §8 governance → Task 6. All covered.
- **Placeholder scan:** no TBD/TODO; every code step shows full code.
- **Type consistency:** `is_functional_localize` (Task 1) used identically in Task 2 adapter, Task 3
  wiring (indirectly), Task 4 (via the dispatch index), Task 5. `LocalizeDispatchIndex(match, crash,
  functional)` constructor arity consistent across Tasks 2/3/4/5. `note_signals` / `_signals_from_doc`
  / `_localize_index_for` signatures consistent between Task 4 impl and its tests.
