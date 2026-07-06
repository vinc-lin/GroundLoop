"""C3 re-validation gate — the distilled form (B) must RE-EARN its lift before it is canonical.

Provenance: C1 `distill_guidance` compresses helped-trace spans into a shorter form B and C2
`lofo_fragments` prunes the non-load-bearing ones. Neither guarantees B reproduces form A's lift —
compression can over-shrink. This is the gate: re-measure the lift on the distilled form and require
it to clear the baseline (form-A) lift within `margin`. If B underperforms A beyond `margin`, the
distilled form is REJECTED (False) and must not be promoted to canonical (mirrors the accept-gate
notion of lift in `groundloop/kb/accept.py`, but for the distilled artifact rather than an arm).
"""
from __future__ import annotations

from collections.abc import Callable


def revalidate(
    distilled_guidance: str,
    baseline_lift: float,
    run_fn: Callable[[str], float],
    *,
    margin: float = 0.0,
) -> bool:
    """True iff the distilled form re-earns the baseline lift within `margin`.

    ``run_fn(guidance) -> float`` returns a lift score (same Callable[[str], float] shape C2
    `lofo_fragments` consumes — e.g. a Φ_c delta or newly-solved rate from a fix-eval A/B run).
    Passes iff ``run_fn(distilled_guidance) >= baseline_lift - margin``; ``margin`` is a
    non-negative slack (0.0 demands the full baseline lift).
    """
    if margin < 0:
        raise ValueError(f"margin must be non-negative, got {margin!r}")
    return run_fn(distilled_guidance) >= baseline_lift - margin
