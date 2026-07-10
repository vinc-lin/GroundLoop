from groundloop.eval.report import render_markdown


def _sub(recall1, cov):
    return {"n": 1, "forced": {"recall@1": {"value": recall1}, "mrr": 0.0},
            "selective": {"coverage": cov, "selective_accuracy": {"value": recall1},
                          "phi_c": {"1.0": recall1}}}


def test_render_includes_bug_kind_section():
    card = {"n_cases": 2, "arms": {"functional": {
        "n": 2, "forced": {"recall@1": {"value": 0.5}, "mrr": 0.5},
        "selective": {"coverage": 1.0, "selective_accuracy": {"value": 0.5}, "phi_c": {"1.0": 0.5}},
        "by_bug_kind": {"functional": _sub(0.9, 1.0), "crash": _sub(0.1, 1.0)}}}}
    md = render_markdown(card)
    assert "by bug_kind" in md
    assert "functional / functional" in md and "0.90" in md


def test_render_without_bug_kind_unchanged():
    card = {"n_cases": 1, "arms": {"a": {
        "n": 1, "forced": {"recall@1": {"value": 1.0}, "mrr": 1.0},
        "selective": {"coverage": 1.0, "selective_accuracy": {"value": 1.0}, "phi_c": {"1.0": 1.0}}}}}
    assert "by bug_kind" not in render_markdown(card)
