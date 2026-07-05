from groundloop.eval.cost import cost_of, tokens_from_raw, cost_from_raw, PRICES


def test_cost_of_uses_price_row():
    # 1M input + 1M output at (10, 20) per 1e6 -> 30.0
    c = cost_of(1_000_000, 1_000_000, "m", prices={"m": (10.0, 20.0)})
    assert abs(c - 30.0) < 1e-9


def test_cost_of_unknown_model_is_zero():
    assert cost_of(1000, 1000, "nope", prices={"m": (1.0, 1.0)}) == 0.0


def test_tokens_and_cost_from_raw():
    raw = {"usage": {"input_tokens": 12, "output_tokens": 3}, "total_cost_usd": 0.0042}
    assert tokens_from_raw(raw) == (12, 3)
    assert abs(cost_from_raw(raw) - 0.0042) < 1e-9
    assert tokens_from_raw("bad") == (0, 0)
    assert cost_from_raw(None) == 0.0


def test_deepseek_priced():
    assert "deepseek-chat" in PRICES     # the served workhorse model must have a row
