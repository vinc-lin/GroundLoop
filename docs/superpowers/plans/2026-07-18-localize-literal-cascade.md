# Localize literal-anchor cascade (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a recall-first localize cascade that unions three grounded query sources — crash code-tokens,
**literal anchors from the ticket prose**, and a semantic bge-m3 fallback — via RRF, so the oracle file lands
in the candidate set for functional tickets where pool-widening failed.

**Architecture:** One new `CodeIndex` adapter (`adapters/index/cascade_localize.py`, opt-in `--localize
cascade`) built on the stateful signal-stash pattern of `signal_query.py`. Its `retrieve` runs each tier over
the existing atlas, RRF-fuses the ranked **file lists** (`engines/atlas/retrieve.py::rrf_fuse`), and is
**non-regressive** (falls back to the FTS floor when no tier fires — never worse than `--localize atlas`). The
literal tier is a new domain-pack extractor (`domains/android_ivi/anchors.py`) with a **rarity gate** over the
atlas (drop over-matching tokens like `log`; keep rare ones like `PNG`). Zero `core/` / atlas-schema edits;
`Signals` is frozen, so anchors are derived at localize time from the query prose, not added as a field.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check
groundloop tests` (line 110). SQLite/FTS5 + bge-m3.

**Scope note:** Phase 2 of `docs/superpowers/specs/2026-07-17-localize-recall-cascade-design.md` (§3.2–3.3).
Phase 1 (vector-lane hardening + `KLOOP_INDEX_CAMELCASE`) is already merged. The **soft gate** (§3.4), the
**benchmark re-point / true localize-abstain** (§3.5), and any **cascade→judge** integration are OUT OF SCOPE
here — the cascade is pure recall candidate-gen (precision stays with the judge/fixer downstream).

**Reuse (do not rebuild):** `rrf_fuse` (`engines/atlas/retrieve.py:4`), `AtlasIndex.retrieve` /
`Store.keyword_search` (FTS tier), `SemanticAtlasIndex.retrieve` (`adapters/index/atlas_semantic.py:50`,
vector tier), `code_query`/`prose_query` (`domains/android_ivi/functional_signals.py`), the stash+`note_signals`
shape (`adapters/index/signal_query.py`), `SplitIndex` (`adapters/index/split.py`).

---

## File Structure

- **Create** `groundloop/domains/android_ivi/anchors.py` — `extract_anchor_candidates(text) -> list[str]`
  (shape-based literal candidates minus a stoplist) + `rare_anchors(candidates, store, repo, *, max_files,
  max_anchors) -> list[str]` (atlas rarity gate). One responsibility: turn ticket prose into a few
  high-value literal FTS queries.
- **Create** `groundloop/adapters/index/cascade_localize.py` — `CascadeLocalizeIndex` (the RRF-union CodeIndex).
- **Modify** `groundloop/cli/__init__.py` — a `cascade` choice in the `--localize` arg + the elif branch.
- **Modify** `groundloop/run/grade_run.py` — `_localize_index_for` builds the same cascade for the isolated diagnostic.
- **Test** `tests/domains/test_anchors.py`, `tests/adapters/test_cascade_localize.py`,
  `tests/run/test_localize_cascade_wiring.py` (place under the existing test layout; mirror a sibling's fixtures).

---

### Task 1: Literal-anchor candidate extractor

**Files:** Create `groundloop/domains/android_ivi/anchors.py`; Test `tests/domains/test_anchors.py`.

- [ ] **Step 1: Write the failing test.**

```python
# tests/domains/test_anchors.py
from groundloop.domains.android_ivi.anchors import extract_anchor_candidates


def test_extracts_quoted_and_extension_and_camelcase():
    text = 'System screenshots have the extension JPG instead of PNG in ScreenshotUtils'
    got = extract_anchor_candidates(text)
    assert "JPG" in got and "PNG" in got            # ALL-CAPS extension tokens
    assert "ScreenshotUtils" in got                 # CamelCase identifier in prose
    assert "screenshots" not in got                 # a plain lowercase english word is not an anchor


