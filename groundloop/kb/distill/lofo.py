"""Leave-one-fragment-out (LOFO) attribution for distilled KB guidance (SP2/SP3 KB lane, C2).

Given a candidate guidance string and a ``run_fn`` that scores its lift, LOFO ablates one
line-fragment at a time and keeps only the fragments whose removal *drops* the lift. This is the
attribution step between C1 (verbatim extraction) and C3 (re-validation of the distilled form):
it prunes inert filler so only load-bearing spans survive toward the canonical skill.
"""
from __future__ import annotations

from collections.abc import Callable


def lofo_fragments(guidance: str, run_fn: Callable[[str], float]) -> list[str]:
    """Return the load-bearing line-fragments of ``guidance`` under ``run_fn``.

    Split ``guidance`` into non-blank line fragments (original order preserved). Measure the
    baseline lift ``run_fn(guidance)``, then for each fragment measure the lift of the guidance
    with that fragment removed. A fragment is *load-bearing* iff its removal strictly lowers the
    lift (``run_fn(ablated) < baseline``); such fragments are returned in their original order.
    """
    fragments = [line for line in guidance.splitlines() if line.strip()]
    baseline = run_fn(guidance)
    load_bearing: list[str] = []
    for i, frag in enumerate(fragments):
        ablated = "\n".join(fragments[:i] + fragments[i + 1 :])
        if run_fn(ablated) < baseline:
            load_bearing.append(frag)
    return load_bearing
