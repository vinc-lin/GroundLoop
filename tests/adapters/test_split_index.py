from groundloop.adapters.index.labs.split import SplitIndex


class _Idx:
    def __init__(self, tag): self.tag = tag
    def rank_repos(self, signals, catalog): return [("rank", self.tag)]
    def retrieve(self, repo, query): return [f"loc:{self.tag}"]


def test_split_index_delegates_each_method():
    s = SplitIndex(_Idx("M"), _Idx("L"))
    assert s.rank_repos(None, []) == [("rank", "M")]     # from the MATCH index
    assert s.retrieve(None, "q") == ["loc:L"]            # from the LOCALIZE index
