from groundloop.adapters.index.labs.cascade_localize import CascadeLocalizeIndex
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


def test_non_regressive_when_literal_fires_but_misses_oracle():
    # BLOCKER regression (review #1): functional ticket, no code tokens, no embedder, an anchor that FIRES
    # but misses the oracle. The prose floor uniquely lands the oracle, so the cascade MUST still surface it.
    # Before the floor-as-permanent-union-member fix, a firing anchor discarded the floor and the oracle
    # vanished from the result -> a strict recall regression below `--localize atlas`.
    fts = _StubIdx({"HVAC temperature wrong": ["ORACLE.kt"],    # the prose floor finds the oracle
                    "HVAC": ["WRONG1.kt", "WRONG2.kt"]})        # the anchor finds only wrong files
    idx = CascadeLocalizeIndex(match=_StubIdx({}), fts=fts, semantic=None,
                               anchors_fn=lambda text, store, repo: ["HVAC"], store=object())
    idx.note_signals(Signals())              # no code tokens
    out = idx.retrieve(RepoRef("r"), "HVAC temperature wrong")
    assert "ORACLE.kt" in out                # the floor's oracle survives the union (was ABSENT pre-fix)
