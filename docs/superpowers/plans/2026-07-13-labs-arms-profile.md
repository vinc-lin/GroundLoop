# Labs arms + `KLOOP_LABS` profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Wire the experimental Candidate arms (`functional`/`dispatch`/`semantic`/`judge` match + `semantic`
localize) into `gloop run` as *selectable* arms, plus a `KLOOP_LABS`/`--profile labs` switch that flips the run
defaults to the experimental stack — **without** changing the Core default when the profile is unset.

**Architecture:** All at the composition root (`groundloop/cli/__init__.py`) + a small `SplitIndex` adapter +
`run/manifest.py` + docs. **NEVER edit `groundloop/core/`; NEVER touch the SQLite schema.** Mirror the
`gloop eval`/`funceval` construction exactly. Spec:
`docs/superpowers/specs/2026-07-13-labs-arms-and-profile-design.md`.

**Tech Stack:** Python 3.12 `.venv`. Tests `.venv/bin/python -m pytest -q`; ruff `.venv/bin/ruff check groundloop
tests` (line 110). Branch `labs-arms-profile`. Commit only when green + ruff clean; trailer
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Guard git against the v9fs
`.git/index.lock` race.

**Grounding (verified constructors):**
- `SemanticAtlasIndex(db_path, embedder)`; `LLMJudgeIndex(base_index, judge)`, `GatewayJudge(base_url,
  api_key, model)`; `FunctionalTextIndex(profile_db, embedder, atlas_db=index_db)`;
  `DispatchIndex(FaultRoutingIndex(index_db), functional_index, fault_scale=_FAULT_SCALE)`.
- Extractors are no-arg: `FunctionalTextExtractor()`, `DispatchExtractor()`; `semantic`/`judge` keep the base
  `AndroidSignalExtractor`.
- `_FAULT_SCALE` lives in `groundloop/funceval/arms.py` (`= TAU_FUNC[0]/_TAU_RRF[0]`) — import it, don't
  replicate.
- Embedder: `GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)` when
  `KLOOP_EMBED_BASE_URL` is set (mirror `_run_kb_ab`). Judge creds = the `produce_*` settings.
- The functional/dispatch **profile artifact** is a `--profile-db` built by `gloop build-textprofile`.
- The run handler's index-selection block is an `if args.index_db: index = AtlasIndex(...); if
  args.match_arm=="routing": ... elif "component": ... else: <flood/tokenindex>` chain; `match_arm`
  (the honest actual-ran arm) is initialized from the request and set to `"flood"` on any fallback.

---

## Task 1: `SplitIndex` composite adapter

**Why:** the `CodeIndex` port does BOTH `rank_repos` and `retrieve` on one object, but `--localize` must be
choosable independently of `--match-arm`. `SplitIndex` delegates each to a different index.

**Files:** Create `groundloop/adapters/index/split.py`; Test `tests/adapters/test_split_index.py` (new).

- [ ] **Step 1 — failing test** `tests/adapters/test_split_index.py`:
```python
from groundloop.adapters.index.split import SplitIndex

class _Idx:
    def __init__(self, tag): self.tag = tag
    def rank_repos(self, signals, catalog): return [("rank", self.tag)]
    def retrieve(self, repo, query): return [f"loc:{self.tag}"]

def test_split_index_delegates_each_method():
    s = SplitIndex(_Idx("M"), _Idx("L"))
    assert s.rank_repos(None, []) == [("rank", "M")]     # from the MATCH index
    assert s.retrieve(None, "q") == ["loc:L"]            # from the LOCALIZE index
