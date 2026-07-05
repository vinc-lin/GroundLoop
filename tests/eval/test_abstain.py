from groundloop.eval.abstain import decide
from groundloop.core.types import RepoScore, RepoRef


def _r(name, score):
    return RepoScore(RepoRef(name), float(score))


def test_predicts_top1_when_margin_and_score_clear():
    ranked = [_r("a", 5), _r("b", 2)]
    d = decide(ranked, tau_margin=2.0, tau_score=1.0)
    assert d.predicted == "a" and d.margin == 3.0 and d.top1_score == 5.0


def test_abstains_on_low_margin():
    ranked = [_r("a", 3), _r("b", 3)]      # margin 0
    d = decide(ranked, tau_margin=2.0, tau_score=1.0)
    assert d.predicted is None


def test_abstains_on_weak_top1_even_if_margin_ok():
    ranked = [_r("a", 0.5), _r("b", 0.0)]  # margin 0.5 but score below tau_score
    d = decide(ranked, tau_margin=0.3, tau_score=1.0)
    assert d.predicted is None


def test_single_candidate_margin_is_top_score():
    d = decide([_r("a", 4)], tau_margin=2.0, tau_score=1.0)
    assert d.predicted == "a" and d.margin == 4.0


def test_empty_ranked_abstains():
    d = decide([], tau_margin=2.0, tau_score=1.0)
    assert d.predicted is None
