from groundloop.eval.metrics import (recall_at_k, success_at_k, mrr, ndcg_at_k,
                                      wilson, phi_c, repo_rank)


def test_migrated_file_metrics():
    assert recall_at_k(["a", "b", "c"], {"a", "z"}, 2) == 0.5
    assert success_at_k(["a", "b"], {"b"}, 2) == 1.0
    assert mrr(["x", "a"], {"a"}) == 0.5
    assert abs(ndcg_at_k(["a"], {"a"}, 1) - 1.0) < 1e-9


def test_repo_rank_exact_match():
    assert repo_rank(["b", "a", "c"], "a") == 2
    assert repo_rank(["b", "c"], "a") == 0        # absent


def test_wilson_bounds_within_0_1_and_centered():
    lo, hi = wilson(7, 10)
    assert 0.0 <= lo <= 0.7 <= hi <= 1.0
    lo0, hi0 = wilson(0, 0)                        # n=0 -> [0,1]
    assert (lo0, hi0) == (0.0, 1.0)


def test_phi_c_rewards_abstain_over_wrong_guess():
    # records: (answered, correct, answerable)
    correct = [{"answered": True, "correct": True, "answerable": True}]
    wrong = [{"answered": True, "correct": False, "answerable": True}]
    abstain = [{"answered": False, "correct": False, "answerable": True}]
    assert phi_c(correct, c=1.0) == 1.0
    assert phi_c(wrong, c=1.0) == -1.0
    assert phi_c(abstain, c=1.0) == 0.0
    # abstaining (0) strictly beats guessing wrong (-1)
    assert phi_c(abstain, c=1.0) > phi_c(wrong, c=1.0)
    # abstain on an UNANSWERABLE ticket is the correct action -> +1
    oof = [{"answered": False, "correct": False, "answerable": False}]
    assert phi_c(oof, c=1.0) == 1.0