def test_quoted_spans_and_backticks():
    got = extract_anchor_candidates('the label reads "Border Crossing" not `BorderCrossingService`')
    assert "Border Crossing" in got                 # quoted phrase kept as a phrase
    assert "BorderCrossingService" in got           # backtick code span


def test_stoplist_and_dedup():
    got = extract_anchor_candidates("the App fails when the ERROR is shown and the App logs ERROR")
    assert "App" not in got and "the" not in got    # common words stoplisted
    assert got.count("ERROR") <= 1                   # deduped
```

- [ ] **Step 2: Run it, verify FAIL** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `extract_anchor_candidates`.** Extract, in prose order, deduped: (a) quoted spans
`"..."`/`'...'` (inner phrase); (b) backtick code spans `` `...` ``; (c) CamelCase identifiers (`\b[A-Za-z]+[A-Z]\w*\b`
with an internal capital, e.g. `ScreenshotUtils`, `mDNS`); (d) ALL-CAPS / extension tokens (`\b[A-Z]{2,5}\b`,
e.g. `JPG`, `PNG`, `HTTP`); (e) dotted/snake identifiers (`\b\w+[._]\w[\w._]*\b`, e.g. `R.id.foo`,
`audio_focus`). Drop any candidate whose lowercase is in a `_STOPLIST` of common english + code words
(the, a, is, when, fails, error, app, log, file, value, null, true, false, …) — but keep it if it survived via
a quote/backtick (an explicit anchor). Dedup case-insensitively, preserve first original casing (FTS is
case-insensitive but readable output helps). Keep phrases (quoted multi-word) intact.

```python
# groundloop/domains/android_ivi/anchors.py  (skeleton — fill the regexes/stoplist to satisfy the tests)
from __future__ import annotations
import re

_QUOTED = re.compile(r'"([^"]{2,60})"|\'([^\']{2,60})\'')
_BACKTICK = re.compile(r'`([^`]{2,60})`')
_CAMEL = re.compile(r'\b[A-Za-z]*[a-z][A-Z]\w*\b|\b[A-Z]{2,}[a-z]\w*\b')
_ALLCAPS = re.compile(r'\b[A-Z]{2,5}\b')
_DOTTED = re.compile(r'\b\w+[._]\w[\w._]*\b')
_STOPLIST = {"the","a","an","is","are","when","then","fails","fail","error","app","log","logs","file",
             "value","null","true","false","should","not","instead","of","in","and","the","this","that"}

