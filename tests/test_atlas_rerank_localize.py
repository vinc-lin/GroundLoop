"""`--localize atlas_rerank` (Task 1): the plain FTS5 `AtlasIndex.retrieve` recall pool, reordered by the
LLM file-judge — composed exactly like `cascade_judge` (see `tests/run/test_localize_cascade_judge_wiring.py`)
but with a plain `AtlasIndex` as the `pool_index` and NO embedder (no vector lane at all, unlike cascade's
optional bge-m3 tier). These are class-level tests: they lock the `RerankLocalizeIndex` behavior the CLI
wiring must preserve, independent of the `gloop run` composition root.

Hermetic — no network / no real LLM (`StubFileJudge`), no live CBM. The atlas fixture carries three
distinct source-file symbol units so `AtlasIndex.retrieve` yields >=2 hits for a single query.
"""
from __future__ import annotations

import pytest

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex, StubFileJudge
from groundloop.core.types import RepoRef
from groundloop.engines.atlas.store import Store, Unit

REPO = "repoA"
ALPHA, BETA, GAMMA = "src/alpha.java", "src/beta.java", "src/gamma.java"
QUERY = "Alpha Beta Gamma"


def _build_atlas(db_path: str) -> str:
    s = Store(db_path)
    units = [
        Unit(repo=REPO, kind="symbol", name="Alpha", qualified_name="com.foo.Alpha",
             file=ALPHA, repo_head="h", text="class Alpha handler", meta={}),
        Unit(repo=REPO, kind="symbol", name="Beta", qualified_name="com.foo.Beta",
             file=BETA, repo_head="h", text="class Beta handler", meta={}),
        Unit(repo=REPO, kind="symbol", name="Gamma", qualified_name="com.foo.Gamma",
             file=GAMMA, repo_head="h", text="class Gamma handler", meta={}),
    ]
    s.reindex_repo(REPO, list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return db_path


@pytest.fixture()
def atlas_db(tmp_path) -> str:
    return _build_atlas(str(tmp_path / "atlas.db"))


def test_atlas_rerank_pool_is_fts5_and_judge_reorders(atlas_db):
    atlas = AtlasIndex(atlas_db)
    pool = atlas.retrieve(RepoRef(REPO), QUERY)
    assert len(pool) >= 2       # a real >=2-hit FTS5 pool, not a degenerate single-file case

    idx = RerankLocalizeIndex(atlas, store=Store(atlas_db), embedder=None,
                              judge=StubFileJudge(order=list(reversed(pool))), pool_index=atlas)
    result = idx.retrieve(RepoRef(REPO), QUERY)

    assert set(result) == set(pool)               # grounded: the judge only REORDERS the real pool
    assert result == list(reversed(pool))          # the stub's scripted order drives the result


def test_atlas_rerank_without_judge_equals_atlas(atlas_db):
    atlas = AtlasIndex(atlas_db)
    idx = RerankLocalizeIndex(atlas, store=Store(atlas_db), embedder=None, judge=None, pool_index=atlas)

    assert idx.retrieve(RepoRef(REPO), QUERY) == atlas.retrieve(RepoRef(REPO), QUERY)
