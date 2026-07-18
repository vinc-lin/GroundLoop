# Cascade → judge (recall pool + precision rerank) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rerank the *cascade's* higher-recall candidate pool with the grounded LLM file-judge, combining the
two things the `[proxy]` data shows actually work — the cascade wins recall@5 (0.308 vs the reranker's own pool
0.267) and the judge wins file@1 (0.212) — into a `--localize cascade_judge` arm.

**Architecture:** Additive, maximal-reuse. Add an optional `pool_index` seam to the existing (tested)
`RerankLocalizeIndex`: when set, the reranker draws its candidate POOL from the injected `CodeIndex`
(the cascade) instead of its own `_gen_hits`, and retains a **doc lane** so the existing CodeWiki-context path
(doc→source rewrite + wiki summary) still feeds the judge. Default `pool_index=None` ⇒ the current `--localize
rerank` behavior is byte-for-byte unchanged. Wire a `--localize cascade_judge` arm at the composition root that
injects a `CascadeLocalizeIndex` as the pool source. Zero `core/` / atlas-schema edits; opt-in Candidate.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check
groundloop tests` (line 110). SQLite/FTS5 + bge-m3 + the gateway LLM judge.

**Why this over pushing the literal tier:** the 2026-07-18 `[proxy]` read showed the literal anchor is marginal
and the semantic tier is the recall lever; the biggest single lever remains the judge (0.212). The cascade's
pool already out-recalls the reranker's own pool, so the highest-EV next step is to hand that better pool to the
judge — not to tune anchors. (`docs/results-log.md` 2026-07-18.)

**Scope note:** This is the cascade→judge integration scoped OUT of the Phase-2 plan
(`docs/superpowers/plans/2026-07-18-localize-literal-cascade.md`). The soft-gate (§3.4 of the cascade spec), the
benchmark re-point, and the CamelCase-atlas / `[production]` reads remain separate.

**Reuse (do not rebuild):** `RerankLocalizeIndex` (`adapters/index/rerank_localize.py`) — its `_build_pool`,
`_context_for`, `_ground`, and `GatewayFileJudge`; `CascadeLocalizeIndex` (`adapters/index/cascade_localize.py`);
`_build_rerank_localize` + `_entity_map_provider`/`_source_reader`/`_cbm_provider` (`cli/__init__.py`);
`SemanticAtlasIndex`, `AtlasIndex`, `Store`, `SplitIndex`.

---

## File Structure

- **Modify** `groundloop/adapters/index/rerank_localize.py` — add the `pool_index` seam (`__init__` param +
  a `_pool_index_hits` path in `_retrieve` + a `_doc_hits` doc lane). Additive; default None = unchanged.
- **Modify** `groundloop/cli/__init__.py` — add `"cascade_judge"` to `--localize` choices; a `cascade_judge`
  branch that builds a `CascadeLocalizeIndex` and passes it as `pool_index` to `_build_rerank_localize`
  (add a `pool_index=None` param to that helper).
- **Modify** `groundloop/run/grade_run.py` — an `arm == "cascade_judge"` branch mirroring the live wiring.
- **Test** `tests/adapters/test_rerank_pool_index.py`, `tests/run/test_localize_cascade_judge_wiring.py`.

---

### Task 1: `pool_index` seam on RerankLocalizeIndex

**Files:** Modify `groundloop/adapters/index/rerank_localize.py`; Test `tests/adapters/test_rerank_pool_index.py`.

Reference the current code (read it first): `_retrieve` (~lines 142-159) computes `query_str = code_query(...)
or query`, then `hits = self._gen_hits(repo.name, query_str)`, then `_build_pool(hits, em)` → judge → `_ground`.
`_keyword_hits` (~176-186) maps `store.keyword_search(...)` rows to hit dicts `{"kind","file",
"qualified_name","snippet","meta"}`.

- [ ] **Step 1: Write the failing test.** With a `pool_index` injected (a stub whose `retrieve` returns a fixed
file list) and a `StubFileJudge`, the reranker's pool must come from the pool_index's files (reordered by the
judge, grounded to the pool). Also assert `note_signals` is forwarded to the pool_index, and that with
`pool_index=None` the existing behavior is untouched.

```python
# tests/adapters/test_rerank_pool_index.py
from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex, StubFileJudge
from groundloop.core.types import RepoRef, Signals


class _StubPool:
    def __init__(self, files):
        self._files = files
        self.noted = None
    def note_signals(self, s):
        self.noted = s
    def retrieve(self, repo, query):
        return list(self._files)


class _StubStore:
    def keyword_search(self, q, k=20, repos=None, kinds=None):
        return []          # no doc hits -> pool is exactly the pool_index files


def _match():
    class M:
        def rank_repos(self, s, c):
            return []
    return M()