def extract_anchor_candidates(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    def add(s: str, forced: bool = False) -> None:
        s = s.strip()
        key = s.lower()
        if not s or key in seen: return
        if not forced and key in _STOPLIST: return
        seen.add(key); out.append(s)
    for m in _QUOTED.finditer(text): add(m.group(1) or m.group(2), forced=True)
    for m in _BACKTICK.finditer(text): add(m.group(1), forced=True)
    for rx in (_CAMEL, _DOTTED, _ALLCAPS):
        for m in rx.finditer(text): add(m.group(0))
    return out
```

- [ ] **Step 4: Run test → PASS.** Iterate the regexes/stoplist until all three tests pass.

- [ ] **Step 5: ruff** `.venv/bin/ruff check groundloop/domains/android_ivi/anchors.py`.

- [ ] **Step 6: Commit** `feat(localize): literal-anchor candidate extractor (android_ivi)`.

---

### Task 2: Atlas rarity gate (drop over-matching anchors)

**Files:** Modify `groundloop/domains/android_ivi/anchors.py` (+ `rare_anchors`); Test `tests/domains/test_anchors.py`.

- [ ] **Step 1: Write the failing test** using a stub store that returns a controllable hit count per query.

```python
# add to tests/domains/test_anchors.py
from groundloop.domains.android_ivi.anchors import rare_anchors


class _StubStore:
    """keyword_search returns N (Unit-like, rank) rows keyed by query -> distinct file count."""
    def __init__(self, hits_by_q): self._h = hits_by_q
    def keyword_search(self, q, k=20, repos=None, kinds=None):
        n = self._h.get(q, 0)
        return [(type("U", (), {"file": f"f{i}.kt"})(), i) for i in range(min(n, k))]


def test_rarity_gate_drops_overmatching_keeps_rare():
    store = _StubStore({"PNG": 3, "log": 500, "ScreenshotUtils": 1, "missing": 0})
    got = rare_anchors(["log", "PNG", "ScreenshotUtils", "missing"], store, "r",
                       max_files=40, max_anchors=6)
    assert "PNG" in got and "ScreenshotUtils" in got   # rare -> kept
    assert "log" not in got                             # over-matches (>40) -> dropped
    assert "missing" not in got                         # zero hits -> dropped (nothing to anchor)
    assert got == sorted(got, key=lambda a: {"ScreenshotUtils":1,"PNG":3}[a])  # rarest first
```

- [ ] **Step 2: Run it, verify FAIL.**

- [ ] **Step 3: Implement `rare_anchors`.** For each candidate, count distinct files hit via
`store.keyword_search(cand, k=max_files + 1, repos=[repo], kinds=["symbol"])` (count distinct `unit.file`);
keep candidates with `1 <= hits <= max_files`; sort ascending by hit count (rarest first); return the first
`max_anchors`.

```python
def rare_anchors(candidates, store, repo, *, max_files: int = 40, max_anchors: int = 6) -> list[str]:
    scored: list[tuple[int, str]] = []
    for c in candidates:
        try:
            rows = store.keyword_search(c, k=max_files + 1, repos=[repo], kinds=["symbol"])
        except Exception:      # noqa: BLE001 — a bad anchor must never sink localize
            continue
        n = len({getattr(u, "file", None) for u, _ in rows if getattr(u, "file", None)})
        if 1 <= n <= max_files:
            scored.append((n, c))
    scored.sort(key=lambda t: t[0])
    return [c for _n, c in scored[:max_anchors]]
```

- [ ] **Step 4: Run test → PASS.** **Step 5: ruff. Step 6: Commit** `feat(localize): atlas rarity gate for literal anchors`.

---

### Task 3: The cascade adapter (RRF union, non-regressive)

**Files:** Create `groundloop/adapters/index/cascade_localize.py`; Test `tests/adapters/test_cascade_localize.py`.

- [ ] **Step 1: Write the failing test** with a stub FTS index + stub semantic index whose `retrieve` return
distinct ranked lists, and assert the cascade RRF-fuses them (a file appearing in two tiers ranks above one in
a single tier), stashes signals, and falls back to the floor when nothing fires.

```python
# tests/adapters/test_cascade_localize.py
from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
from groundloop.core.types import RepoRef, Signals


class _StubIdx:
    def __init__(self, by_query): self._q = by_query
    def rank_repos(self, s, c): return []
    def retrieve(self, repo, query): return list(self._q.get(query, []))


def _sig(code=()):  # code tokens present -> crash tier fires
    return Signals(classes=tuple(code))


def test_rrf_union_ranks_shared_file_first(monkeypatch):
    # crash tier (code_query) -> [A, B]; literal tier (anchor 'PNG') -> [B, C]; B shared -> rank 1
    fts = _StubIdx({"FooCrash": ["A.kt", "B.kt"], "PNG": ["B.kt", "C.kt"]})
    idx = CascadeLocalizeIndex(match=_StubIdx({}), fts=fts, semantic=None,
                               anchors_fn=lambda text, store, repo: ["PNG"], store=object())
    idx.note_signals(_sig(("FooCrash",)))   # code_query -> "FooCrash"
    out = idx.retrieve(RepoRef("r"), "screenshots are PNG")
    assert out[0] == "B.kt"                  # shared across two tiers -> RRF top
    assert set(out) == {"A.kt", "B.kt", "C.kt"}


def test_non_regressive_floor_when_no_tier_fires():
    fts = _StubIdx({"just prose": ["X.kt"]})
    idx = CascadeLocalizeIndex(match=_StubIdx({}), fts=fts, semantic=None,
                               anchors_fn=lambda text, store, repo: [], store=object())
    idx.note_signals(Signals())              # no code tokens, no anchors, no embedder
    assert idx.retrieve(RepoRef("r"), "just prose") == ["X.kt"]   # == the FTS floor, never []
```

- [ ] **Step 2: Run it, verify FAIL.**

- [ ] **Step 3: Implement `CascadeLocalizeIndex`.** Inject the FTS index (`AtlasIndex`), an optional semantic
index (`SemanticAtlasIndex` or None), an `anchors_fn` (default: `rare_anchors ∘ extract_anchor_candidates`),
and the `store` (for the rarity gate). Stash signals in `rank_repos`/`note_signals` (the `signal_query`
pattern). `retrieve` collects a ranked `list[str]` from each tier that fires, `rrf_fuse`es them, caps at `k`;
if NO tier fires, return the FTS floor on the prose query (non-regressive).

```python
# groundloop/adapters/index/cascade_localize.py
from __future__ import annotations
from typing import Optional, Sequence
from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.anchors import extract_anchor_candidates, rare_anchors
from groundloop.domains.android_ivi.functional_signals import code_query
from groundloop.engines.atlas.retrieve import rrf_fuse


def _default_anchors(text, store, repo):
    return rare_anchors(extract_anchor_candidates(text), store, repo)


class CascadeLocalizeIndex:
    """Recall-first localize: RRF-union of crash code-tokens (FTS), literal anchors (FTS), and an optional
    bge-m3 semantic fallback. Non-regressive: falls back to the FTS floor when no tier fires. Stash pattern
    (signal_query.py); no core/ or schema edit; opt-in Candidate."""
    def __init__(self, match, *, fts, semantic=None, store, anchors_fn=_default_anchors, k: int = 20):
        self._match = match
        self._fts = fts                 # AtlasIndex (FTS tier)
        self._semantic = semantic       # SemanticAtlasIndex | None
        self._store = store
        self._anchors_fn = anchors_fn
        self.k = k
        self._last_signals: Optional[Signals] = None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def note_signals(self, signals: Signals) -> None:
        self._last_signals = signals

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        lists: list[list[str]] = []
        cq = code_query(self._last_signals) if self._last_signals is not None else ""
        if cq:
            lists.append(self._fts.retrieve(repo, cq))                 # crash tier
        for a in self._anchors_fn(query, self._store, repo.name):
            lists.append(self._fts.retrieve(repo, a))                  # literal tier (one query per anchor)
        if self._semantic is not None:
            lists.append(self._semantic.retrieve(repo, query))         # semantic fallback
        lists = [x for x in lists if x]
        if not lists:
            return self._fts.retrieve(repo, query)                     # non-regressive floor
        return [f for f, _ in rrf_fuse(lists)][: self.k]
```

- [ ] **Step 4: Run test → PASS.** **Step 5: ruff. Step 6: Commit** `feat(localize): CascadeLocalizeIndex — RRF union of crash/literal/semantic tiers`.

---

### Task 4: Composition-root wiring (`--localize cascade`)

**Files:** Modify `groundloop/cli/__init__.py`; Modify `groundloop/run/grade_run.py`; Test
`tests/run/test_localize_cascade_wiring.py`.

- [ ] **Step 1: Write the failing test.** `gloop run --localize cascade` must wrap the match index in a
`SplitIndex` over a `CascadeLocalizeIndex`; the semantic tier is included ONLY when an embedder is available
(no hard fail — the cascade degrades to crash+literal FTS without one, unlike `rerank`). Mirror the wiring
test added in Phase 1 (`tests/run/test_localize_rerank_failfast.py`).

```python
# tests/run/test_localize_cascade_wiring.py
def test_localize_cascade_wraps_split_over_cascade(monkeypatch):
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: None)  # no embedder -> still builds (FTS tiers)
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset", lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.cli import main
    try:
        main(["run","--dataset","d","--catalog","c","--work","w","--changes","ch","--index-db","a.db",
              "--out","o","--repos","r","--fixer","canned","--match-arm","flood","--localize","cascade"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex) and isinstance(idx._localize, CascadeLocalizeIndex)
```

- [ ] **Step 2: Run it, verify FAIL** (`cascade` not a valid `--localize` choice yet).

- [ ] **Step 3: Implement.** Add `"cascade"` to the `--localize` arg choices. Add an `elif localize_req ==
"cascade":` branch that builds `CascadeLocalizeIndex(match=index, fts=AtlasIndex(args.index_db),
semantic=SemanticAtlasIndex(args.index_db, emb) if emb else None, store=Store(args.index_db))` and wraps it
`SplitIndex(index, cascade)` — where `emb = _build_embedder()` (None is allowed; the cascade degrades). Add the
matching `arm == "cascade"` branch in `grade_run._localize_index_for` so the isolated diagnostic reconstructs
the same cascade (semantic tier only if the passed embedder is non-None). Import at the composition root only.

- [ ] **Step 4: Run test → PASS.**

- [ ] **Step 5: Core defaults unchanged.** `.venv/bin/python -m pytest tests/run/test_core_defaults_unchanged.py -q`
— PASS (default localize unchanged; `cascade` is opt-in).

- [ ] **Step 6: Commit** `feat(localize): wire --localize cascade at the composition root (opt-in Candidate)`.

---

### Task 5: Gate — full suite + ruff + invariants

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` — all green.
- [ ] **Step 2:** `.venv/bin/ruff check groundloop tests` — clean.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/test_invariants.py tests/run/test_core_defaults_unchanged.py -q` — PASS.
- [ ] **Step 4:** Only after green+clean are the code tasks complete.

---

## Live runbook (orchestrator, NOT a subagent task) — the `[proxy]` ablation

The whole point is the literal tier's **marginal** recall contribution, split by regime, on the CamelCase
atlas (the literal tier needs A3 to match compound symbol names). Run off ext4, `.env` sourced.

1. Build a CamelCase 6-repo `[proxy]` atlas once: `KLOOP_INDEX_CAMELCASE=1 gloop index --registry <6-repo.toml>`
   into a fresh DB (leave the baseline atlas untouched).
2. Extend the isolated localize harness (the prior `localize_ab.py` shape) with a `cascade` arm and run, split
   by `bug_kind` (crash-synth slice + functional `mine74`), on BOTH the baseline and CamelCase atlases:
   arms = `atlas` (floor) · `cascade_no_literal` (crash+semantic only) · `cascade` (+literal) · `rerank` (judge).
   Report recall@1/3/5. The decisive read: **`cascade` − `cascade_no_literal`** on the functional split
   (does the literal anchor add the missing oracle files?) and `cascade` vs `atlas` overall (non-regression).
3. **Match-regression check** on the CamelCase atlas (A3 changes the shared atlas) — deferred-from-Phase-1, do
   it here before the atlas is trusted.
4. Log to `docs/results-log.md`, `[proxy]`-tagged, with atlas identity + which arms fired the literal tier.

**Verification of the plan:** anchors extract the right literals and the rarity gate drops `log`-like noise;
the cascade RRF-fuses tiers and never returns worse than the FTS floor; `--localize cascade` is reachable +
opt-in + Core-default-safe; suite green + ruff clean; and the `[proxy]` ablation shows the literal tier's
marginal recall (or honestly shows it doesn't help — then the design's semantic-fallback assumption is what
carries functional recall). The `[production]` GEI read remains the Candidate→Core gate.

---

## Self-review notes

- **Spec coverage (§3.2–3.3):** Task 1–2 = literal-anchor tier + rarity gate; Task 3 = RRF cascade + tiers +
  non-regressive floor; Task 4 = wiring. Abstain (§3.3) intentionally deferred (needs the §3.5 benchmark
  re-point plumbing) — stated in Scope note; the cascade is non-regressive instead.
- **Type consistency:** every tier `retrieve(repo, query) -> list[str]`; `rrf_fuse(list[list[str]]) ->
  list[tuple[str,float]]`; `extract_anchor_candidates(str)->list[str]`; `rare_anchors(list,store,repo,*,...)
  ->list[str]`; `anchors_fn(text, store, repo_name)->list[str]` (note: `repo.name` is passed).
- **No placeholders:** every code step has real code or an exact command. The regex/stoplist in Task 1 is a
  skeleton the implementer tunes against the three provided tests (the tests are the contract).
- **Grounding:** anchors and tier outputs are real atlas files; the rarity gate is a real FTS count; no
  fabricated paths. RRF keeps the union non-regressive.
