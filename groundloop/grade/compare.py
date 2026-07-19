"""Diff two grade-run cards into a per-stage regression verdict — the grade-run analogue of
fixeval.compare. Reads only the quality scalars (match recall@1 / localize file@5 / fix resolved_rate)
plus cost; the verdict is driven by the three quality metrics, never by cost or a count change alone."""
from __future__ import annotations

_EPS = 1e-9


def _dig(card: dict, *keys):
    """Walk a nested .get chain, tolerating missing dicts / None anywhere along the path."""
    cur = card
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _delta(cur, prev) -> dict:
    d = (cur - prev) if (cur is not None and prev is not None) else None
    return {"cur": cur, "prev": prev, "delta": d}


def _cost(card: dict) -> float:
    return sum(c.get("cost_usd", 0.0) or 0.0 for c in (card.get("cases") or []))


def compare_cards(cur: dict, prev: dict) -> dict:
    match = _delta(_dig(cur, "overall", "match", "recall@1"),
                   _dig(prev, "overall", "match", "recall@1"))
    localize = _delta(_dig(cur, "overall", "localize", "as_run", "file@5"),
                      _dig(prev, "overall", "localize", "as_run", "file@5"))
    resolved = _delta(_dig(cur, "overall", "fix", "resolved_rate_strict", "value"),
                      _dig(prev, "overall", "fix", "resolved_rate_strict", "value"))
    n_gradeable = _delta(_dig(cur, "overall", "fix", "n_gradeable"),
                         _dig(prev, "overall", "fix", "n_gradeable"))
    cost = _delta(_cost(cur), _cost(prev))

    # Per-case regressions: as_run@1 fell from a hit (1) to <1, OR fix fell from "applies".
    prev_by_id = {c["case_id"]: c for c in (prev.get("cases") or [])}
    regressions: list = []
    for c in (cur.get("cases") or []):
        p = prev_by_id.get(c["case_id"])
        if p is None:                                   # absent from prev -> not a regression
            continue
        loc_reg = (p.get("as_run@1") == 1) and ((c.get("as_run@1") or 0) < 1)
        fix_reg = (p.get("fix") == "applies") and (c.get("fix") != "applies")
        if loc_reg or fix_reg:
            regressions.append(c["case_id"])

    # Verdict: only the three quality deltas count (cost + n_gradeable are informational).
    tracked = [match["delta"], localize["delta"], resolved["delta"]]
    if any(d is not None and d < -_EPS for d in tracked):
        verdict = "regressed"
    elif any(d is not None and d > _EPS for d in tracked):
        verdict = "improved"
    else:
        verdict = "flat"

    return {
        "match": {"recall@1": match},
        "localize": {"file@5": localize},
        "fix": {"resolved_rate": resolved, "n_gradeable": n_gradeable},
        "cost": cost,
        "regressions": regressions,
        "verdict": verdict,
    }