def test_pool_comes_from_injected_pool_index_and_judge_reorders():
    pool = _StubPool(["A.kt", "B.kt", "C.kt"])
    judge = StubFileJudge(order=["C.kt", "A.kt", "B.kt"])     # judge reorders the pool
    idx = RerankLocalizeIndex(_match(), store=_StubStore(), embedder=None, judge=judge,
                              pool_index=pool)
    idx.note_signals(Signals(classes=("Foo",)))
    out = idx.retrieve(RepoRef("r"), "some prose ticket")
    assert out[0] == "C.kt"                       # judge order, grounded to the pool
    assert set(out) == {"A.kt", "B.kt", "C.kt"}   # pool = the pool_index files
    assert pool.noted == Signals(classes=("Foo",))  # signals forwarded to the pool source
    assert idx.retrieve(RepoRef("r"), "some prose ticket")  # idempotent, no crash
```

- [ ] **Step 2: Run it, verify FAIL** (`pool_index` is not a param yet).

- [ ] **Step 3: Implement the seam.** In `__init__`, add `pool_index=None` (store `self._pool_index =
pool_index`). In `_retrieve`, branch the hit source:

```python
    def _retrieve(self, repo: RepoRef, query: str) -> list[str]:
        q = code_query(self._last_signals) if self._last_signals is not None else ""
        query_str = q or query
        if self._pool_index is not None:
            hits = self._pool_index_hits(repo, query, query_str)
        else:
            hits = self._gen_hits(repo.name, query_str)
        em = self._entity_map_for(repo.name)
        pool, qns_by_file, snip_by_file, wiki_by_file = self._build_pool(hits, em)
        # ... rest unchanged (pool empty -> fallback; judge None/len<=1 -> pool; else context+rerank+ground)
```

Add the two helpers:

```python
    def _pool_index_hits(self, repo: RepoRef, query: str, query_str: str) -> list[dict]:
        """Recall pool from the injected CodeIndex (e.g. the cascade) as symbol hits, PLUS a doc lane so
        _build_pool can rewrite doc units -> source and stash CodeWiki summaries for the judge context.
        The injected index gets the PROSE query + the stashed signals (it runs its own code_query/anchors);
        symbol hits are listed FIRST so the pool cap keeps the recall candidates over doc-rewritten ones."""
        if hasattr(self._pool_index, "note_signals"):
            self._pool_index.note_signals(self._last_signals)
        try:
            files = list(self._pool_index.retrieve(repo, query))
        except Exception:      # noqa: BLE001 — a pool-source failure degrades to the doc lane, never sinks localize
            files = []
        sym = [{"kind": "symbol", "file": f, "qualified_name": "", "snippet": "", "meta": {}} for f in files]
        return sym + self._doc_hits(repo.name, query_str)

    def _doc_hits(self, repo_name: str, query_str: str) -> list[dict]:
        hits: list[dict] = []
        try:
            rows = self.store.keyword_search(query_str, k=self.k, repos=[repo_name], kinds=["doc"])
        except Exception:      # noqa: BLE001
            return hits
        for u, _rank in rows:
            hits.append({"kind": u.kind, "file": u.file, "qualified_name": u.qualified_name,
                         "snippet": (u.text or "")[:400], "meta": u.meta or {}})
        return hits
```

- [ ] **Step 4: Run test → PASS.** Also run the EXISTING reranker tests to prove the default path is unchanged:
`.venv/bin/python -m pytest tests/ -q -k "rerank"` — all green (pool_index defaults None → the `else` branch).

- [ ] **Step 5: ruff.** **Step 6: Commit** `feat(localize): pool_index seam on RerankLocalizeIndex (recall pool + doc lane)`.

---

### Task 2: Wire `--localize cascade_judge`

**Files:** Modify `groundloop/cli/__init__.py` (choices + `_build_rerank_localize` `pool_index` param + the
branch), `groundloop/run/grade_run.py`; Test `tests/run/test_localize_cascade_judge_wiring.py`.

- [ ] **Step 1: Write the failing test** (mirror `tests/run/test_localize_cascade_wiring.py`). With an embedder
present, `gloop run --localize cascade_judge` builds a `SplitIndex` over a `RerankLocalizeIndex` whose
`_pool_index` is a `CascadeLocalizeIndex`. With no embedder it STILL builds (cascade degrades; judge is
creds-gated, not embedder-gated) — assert it does not `return 2`.

```python
# tests/run/test_localize_cascade_judge_wiring.py
def test_cascade_judge_wraps_rerank_over_cascade_pool(monkeypatch, tmp_path):
    monkeypatch.setattr("groundloop.cli._build_embedder", lambda: None)  # cascade degrades; no fail-fast
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)           # judge=None is fine for wiring
    seen = {}
    import groundloop.run.batch as batch
    monkeypatch.setattr(batch, "run_dataset",
                        lambda dataset, **kw: (seen.__setitem__("index", kw.get("index")) or 0))
    from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex
    from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.cli import main
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned",
              "--match-arm", "flood", "--localize", "cascade_judge"])
    except Exception:
        pass
    idx = seen.get("index")
    assert isinstance(idx, SplitIndex)
    assert isinstance(idx._localize, RerankLocalizeIndex)
    assert isinstance(idx._localize._pool_index, CascadeLocalizeIndex)
