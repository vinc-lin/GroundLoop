"""Token->USD cost for live eval arms (migrated from knowledgeLoop eval/cost.py).

PRICES is ILLUSTRATIVE per 1e6 tokens (input, output) — CONFIRM before a billed run; the scorecard
records the table actually used so a stale row is visible, not silent."""
from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.28, 0.42),          # the served produce/judge workhorse (illustrative)
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}


def cost_of(input_tokens: int, output_tokens: int, model: str, *, prices: dict = PRICES) -> float:
    row = prices.get(model)
    if row is None:
        return 0.0
    in_price, out_price = row
    return input_tokens / 1_000_000 * in_price + output_tokens / 1_000_000 * out_price


def tokens_from_raw(raw) -> tuple[int, int]:
    usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def cost_from_raw(raw) -> float:
    if not isinstance(raw, dict):
        return 0.0
    try:
        return float(raw.get("total_cost_usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