```

- [ ] **Step 2 — run, confirm FAIL** (`ModuleNotFoundError`).

- [ ] **Step 3 — implement** `groundloop/adapters/index/split.py`:
```python
"""A CodeIndex composite: rank_repos from the MATCH index, retrieve from the LOCALIZE index. Lets
`gloop run` choose --localize independently of --match-arm (run_ticket uses one index for both). Pure
composition-root adapter — no core edit."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals


class SplitIndex:
    def __init__(self, match, localize):
        self._match = match
        self._localize = localize

    def rank_repos(self, signals: Signals, catalog) -> list[RepoScore]:
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self._localize.retrieve(repo, query)
```
(Confirm the `RepoScore`/`RepoRef`/`Signals` import names against `core/types.py`; drop the type hints to bare
if any name differs — behavior is what matters.)

- [ ] **Step 4 — run** `.venv/bin/python -m pytest tests/adapters/test_split_index.py -q` PASS; full suite green; ruff clean.
- [ ] **Step 5 — commit** `git add groundloop/adapters/index/split.py tests/adapters/test_split_index.py && git commit -m "feat(index): SplitIndex composite (rank from match, retrieve from localize)"`

---

## Task 2: `_build_embedder()` helper + `--match-arm semantic` & `judge`

**Why:** wire the two creds-only experimental match arms; extract the env-driven embedder into a reusable
helper (used again by functional/dispatch/localize).

**Files:** Modify `groundloop/cli/__init__.py` (add `_build_embedder`, extend `--match-arm` choices, add the
two branches + fail-closed guards); Test `tests/run/test_labs_match_arms.py` (new).

- [ ] **Step 1 — failing test** `tests/run/test_labs_match_arms.py` — build the arms at the composition root
  with a **monkeypatched** embedder/judge so no live gateway is needed. Two paths per arm:
  (a) with creds present (monkeypatch `KLOOP_EMBED_BASE_URL` + `_build_embedder` to return a stub, or
  `SemanticAtlasIndex`/`GatewayJudge` to stubs), `main(["run", ... "--match-arm","semantic", ...])` proceeds
  past index construction; (b) `--match-arm semantic` with `KLOOP_EMBED_BASE_URL` unset → `main(...)` returns
  `2` with "embedder" in the output; `--match-arm judge` with no `KLOOP_PRODUCE_API_KEY` → `2` with "judge"/
  "creds". Keep it a composition-root/`main()` test (the autouse `KLOOP_DEV` fixture is already on).
  Prefer asserting the fail-closed rc/message (deterministic) + that a stubbed-creds build does not hit the
  guard. Read `tests/run/test_dev_gate.py` for the `main()`-invocation style.

- [ ] **Step 2 — run, confirm FAIL** (`--match-arm semantic` not a valid choice yet).

- [ ] **Step 3 — implement** (`groundloop/cli/__init__.py`):
  1. Extend the run `--match-arm` choices to `["flood","routing","component","semantic","judge","functional","dispatch"]`
     (add all four now; functional/dispatch get their branches in Task 3 — but adding them to `choices` now is
     fine since an unhandled choice would fall through; to be safe, Task 3 adds their branches before anything
     selects them — OR add only `semantic,judge` here and `functional,dispatch` in Task 3. **Add only
     `semantic,judge` to choices in THIS task**; Task 3 adds `functional,dispatch`.)
  2. Add a module-level helper:
```python
def _build_embedder():
    """GatewayEmbedder when KLOOP_EMBED_BASE_URL is set, else None (mirrors _run_kb_ab)."""
    import os
    if not os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        return None
    from groundloop.config.settings import Settings
    from groundloop.engines.atlas.embed import GatewayEmbedder
    st = Settings.load()
    return GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
```
  3. In the run handler's index-selection chain (inside `if args.index_db:`), add branches after the existing
     `component` branch:
```python
            elif args.match_arm == "semantic":
                emb = _build_embedder()
                if emb is None:
                    print("gloop run --match-arm semantic: no embedder — set KLOOP_EMBED_BASE_URL "
                          "(bge-m3 gateway). This arm needs the vector index.")
                    return 2
                from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                index = SemanticAtlasIndex(args.index_db, emb)
            elif args.match_arm == "judge":
                if not os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
                    print("gloop run --match-arm judge: no judge creds — set KLOOP_PRODUCE_API_KEY.")
                    return 2
                from groundloop.adapters.index.atlas_judge import GatewayJudge, LLMJudgeIndex
                from groundloop.config.settings import Settings as _S
                s = _S.load()
                index = LLMJudgeIndex(AtlasIndex(args.index_db), GatewayJudge(
                    s.produce_base_url, s.produce_api_key, s.produce_main_model))
```
  (Both keep the base `AndroidSignalExtractor` — no `extractor` reassignment. `match_arm` stays the requested
  value = honest, since these arms do run when their creds are present.)

- [ ] **Step 4 — run** `tests/run/ tests/test_cli.py` PASS; full suite green; ruff clean.
- [ ] **Step 5 — commit** `git add groundloop/cli/__init__.py tests/run/test_labs_match_arms.py && git commit -m "feat(run): selectable --match-arm semantic|judge (fail-closed without creds)"`

---

## Task 3: `--match-arm functional` & `dispatch` + `--functional-profile`

**Why:** wire the two arms that need a repo-text profile artifact; dispatch composes fault + functional.

**Files:** Modify `groundloop/cli/__init__.py` (choices + `--functional-profile` flag + two branches +
guards); extend `tests/run/test_labs_match_arms.py`.

- [ ] **Step 1 — failing test** — add cases: `--match-arm functional` with an embedder stub but NO
  `--functional-profile`/`KLOOP_FUNCTIONAL_PROFILE` → `main(...)` returns `2` with "profile"; with both a
  stub embedder and a profile path present, the `functional` branch builds `FunctionalTextIndex` + swaps in
  `FunctionalTextExtractor` (assert it proceeds past construction, e.g. monkeypatch `FunctionalTextIndex` to a
  stub and assert it was constructed). `dispatch` analogous. Run → FAIL (`functional` not a choice yet).

- [ ] **Step 2 — run, confirm FAIL.**

- [ ] **Step 3 — implement:**
  1. Add `"functional","dispatch"` to the `--match-arm` choices.
  2. Add `r.add_argument("--functional-profile", default="", help="repo-text profile db (gloop
     build-textprofile) for --match-arm functional/dispatch; else KLOOP_FUNCTIONAL_PROFILE")`.
  3. Branches (after `judge`):
```python
            elif args.match_arm in ("functional", "dispatch"):
                emb = _build_embedder()
                profile_db = args.functional_profile or os.environ.get("KLOOP_FUNCTIONAL_PROFILE", "").strip()
                if emb is None or not profile_db:
                    print("gloop run --match-arm functional/dispatch: needs an embedder "
                          "(KLOOP_EMBED_BASE_URL) AND a repo-text profile "
                          "(--functional-profile / KLOOP_FUNCTIONAL_PROFILE, built by `gloop build-textprofile`).")
                    return 2
                from groundloop.adapters.index.functional_text import DispatchIndex, FunctionalTextIndex
                from groundloop.domains.android_ivi.functional_signals import (
                    DispatchExtractor, FunctionalTextExtractor)
                ftext = FunctionalTextIndex(profile_db, emb, atlas_db=args.index_db)
                if args.match_arm == "functional":
                    index, extractor = ftext, FunctionalTextExtractor()
                else:
                    from groundloop.adapters.index.fault_routing import FaultRoutingIndex
                    from groundloop.funceval.arms import _FAULT_SCALE   # tuned fault/functional scale (SSOT)
                    index = DispatchIndex(FaultRoutingIndex(args.index_db), ftext, fault_scale=_FAULT_SCALE)
                    extractor = DispatchExtractor()
```

- [ ] **Step 4 — run** `tests/run/ tests/funceval/` PASS; full suite green; ruff clean.
- [ ] **Step 5 — commit** `git add groundloop/cli/__init__.py tests/run/test_labs_match_arms.py && git commit -m "feat(run): selectable --match-arm functional|dispatch (fail-closed without embedder+profile)"`

---

## Task 4: `--localize {atlas,semantic}` + SplitIndex wiring

**Why:** choose the localize retriever independently of the match arm; semantic localize via `SplitIndex`.

**Files:** Modify `groundloop/cli/__init__.py` (add `--localize`, wrap the built `index` in `SplitIndex` when
localize ≠ the match arm's native retrieve); Test `tests/run/test_localize_arm.py` (new).

- [ ] **Step 1 — failing test** — `--localize semantic` with a stub embedder wraps the match index in a
  `SplitIndex` whose `retrieve` comes from a `SemanticAtlasIndex` (monkeypatch `SemanticAtlasIndex` to a stub;
  assert the composed index is a `SplitIndex`). `--localize semantic` with NO embedder → `main(...)` returns
  `2` with "embedder" (fail-closed when explicit). Default `--localize atlas` with a non-semantic match → no
  `SplitIndex` (index unchanged). Run → FAIL (`--localize` unknown flag).

- [ ] **Step 2 — run, confirm FAIL.**

- [ ] **Step 3 — implement:**
  1. `r.add_argument("--localize", choices=["atlas","semantic"], default="atlas", help="localize retriever: "
     "atlas (FTS5, default) | semantic (bge-m3 vector, needs KLOOP_EMBED_BASE_URL)")`.
  2. AFTER the index-selection chain has built `index` (and only when `args.index_db` is set), before wiring
     the estate/fixer, add the localize split:
```python
            # localize retriever (independent of the match arm). semantic-match already retrieves via vectors.
            if args.localize == "semantic" and args.match_arm != "semantic":
                emb = _build_embedder()
                if emb is None:
                    print("gloop run --localize semantic: no embedder — set KLOOP_EMBED_BASE_URL.")
                    return 2
                from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                from groundloop.adapters.index.split import SplitIndex
                index = SplitIndex(index, SemanticAtlasIndex(args.index_db, emb))
            elif args.localize == "atlas" and args.match_arm == "semantic":
                from groundloop.adapters.index.split import SplitIndex
                index = SplitIndex(index, AtlasIndex(args.index_db))
```
  (Reuse `_build_embedder`; the second branch handles semantic-match + atlas-localize. Place this AFTER the
  `if/elif` arm chain but still inside `if args.index_db:`.)

- [ ] **Step 4 — run** `tests/run/` PASS; full suite green; ruff clean.
- [ ] **Step 5 — commit** `git add groundloop/cli/__init__.py groundloop/adapters/index/split.py tests/run/test_localize_arm.py && git commit -m "feat(run): --localize {atlas,semantic} via SplitIndex"`

---

## Task 5: `--profile {core,labs}` / `KLOOP_LABS` + manifest fields

**Why:** the per-environment switch that flips run defaults to the experimental stack (routing match +
semantic localize + plan fix), explicit flags overriding; record `profile`/`localize` in the manifest.

**Files:** Modify `groundloop/cli/__init__.py` (`--profile` flag, None-sentinel defaults for
`--match-arm`/`--localize`, the labs resolution + the semantic-localize degrade-under-labs, thread
`profile`/`localize` to the manifest); `groundloop/run/manifest.py` (two new fields); Test
`tests/run/test_labs_profile.py` (new).

- [ ] **Step 1 — failing test** `tests/run/test_labs_profile.py`:
  - `build_parser().parse_args(["run", ...])` with no `--match-arm`/`--localize` → those attrs are `None`
    (sentinel).
  - the resolution helper (extract as `_resolve_arms(args) -> (match_arm, localize, profile)` for testability):
    `--profile labs` → `("routing","semantic","labs")`; bare (core) → `("component","atlas","core")`;
    `--profile labs --match-arm functional` → `("functional","semantic","labs")` (explicit overrides);
    `KLOOP_LABS=1` env → same as `--profile labs`.
  - `write_manifest(...)` includes `profile` and `localize`.
  - degrade: with `KLOOP_LABS=1` and NO embedder, the *labs-defaulted* localize=semantic degrades to `atlas`
    with a warning (not exit 2); but an *explicit* `--localize semantic` with no embedder still exits 2.

- [ ] **Step 2 — run, confirm FAIL.**

- [ ] **Step 3 — implement:**
  1. `r.add_argument("--profile", choices=["core","labs"], default="core", help="core (default) | labs "
     "(experimental defaults: routing match + semantic localize; also KLOOP_LABS=1)")`.
  2. Change `--match-arm` and `--localize` argparse `default=` to `None` (the sentinels).
  3. Add a module-level `_resolve_arms(args)`:
```python
def _resolve_arms(args):
    """Resolve requested (match_arm, localize) from flags + the labs profile. Explicit flags win; the labs
    profile only fills a left-at-default (None) flag. Returns (match_arm, localize, profile)."""
    import os
    labs = args.profile == "labs" or bool(os.environ.get("KLOOP_LABS", "").strip())
    match_arm = args.match_arm if args.match_arm is not None else ("routing" if labs else "component")
    localize = args.localize if args.localize is not None else ("semantic" if labs else "atlas")
    return match_arm, localize, ("labs" if labs else "core")
```
  4. At the top of the run handler, replace direct `args.match_arm`/`args.localize` reads with the resolved
     values: `arm_req, localize_req, profile = _resolve_arms(args)`, and set `localize_explicit =
     args.localize is not None`. Update ALL the arm branches + the localize block (Tasks 2-4) to use `arm_req`
     / `localize_req` instead of `args.match_arm` / `args.localize`, and the honest-recording var
     `match_arm = arm_req` (still overwritten to `"flood"` on fallback).
  5. In the localize block (Task 4), change the semantic fail-closed to degrade-under-labs:
```python
            if localize_req == "semantic" and arm_req != "semantic":
                emb = _build_embedder()
                if emb is None:
                    if localize_explicit:
                        print("gloop run --localize semantic: no embedder — set KLOOP_EMBED_BASE_URL.")
                        return 2
                    print("gloop run (labs): --localize semantic wanted but no embedder — falling back to "
                          "atlas FTS5 localize. Set KLOOP_EMBED_BASE_URL to engage semantic localize.")
                    localize_req = "atlas"
                else:
                    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                    from groundloop.adapters.index.split import SplitIndex
                    index = SplitIndex(index, SemanticAtlasIndex(args.index_db, emb))
```
  6. `run/manifest.py`: add `profile: str = "core"` and `localize: str = "atlas"` params to `write_manifest`
     and to the manifest dict. Thread `profile=profile, localize=localize_req` from the CLI `write_manifest(...)`
     call (localize_req = the value that actually ran, post-degrade).

- [ ] **Step 4 — run** `tests/run/ tests/test_cli.py` PASS; full suite green; ruff clean.
- [ ] **Step 5 — commit** `git add groundloop/cli/__init__.py groundloop/run/manifest.py tests/run/test_labs_profile.py && git commit -m "feat(run): --profile labs / KLOOP_LABS flips defaults to the experimental stack (explicit flags win)"`

---

## Task 6: Governance docs + the defaults-unchanged regression test

**Why:** record that the arms are now run-reachable Candidates (blocker → a `[production]` read) and register
`KLOOP_LABS`/`SplitIndex`; assert the Core defaults are unchanged with the profile unset.

**Files:** `docs/capabilities.md`, `docs/workflows.md`, `docs/guide.md`; Test
`tests/run/test_core_defaults_unchanged.py` (new).

- [ ] **Step 1 — failing test** `tests/run/test_core_defaults_unchanged.py`:
```python
def test_core_defaults_unchanged_without_labs(monkeypatch):
    monkeypatch.delenv("KLOOP_LABS", raising=False)
    from groundloop.cli import build_parser, _resolve_arms
    args = build_parser().parse_args(["run","--dataset","d","--catalog","c","--work","w",
                                      "--changes","ch","--index-db","a.db","--out","o","--repos","r"])
    assert _resolve_arms(args) == ("component", "atlas", "core")   # Core defaults, profile off
    assert args.fixer == "plan"                                     # Provisional-Core fix default (unchanged)
```
  Run → FAIL if `_resolve_arms` isn't importable / defaults drifted. (It should PASS once Task 5 landed — this
  task's test is a governance guard; if it already passes, that's the point. Still add it as the regression
  lock.)

- [ ] **Step 2 — run** (expect PASS given Task 5; if it fails, the defaults drifted — fix before docs).

- [ ] **Step 3 — docs (targeted edits):**
  - `docs/capabilities.md`: in the Candidate list + wherever the feature-map-style blockers live, change the
    experimental arms' blocker from "wire into run + `[production]`" to "a `[production]` read (now
    run-reachable)". Add `KLOOP_LABS`/`--profile labs` + `SplitIndex` to the **Core** production-surface
    section as a per-environment switch (like `KLOOP_DEV`), explicitly noting: **it changes defaults only
    where enabled; real production (unset) is Core-identical**, and the §4 CI check asserts defaults with
    `KLOOP_LABS` unset.
  - `docs/workflows.md`: in the **Per-stage feature map**, change the `functional`/`dispatch`/`semantic`/
    `judge` match rows + the `semantic` localize row's **Reachable via** to `gloop run --match-arm <x>` /
    `--localize semantic` and their **Blocker → Core** to "a `[production]` read"; add `SplitIndex` (Core) +
    the `KLOOP_LABS` switch to the cross-cutting guards/infra note. In the Production checklist, add a
    one-line "labs test runs: `KLOOP_LABS=1` (or `--profile labs`) flips to the experimental stack; the
    manifest records `profile`/`localize`" note — and reiterate real production leaves it unset.
  - `docs/guide.md` §5: add the new `--match-arm` choices + `--localize` + `--profile labs` to the run
    surface (one paragraph); note the creds/artifact each experimental arm needs.

- [ ] **Step 4 — run** full suite green; ruff clean.
- [ ] **Step 5 — commit** `git add docs/capabilities.md docs/workflows.md docs/guide.md tests/run/test_core_defaults_unchanged.py && git commit -m "docs+test: register labs arms as run-reachable Candidates + KLOOP_LABS; lock Core defaults"`

---

## Final acceptance

1. Full suite green + ruff clean.
2. `gloop run --match-arm {semantic,judge,functional,dispatch}` and `--localize semantic` all build the right
   index+extractor (mirroring eval/funceval), fail-closed on missing creds/artifact when explicit.
3. `SplitIndex` composes match+localize; `--localize semantic` engages it.
4. `--profile labs` / `KLOOP_LABS=1` → defaults become routing+semantic+plan; explicit flags override; the
   labs-defaulted semantic localize degrades to atlas (loud) without an embedder; manifest records
   `profile`/`localize`.
5. **With `KLOOP_LABS` unset the run defaults are still `component`/`atlas`/`plan`** (the regression lock).
6. No `core/`/schema edit; docs + capabilities/workflows consistent.

Then `superpowers:finishing-a-development-branch`.
