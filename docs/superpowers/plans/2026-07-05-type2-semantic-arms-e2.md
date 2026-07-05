# Type-2 Semantic Arms (E2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add the `+semantic` matcher strategy — a `SemanticAtlasIndex` that ranks repos by bge-m3 vector similarity — so the eval gains the two arms that test the core project hypothesis: **does semantic retrieval beat FTS5 membership?**

**Architecture:** Pure edge composition (`core/` frozen). `SemanticAtlasIndex(db, embedder)` implements the same `CodeIndex` protocol as `AtlasIndex` (`rank_repos` + `retrieve`), folding `store.vector_search` cosine hits into per-repo `RepoScore`. It's a drop-in swap at the composition root. The *ranking logic* is hermetically testable with a fake embedder + a real-vector fixture atlas; only the live `GatewayEmbedder` path is network-bound → Type-2 gated. A construction-time **reuse-contract guard** (query-embedder dim must match the indexed vectors) closes the silent `_cosine=-1` corruption risk.

**Tech Stack:** Python 3.12, pytest (hermetic via a fake embedder + a real-vector `Store` fixture; the live arm is `skipif`-gated like `tests/e2e`). Reuses `groundloop.engines.atlas.store.Store` (`vector_search`), `groundloop.engines.atlas.embed.GatewayEmbedder`, and the E1-C `eval` harness.

**Canonical design:** [`docs/type2-evaluation.md`](../../type2-evaluation.md) §6.1 (+semantic arm), §6.3 (gating + reuse-contract guard). Eval stage **E2**; builds on E1-C.

---

## Verified internals

- `store.vector_search(qvec, k=20, repos=None, kinds=None) -> list[(Unit, cosine)]`, sorted desc; `Unit` has `.repo`, `.file`.
- `store._cosine(a, b)` returns `-1.0` if `len(a) != len(b)` or either empty (the mismatch footgun).
- `store.reindex_repo(repo, units_with_vecs, *, repo_head)`; `Unit(repo, kind, name, qualified_name, file, repo_head, text, meta)`.
- `GatewayEmbedder(base_url, api_key, model, ...).embed(texts) -> list[list[float]]` (network).
- `AtlasIndex.rank_repos` (membership) scores by matched-token count; `SemanticAtlasIndex` scores by max cosine per repo.
- `Signals.tokens()` builds the query string.

---

## File Structure

- **Create** `groundloop/adapters/index/atlas_semantic.py` — `SemanticAtlasIndex(db, embedder)`.
- **Modify** `groundloop/eval/arms.py` — `build_arms(*, membership_index, semantic_index=None)` adds semantic arms.
- **Modify** `groundloop/cli/__init__.py` — `gloop eval --semantic` builds `SemanticAtlasIndex(GatewayEmbedder)`.
- **Create** `tests/adapters/test_atlas_semantic.py`, extend `tests/eval/test_arms.py`, `tests/e2e/test_semantic_arm_live.py` (gated).

**Commands:** as before. Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1: `SemanticAtlasIndex` adapter + reuse-contract guard

**Files:** Create `groundloop/adapters/index/atlas_semantic.py`; Test `tests/adapters/__init__.py` (empty, if missing) + `tests/adapters/test_atlas_semantic.py`.

- [ ] **Step 1: Failing test** — `tests/adapters/test_atlas_semantic.py`:

```python
import pytest

from groundloop.engines.atlas.store import Store, Unit
from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
from groundloop.core.types import RepoRef, Signals


class _FakeEmbedder:
    """Returns a fixed query vector regardless of text (controllable for tests)."""
    def __init__(self, vec):
        self._vec = vec

    def embed(self, texts):
        return [list(self._vec) for _ in texts]


def _build_vec_atlas(path):
    """3 repos, one symbol unit each, orthogonal 3-dim vectors."""
    s = Store(path)
    specs = {"repo_a": [1.0, 0.0, 0.0], "repo_b": [0.0, 1.0, 0.0], "repo_c": [0.0, 0.0, 1.0]}
    for repo, vec in specs.items():
        u = Unit(repo=repo, kind="symbol", name="Sym", qualified_name=f"{repo}.Sym",
                 file=f"{repo}/src.ext", repo_head="fix", text="Sym", meta={})
        s.reindex_repo(repo, [(u, vec)], repo_head="fix")
    return path


def test_rank_repos_by_cosine_favours_matching_repo(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))
    # query vector aligned with repo_b -> repo_b should rank first
    idx = SemanticAtlasIndex(db, _FakeEmbedder([0.1, 0.9, 0.0]))
    sig = Signals(classes=("Whatever",))
    ranked = idx.rank_repos(sig, [RepoRef("repo_a"), RepoRef("repo_b"), RepoRef("repo_c")])
    assert ranked[0].repo.name == "repo_b"
    assert ranked[0].score > ranked[1].score


def test_rank_repos_restricts_to_catalog(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))
    idx = SemanticAtlasIndex(db, _FakeEmbedder([1.0, 0.0, 0.0]))
    ranked = idx.rank_repos(Signals(classes=("X",)), [RepoRef("repo_a"), RepoRef("repo_c")])
    assert {r.repo.name for r in ranked} == {"repo_a", "repo_c"}   # repo_b excluded
    assert ranked[0].repo.name == "repo_a"


def test_reuse_contract_guard_rejects_dim_mismatch(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))          # indexed vectors are 3-dim
    with pytest.raises(ValueError, match="(?i)dim"):
        SemanticAtlasIndex(db, _FakeEmbedder([1.0, 0.0]))       # 2-dim query -> mismatch


def test_retrieve_returns_files_for_repo(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))
    idx = SemanticAtlasIndex(db, _FakeEmbedder([1.0, 0.0, 0.0]))
    files = idx.retrieve(RepoRef("repo_a"), "anything")
    assert files == ["repo_a/src.ext"]
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/adapters/index/atlas_semantic.py`:

