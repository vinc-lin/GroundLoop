from groundloop.core.types import RepoRef, RepoScore, Signals


class _FakeMatch:
    def __init__(self):
        self.seen = None
    def rank_repos(self, signals, catalog):
        self.seen = signals
        return [RepoScore(RepoRef("r"), 1.0)]


class _EchoRetriever:
    def retrieve(self, repo, query):
        return [f"q={query}"]


def _sq():
    from groundloop.adapters.index.labs.signal_query import SignalQueryIndex
    return SignalQueryIndex(_FakeMatch(), _EchoRetriever())


def test_rank_repos_delegates_and_stashes():
    sq = _sq()
    sig = Signals(classes=("com.x.Foo",))
    assert sq.rank_repos(sig, [RepoRef("r")])[0].repo.name == "r"
    assert sq._match.seen is sig and sq._last_signals is sig


def test_retrieve_uses_code_tokens_not_prose():
    sq = _sq()
    sq.rank_repos(Signals(classes=("com.x.Foo",), methods=("bar",)), [RepoRef("r")])
    assert sq.retrieve(RepoRef("r"), "the wifi name is wrong") == ["q=com.x.Foo bar"]


def test_retrieve_falls_back_to_prose_when_no_code_tokens():
    sq = _sq()
    sq.rank_repos(Signals(), [RepoRef("r")])          # no code tokens
    assert sq.retrieve(RepoRef("r"), "wrong label") == ["q=wrong label"]


def test_retrieve_without_signals_uses_passed_query():
    sq = _sq()
    assert sq.retrieve(RepoRef("r"), "wrong label") == ["q=wrong label"]


def test_note_signals_seeds_for_out_of_loop_callers():
    sq = _sq()
    sq.note_signals(Signals(classes=("com.x.Foo",)))
    assert sq.retrieve(RepoRef("r"), "prose") == ["q=com.x.Foo"]


def test_argparse_accepts_localize_tokens():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(["run", "--localize", "tokens", "--dataset", "d",
                                    "--catalog", "c", "--work", "w", "--changes", "ch", "--index-db", "x"])
    assert ns.localize == "tokens"
