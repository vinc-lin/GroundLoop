from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
from groundloop.core.types import RepoRef, Signals


class _StubIdx:
    def __init__(self, by_query):
        self._q = by_query

    def rank_repos(self, s, c):
        return []

    def retrieve(self, repo, query):
        return list(self._q.get(query, []))


def _sig(code=()):
    return Signals(classes=tuple(code))


def test_rrf_union_ranks_shared_file_first():
    # crash tier (code_query) -> [A,B]; literal tier (anchor 'PNG') -> [B,C]; B shared -> RRF rank 1
    fts = _StubIdx({"FooCrash": ["A.kt", "B.kt"], "PNG": ["B.kt", "C.kt"]})
    idx = CascadeLocalizeIndex(match=_StubIdx({}), fts=fts, semantic=None,
                               anchors_fn=lambda text, store, repo: ["PNG"], store=object())
    idx.note_signals(_sig(("FooCrash",)))   # code_query -> "FooCrash"
    out = idx.retrieve(RepoRef("r"), "screenshots are PNG")
    assert out[0] == "B.kt"
    assert set(out) == {"A.kt", "B.kt", "C.kt"}


def test_non_regressive_floor_when_no_tier_fires():
    fts = _StubIdx({"just prose": ["X.kt"]})
    idx = CascadeLocalizeIndex(match=_StubIdx({}), fts=fts, semantic=None,
                               anchors_fn=lambda text, store, repo: [], store=object())
    idx.note_signals(Signals())              # no code tokens, no anchors, no embedder
    assert idx.retrieve(RepoRef("r"), "just prose") == ["X.kt"]   # == the FTS floor, never []


def test_semantic_tier_included_when_present():
    fts = _StubIdx({"just prose": ["X.kt"]})
    sem = _StubIdx({"just prose": ["Y.kt", "X.kt"]})
    idx = CascadeLocalizeIndex(match=_StubIdx({}), fts=fts, semantic=sem,
                               anchors_fn=lambda text, store, repo: [], store=object())
    idx.note_signals(Signals())
    out = idx.retrieve(RepoRef("r"), "just prose")
    assert set(out) == {"X.kt", "Y.kt"}      # semantic fired -> union includes Y.kt