```python
"""CodeIndex backed by bge-m3 vector similarity over atlas.db (the +semantic arm).

rank_repos = max cosine per repo over store.vector_search hits, restricted to the catalog.
A construction-time guard verifies the query embedder's dim matches the indexed vectors, so a
model/dim mismatch fails loudly instead of silently scoring every repo -1 (docs §6.3 reuse contract).
Network-bound (GatewayEmbedder) -> Type-2/live."""
from __future__ import annotations

from typing import Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.engines.atlas.store import Store


class SemanticAtlasIndex:
    def __init__(self, db_path: str, embedder):
        self.store = Store(db_path)
        self.embedder = embedder
        self._check_dim()

    def _check_dim(self) -> None:
        """Reuse contract: the query embedder must produce the same dim as the indexed vectors."""
        import json
        row = self.store.db.execute("SELECT vec FROM vectors LIMIT 1").fetchone()
        if row is None:
            return                       # empty atlas — nothing to compare (build-time only)
        indexed_dim = len(json.loads(row["vec"]))
        query_dim = len(self.embedder.embed(["dim probe"])[0])
        if query_dim != indexed_dim:
            raise ValueError(
                f"embedder dim {query_dim} != indexed vector dim {indexed_dim} "
                f"(query embed model must equal the index-time bge-m3 — reuse contract)")

    def _query(self, signals: Signals) -> str:
        return " ".join(signals.tokens())

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        allowed = {r.name for r in catalog}
        best: dict[str, float] = {name: 0.0 for name in allowed}
        q = self._query(signals)
        if q.strip():
            qvec = self.embedder.embed([q])[0]
            for unit, cos in self.store.vector_search(qvec, k=50, repos=list(allowed)):
                if unit.repo in best:
                    best[unit.repo] = max(best[unit.repo], cos)
        ranked = [RepoScore(RepoRef(name), float(score)) for name, score in best.items()]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        qvec = self.embedder.embed([query])[0]
        files: list[str] = []
        for unit, _ in self.store.vector_search(qvec, k=20, repos=[repo.name]):
            if unit.file and unit.file not in files:
                files.append(unit.file)
        return files
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): SemanticAtlasIndex (bge-m3 vector arm) + reuse-contract guard`).

*Note for the implementer:* confirm `Store` exposes `.db` with `row["vec"]` access (sqlite Row). If the vectors table/column name differs, read `groundloop/engines/atlas/store.py` and match; keep the guard's behavior (raise on dim mismatch).

---

## Task 2: Semantic arms in the factory

**Files:** Modify `groundloop/eval/arms.py`; extend `tests/eval/test_arms.py`.

- [ ] **Step 1: Failing test** — add to `tests/eval/test_arms.py`:

```python
def test_build_arms_adds_semantic_when_index_given():
    from groundloop.eval.arms import build_arms
    arms = build_arms(membership_index=_FakeIndex(), semantic_index=_FakeIndex())
    names = {a.name for a in arms}
    assert names == {"membership+text", "membership+logs", "semantic+text", "semantic+logs"}


def test_semantic_arms_omitted_by_default():
    from groundloop.eval.arms import build_arms
    arms = build_arms(membership_index=_FakeIndex())
    assert all(not a.name.startswith("semantic") for a in arms)
```

- [ ] **Step 2: Run → fail. Step 3: Implement** — update `build_arms` in `groundloop/eval/arms.py`:

```python
def build_arms(*, membership_index, semantic_index=None) -> list[Arm]:
    arms = [
        Arm("membership+text", membership_index, TextOnlyExtractor()),
        Arm("membership+logs", membership_index, AndroidSignalExtractor()),
    ]
    if semantic_index is not None:
        arms += [
            Arm("semantic+text", semantic_index, TextOnlyExtractor()),
            Arm("semantic+logs", semantic_index, AndroidSignalExtractor()),
        ]
    return arms
```

- [ ] **Step 4: Run → pass** (`tests/eval/test_arms.py` now 4 tests). **Step 5: ruff + commit** (`feat(eval): add semantic arms to the factory`).

