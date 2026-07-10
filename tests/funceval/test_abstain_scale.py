from groundloop.core.types import RepoRef, RepoScore
from groundloop.eval.abstain import decide
from groundloop.funceval.arms import TAU_FUNC


def test_tau_func_abstains_on_flat_and_answers_on_clear():
    tm, ts = TAU_FUNC
    flat = [RepoScore(RepoRef("a"), 0.30), RepoScore(RepoRef("b"), 0.29)]     # tiny margin -> abstain
    clear = [RepoScore(RepoRef("a"), 0.40), RepoScore(RepoRef("b"), 0.10)]    # wide margin -> answer
    assert decide(flat, tau_margin=tm, tau_score=ts).predicted is None
    assert decide(clear, tau_margin=tm, tau_score=ts).predicted == "a"
