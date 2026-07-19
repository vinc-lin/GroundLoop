from groundloop.adapters.index.labs.atlas_judge import LLMJudgeIndex, StubJudge
from groundloop.core.types import RepoRef, RepoScore, Signals


class _BaseIndex:
    """Deterministic base ranking a>b>c>d by score."""
    def __init__(self, order):
        self._order = order

    def rank_repos(self, signals, catalog):
        allowed = [r.name for r in catalog]
        ranked = [n for n in self._order if n in allowed]
        return [RepoScore(RepoRef(n), float(len(ranked) - i)) for i, n in enumerate(ranked)]

    def retrieve(self, repo, query):
        return [f"{repo.name}/f.ext"]


def _cat(*names):
    return [RepoRef(n) for n in names]


def test_judge_reranks_base_topk():
    base = _BaseIndex(["a", "b", "c", "d"])
    # judge flips the top-3 to c,a,b
    judge = StubJudge({("a", "b", "c"): ["c", "a", "b"]})
    idx = LLMJudgeIndex(base, judge, top_k=3)
    ranked = idx.rank_repos(Signals(classes=("X",)), _cat("a", "b", "c", "d"))
    assert [r.repo.name for r in ranked][:3] == ["c", "a", "b"]
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_non_candidate_repos_sink_below_reranked():
    base = _BaseIndex(["a", "b", "c", "d"])
    judge = StubJudge({("a", "b"): ["b", "a"]})
    idx = LLMJudgeIndex(base, judge, top_k=2)
    names = [r.repo.name for r in idx.rank_repos(Signals(classes=("X",)), _cat("a", "b", "c", "d"))]
    assert names[:2] == ["b", "a"]           # reranked top-2
    assert set(names[2:]) == {"c", "d"}      # the rest below, order among them unspecified


def test_single_candidate_returns_base_unchanged():
    base = _BaseIndex(["a"])
    idx = LLMJudgeIndex(base, StubJudge({}), top_k=3)
    ranked = idx.rank_repos(Signals(classes=("X",)), _cat("a"))
    assert [r.repo.name for r in ranked] == ["a"]   # nothing to rerank


def test_retrieve_delegates_to_base():
    idx = LLMJudgeIndex(_BaseIndex(["a"]), StubJudge({}), top_k=3)
    assert idx.retrieve(RepoRef("a"), "q") == ["a/f.ext"]


def test_stub_judge_falls_back_to_input_order_when_unmapped():
    base = _BaseIndex(["a", "b", "c"])
    idx = LLMJudgeIndex(base, StubJudge({}), top_k=3)   # empty verdict map
    names = [r.repo.name for r in idx.rank_repos(Signals(classes=("X",)), _cat("a", "b", "c"))]
    assert names == ["a", "b", "c"]                     # unchanged (judge returns candidates as-is)