```

- [ ] **Step 2: Run it, verify FAIL** (`cascade_judge` not a valid choice).

- [ ] **Step 3: Implement.**
  - Add `"cascade_judge"` to the `--localize` argparse `choices` (+ a help clause).
  - Add a `pool_index=None` param to `_build_rerank_localize(match_index, args, embedder, pool_index=None)` and
    pass it through to the `RerankLocalizeIndex(...)` construction (`pool_index=pool_index`).
  - Add the branch in `cli.main` (after `cascade`), NO fail-fast on a missing embedder:
    ```python
    elif localize_req == "cascade_judge":
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
        from groundloop.adapters.index.split import SplitIndex
        from groundloop.engines.atlas.store import Store
        emb = _build_embedder()
        sem = SemanticAtlasIndex(args.index_db, emb) if emb is not None else None
        cascade = CascadeLocalizeIndex(index, fts=AtlasIndex(args.index_db), semantic=sem,
                                       store=Store(args.index_db))
        rer = _build_rerank_localize(index, args, emb, pool_index=cascade)
        index = SplitIndex(index, rer)
    ```
  - Add the matching `arm == "cascade_judge"` branch in `grade_run._localize_index_for` building the same
    thing (cascade pool_index into a RerankLocalizeIndex), returning `(rer, arm)` in the sibling return shape.
    (Read how the `rerank` branch there builds its `RerankLocalizeIndex` and clone it, adding `pool_index`.)

- [ ] **Step 4: Run test → PASS.**

- [ ] **Step 5: Core defaults unchanged + existing rerank untouched:**
`.venv/bin/python -m pytest tests/run/test_core_defaults_unchanged.py -q` and `-k "rerank or localize"` — PASS.

- [ ] **Step 6: Commit** `feat(localize): wire --localize cascade_judge (cascade pool + LLM judge)`.

---

### Task 3: Gate — full suite + ruff + invariants

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` — all green.
- [ ] **Step 2:** `.venv/bin/ruff check groundloop tests` — clean.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/test_invariants.py tests/run/test_core_defaults_unchanged.py -q` — PASS.

---

## Live runbook (orchestrator, NOT a subagent task) — the `[proxy]` read

The decisive question: does reranking the cascade's higher-recall pool beat the existing judge-over-its-own-pool
(`rerank_cw_judge` = 0.212 file@1)? Needs judge creds (`KLOOP_PRODUCE_API_KEY`) — cost ~$0.0014/case. Off ext4, `.env` sourced.

1. Add a `cascade_judge` arm to the isolated `localize_ab.py` harness: `RerankLocalizeIndex(AtlasIndex(db),
   store=store, embedder=embedder, judge=_judge(), entity_map=em, source_reader=reader,
   pool_index=CascadeLocalizeIndex(AtlasIndex(db), fts=AtlasIndex(db),
   semantic=(SemanticAtlasIndex(db, embedder) if embedder else None), store=store))`.
2. Run, split by regime, on `atlas-6-doc.db` over `mine74`, arms:
   `atlas` · `cascade` (recall, no judge) · `rerank_cw_judge` (judge over its own pool) · `cascade_judge`
   (judge over the cascade pool). Report file@1/3/5 + $/case. The read: **cascade_judge vs rerank_cw_judge**
   (does the better recall pool lift the judged file@1?) and cascade_judge vs cascade (does the judge lift the
   cascade's recall pool?).
3. If cascade_judge wins on the baseline atlas, re-run on the CamelCase atlas for the full literal-tier strength.
4. Log to `docs/results-log.md`, `[proxy]`-tagged.

**Verification:** the pool_index seam is additive (existing `--localize rerank` tests stay green); `cascade_judge`
is reachable + opt-in + Core-default-safe; suite green + ruff clean; and the `[proxy]` read shows whether
cascade-recall + judge beats the current best judged file@1 (or honestly shows it does not — then the cascade's
recall advantage doesn't survive the judge, and the judge's own pool is sufficient). The `[production]` GEI read
+ the CamelCase-atlas read remain the Candidate→Core gate.

---

## Self-review notes

- **Coverage:** Task 1 = the reuse seam (pool source swap + doc lane for wiki); Task 2 = wiring; runbook = the
  ablation that answers "does the cascade pool improve the judged result". The soft-gate / benchmark re-point /
  CamelCase / `[production]` reads are explicitly out of scope (stated).
- **Additivity:** `pool_index=None` default keeps `--localize rerank` byte-identical; Step 4 of Task 1 and Step 5
  of Task 2 both re-run the existing rerank tests to prove it.
- **Type consistency:** `pool_index` is any object with `retrieve(repo, query) -> list[str]` (+ optional
  `note_signals`); `_pool_index_hits`/`_doc_hits` return `list[dict]` in the same hit shape `_build_pool`
  already consumes (`kind/file/qualified_name/snippet/meta`); `_build_rerank_localize(..., pool_index=None)`.
- **Grounding:** the judge still only REORDERS the grounded pool (`_ground`); the pool source is real cascade
  files + real doc units; a pool-source exception degrades to the doc lane, never fabricates.