---

## Task 3: Wire `gloop eval --semantic` + gated live test

**Files:** Modify `groundloop/cli/__init__.py`; Create `tests/e2e/test_semantic_arm_live.py`.

- [ ] **Step 1: Failing test** — `tests/e2e/test_semantic_arm_live.py` (gated; always collects, skips without creds):

```python
import os
import pytest

_GATE = bool(os.environ.get("KLOOP_EMBED_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_EMBED_API_KEY not set — live semantic arm skipped")
def test_semantic_arm_ranks_over_live_atlas(tmp_path):
    """Live: SemanticAtlasIndex over a real bge-m3 atlas ranks a known repo for a known signal.
    RUNBOOK: needs KLOOP_EMBED_{BASE_URL,API_KEY,MODEL=bge-m3} + a built atlas.db at KLOOP_ATLAS_DB."""
    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
    from groundloop.engines.atlas.embed import GatewayEmbedder
    from groundloop.core.types import RepoRef, Signals

    db = os.environ.get("KLOOP_ATLAS_DB", "")
    if not db or not os.path.isfile(db):
        pytest.skip("KLOOP_ATLAS_DB not a built atlas.db")
    emb = GatewayEmbedder(os.environ["KLOOP_EMBED_BASE_URL"], os.environ["KLOOP_EMBED_API_KEY"],
                          os.environ.get("KLOOP_EMBED_MODEL", "bge-m3"))
    idx = SemanticAtlasIndex(db, emb)              # exercises the dim guard against real vectors
    ranked = idx.rank_repos(Signals(classes=("MediaCodec",), packages=("androidx.media3",)),
                            [RepoRef("media3"), RepoRef("osmand")])
    assert ranked and ranked[0].score >= ranked[-1].score
```

Also add a hermetic CLI-wiring test to `tests/eval/test_cli_eval.py` proving `--semantic` is accepted and (when the embed gateway is absent) fails gracefully rather than crashing — OR simply assert the flag exists:

```python
def test_eval_help_lists_semantic_flag():
    import subprocess, sys
    out = subprocess.run([sys.executable, "-m", "groundloop.cli", "eval", "--help"],
                         capture_output=True, text=True)
    assert "--semantic" in out.stdout
```

- [ ] **Step 2: Run → fail** (the live test skips; the help test fails until the flag is added).

- [ ] **Step 3: Implement** the CLI wiring in `groundloop/cli/__init__.py`. Add to the `eval` subparser:

```python
    ev.add_argument("--semantic", action="store_true",
                    help="add the bge-m3 semantic arms (needs KLOOP_EMBED_* live gateway)")
```

In `_run_eval`, build the optional semantic index before `build_arms`:

```python
    semantic_index = None
    if args.semantic:
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        from groundloop.engines.atlas.embed import GatewayEmbedder
        from groundloop.config.settings import Settings
        st = Settings.load()
        emb = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
        semantic_index = SemanticAtlasIndex(args.index_db, emb)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db),
                                           semantic_index=semantic_index))
```

(Confirm `Settings` exposes `embed_base_url`/`embed_api_key`/`embed_model` — the same fields `_run_index` uses via `GatewayEmbedder(settings.embed_base_url, settings.embed_api_key, settings.embed_model)`.)

- [ ] **Step 4: Run → pass.** Then `.venv/bin/python -m pytest -q` (full suite green; the live test skips), `.venv/bin/ruff check groundloop tests`, `.venv/bin/gloop eval --help` (lists `--semantic`).
- [ ] **Step 5: Commit** (`feat(eval): gloop eval --semantic (bge-m3 arms, gated live)`).

---

## Self-Review

**Spec coverage (`type2-evaluation.md` §6.1/§6.3):** SemanticAtlasIndex folding vector_search into per-repo RepoScore (Task 1) ✓; reuse-contract dim guard closing the `_cosine=-1` silent corruption (Task 1) ✓; the two semantic arms (Task 2) ✓; `gloop eval --semantic` gated on the live gateway (Task 3) ✓; gated Type-2 test (Task 3) ✓. **Deferred (noted):** RRF hybrid (FTS5+semantic fused) as a distinct arm — `engines/atlas/retrieve.py:rrf_fuse` exists; kept out of v1 to keep the A/B clean (membership vs semantic), added once the A/B is settled; embed-cost capture per arm — folds in with the E3 cost work.

**Placeholder scan:** none.

**Type consistency:** `SemanticAtlasIndex.rank_repos(signals, catalog) -> list[RepoScore]` matches the `CodeIndex` protocol `AtlasIndex` implements (so `EvalRunner`/`build_arms` consume it identically); `build_arms(semantic_index=...)` extends the E1-C signature additively (existing callers unaffected — `semantic_index` defaults to `None`); the embedder interface (`.embed(texts) -> list[list[float]]`) matches both the test `_FakeEmbedder` and `GatewayEmbedder`.
