from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import (
    PROSE_MARK, is_functional_localize)


def test_is_functional_localize_prose_marked_is_true():
    # DispatchExtractor stuffs prose into symbols[0] behind PROSE_MARK
    sig = Signals(symbols=(PROSE_MARK + "carplay icon does nothing when tapped",))
    assert is_functional_localize(sig) is True


def test_is_functional_localize_no_anchor_is_true():
    # A prose-only ticket under a non-dispatch extractor: no code tells extracted
    assert is_functional_localize(Signals()) is True
    assert is_functional_localize(Signals(errors=("ANR",))) is True  # generic error != code anchor


def test_is_functional_localize_with_code_anchor_is_false():
    sig = Signals(classes=("com.x.CarPlaySession",), methods=("onConnect",),
                  libraries=("libcarplay.so",))
    assert is_functional_localize(sig) is False


def test_is_functional_localize_native_symbol_anchor_is_false():
    # A real native symbol (NOT prose-marked) is a crash anchor -> FTS5 path
    assert is_functional_localize(Signals(symbols=("IAP2Session",))) is False


def test_is_functional_localize_classes_only_no_frame_is_true():
    # production shape: logcat mentions FQ classes (no stack frame) -> functional -> semantic
    sig = Signals(classes=("com.x.Foo", "com.y.Bar"), packages=("com.x", "com.y"))
    assert is_functional_localize(sig) is True


def test_is_functional_localize_stack_frame_method_is_false():
    assert is_functional_localize(Signals(classes=("com.x.Foo",), methods=("bar",))) is False


def test_is_functional_localize_prose_mark_with_other_symbols_is_true():
    sig = Signals(symbols=(PROSE_MARK + "wrong label", "extra"))
    assert is_functional_localize(sig) is True


class _FakeMatch:
    def __init__(self):
        self.seen = None
    def rank_repos(self, signals, catalog):
        self.seen = signals
        return [RepoScore(RepoRef("r"), 1.0)]


class _FakeRetriever:
    def __init__(self, tag):
        self.tag = tag
    def retrieve(self, repo, query):
        return [f"{self.tag}:{repo.name}"]


def _dispatch():
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    return LocalizeDispatchIndex(_FakeMatch(), _FakeRetriever("crash"), _FakeRetriever("func"))


def test_rank_repos_delegates_and_stashes_signals():
    d = _dispatch()
    sig = Signals(classes=("com.x.Foo",))
    out = d.rank_repos(sig, [RepoRef("r")])
    assert out[0].repo.name == "r"
    assert d._match.seen is sig            # delegated to the match index
    assert d._last_signals is sig          # stashed for the following retrieve


def test_retrieve_routes_functional_to_semantic_after_rank():
    d = _dispatch()
    d.rank_repos(Signals(), [RepoRef("r")])          # no-anchor -> functional
    assert d.retrieve(RepoRef("r"), "q") == ["func:r"]


def test_retrieve_routes_crash_to_fts5_after_rank():
    d = _dispatch()
    d.rank_repos(Signals(methods=("bar",)), [RepoRef("r")])   # frame evidence -> crash
    assert d.retrieve(RepoRef("r"), "q") == ["crash:r"]


def test_retrieve_without_signals_falls_back_to_crash():
    d = _dispatch()
    assert d.retrieve(RepoRef("r"), "q") == ["crash:r"]   # no rank/seed -> safe FTS5 default


def test_note_signals_seeds_functional_route_for_out_of_loop_callers():
    d = _dispatch()
    d.note_signals(Signals(symbols=(PROSE_MARK + "prose",)))
    assert d.retrieve(RepoRef("r"), "q") == ["func:r"]


def test_rank_repos_refreshes_stash_across_tickets_on_one_instance():
    d = _dispatch()
    d.rank_repos(Signals(methods=("bar",)), [RepoRef("r")])          # ticket 1: frame evidence -> crash
    assert d.retrieve(RepoRef("r"), "q") == ["crash:r"]
    d.rank_repos(Signals(), [RepoRef("r")])                          # ticket 2 (same instance): no-anchor
    assert d.retrieve(RepoRef("r"), "q") == ["func:r"]               # must re-route, not stay crash


def test_argparse_accepts_localize_dispatch():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(
        ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
         "--index-db", "a.db", "--out", "o", "--repos", "r", "--localize", "dispatch"])
    assert ns.localize == "dispatch"


class _EchoRetriever:
    def retrieve(self, repo, query):
        return [f"q={query}"]


def test_crash_branch_queries_extracted_code_tokens_not_summary():
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    d = LocalizeDispatchIndex(_FakeMatch(), _EchoRetriever(), _EchoRetriever())
    d.rank_repos(Signals(classes=("com.x.Foo",), methods=("bar",), packages=("com.x",)), [RepoRef("r")])
    hits = d.retrieve(RepoRef("r"), "the wifi name is wrong")   # summary passed by run_ticket
    q = hits[0][2:]
    assert "com.x.Foo" in q and "bar" in q and "the wifi name is wrong" not in q  # code tokens, not prose


def test_functional_branch_keeps_prose_summary_query():
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    d = LocalizeDispatchIndex(_FakeMatch(), _EchoRetriever(), _EchoRetriever())
    d.rank_repos(Signals(classes=("com.x.Foo",)), [RepoRef("r")])   # no frame -> functional
    assert d.retrieve(RepoRef("r"), "wrong label") == ["q=wrong label"]   # prose summary for bge-m3


def test_code_query_drops_prose_mark_and_dedups_in_order():
    from groundloop.domains.android_ivi.functional_signals import code_query
    sig = Signals(classes=("com.x.Foo", "com.x.Foo"), methods=("bar",),
                  symbols=(PROSE_MARK + "prose", "IAP2Session"))
    assert code_query(sig) == "com.x.Foo bar IAP2Session"   # prose-mark dropped, deduped, class->method->symbol order
