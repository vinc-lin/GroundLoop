"""RerankLocalizeIndex must SURFACE (never silently swallow) a live embed-lane failure.

The reranker's candidate-gen uses the bge-m3 vector lane (find_related_units) when an embedder is
present, degrading to keyword-only on error. That degrade is legitimate BUT it must be visible: a
mid-run embed failure that silently drops the vector lane makes a rerank scorecard look valid while
the vector signal is gone. Assert the swallowed error is counted on `embed_failures` (and the
keyword fallback still returns a pool)."""
from __future__ import annotations

import pytest

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.labs.rerank_localize import RerankLocalizeIndex
from groundloop.core.types import RepoRef, Signals
from groundloop.engines.atlas.store import Store, Unit

REPO = "repoA"
ALPHA = "src/alpha.java"


class _BoomEmbedder:
    """Embedder whose vector lane is down (a live gateway failure mid-run)."""
    def embed(self, texts):
        raise RuntimeError("embed gateway down")


@pytest.fixture()
def atlas(tmp_path):
    db = str(tmp_path / "atlas.db")
    s = Store(db)
    units = [Unit(repo=REPO, kind="symbol", name="Alpha", qualified_name="com.foo.Alpha",
                  file=ALPHA, repo_head="h", text="class Alpha audio handler", meta={})]
    s.reindex_repo(REPO, list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return db


def test_embed_failure_is_counted_not_swallowed(atlas):
    idx = RerankLocalizeIndex(AtlasIndex(atlas), store=Store(atlas),
                              embedder=_BoomEmbedder(), judge=None)
    idx.note_signals(Signals(classes=("com.foo.Alpha",)))
    out = idx.retrieve(RepoRef(REPO), "alpha")
    assert idx.embed_failures == 1          # the swallowed embed error is now visible
    assert ALPHA in out                     # keyword fallback still returns the pool (degrade, not sink)


def test_embed_failures_starts_at_zero(atlas):
    idx = RerankLocalizeIndex(AtlasIndex(atlas), store=Store(atlas), embedder=None, judge=None)
    assert idx.embed_failures == 0
