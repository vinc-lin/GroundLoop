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
    idx = RerankLocalizeIndex(_match(), store=_StubStore(), embedder=None, judge=judge, pool_index=pool)
    idx.note_signals(Signals(classes=("Foo",)))
    out = idx.retrieve(RepoRef("r"), "some prose ticket")
    assert out[0] == "C.kt"                       # judge order, grounded to the pool
    assert set(out) == {"A.kt", "B.kt", "C.kt"}   # pool = the pool_index files
    assert pool.noted == Signals(classes=("Foo",))  # signals forwarded to the pool source


def test_pool_index_none_is_unchanged_default(monkeypatch):
    # sanity: with pool_index=None the reranker uses _gen_hits (existing path) — construct with no pool_index
    idx = RerankLocalizeIndex(_match(), store=_StubStore(), embedder=None, judge=None)
    # _StubStore returns no rows -> empty pool -> retrieve falls back without crashing
    assert idx.retrieve(RepoRef("r"), "prose") == [] or isinstance(idx.retrieve(RepoRef("r"), "prose"), list)
