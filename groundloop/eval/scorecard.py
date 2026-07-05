"""Offline grade pass — the ONLY reader of the oracle. Produces the two-view scorecard
(forced ceiling + selective) per arm (docs/type2-evaluation.md §7)."""
from __future__ import annotations

from collections import defaultdict

from groundloop.core.types import Oracle
from groundloop.eval.runner import MatchRecord
from groundloop.eval.metrics import repo_rank, wilson, phi_c


def score_match(rec: MatchRecord, oracle: Oracle, *, is_answerable: bool = True) -> dict:
    owner = oracle.owning_repo
    rank = repo_rank(rec.ranked_names, owner)
    answered = rec.predicted is not None
    return {
        "case_id": rec.case_id,
        "repo_rank": rank,
        "recall@1": bool(rec.ranked_names[:1] == [owner]),   # forced view (abstain-agnostic)
        "answered": answered,
        "correct": bool(answered and rec.predicted == owner),
        "answerable": is_answerable,
        "ranked_names": rec.ranked_names,
    }


def _wrap(k: int, n: int) -> dict:
    return {"value": (k / n if n else 0.0), "wilson95": list(wilson(k, n))}


def grade_all(records, *, oracle_by_case: dict[str, Oracle], ks=(1, 3, 5),
              c_values=(0.5, 1.0, 2.0)) -> dict:
    by_arm: dict[str, list] = defaultdict(list)
    for rec in records:
        oracle = oracle_by_case[rec.case_id]
        by_arm[rec.arm].append(score_match(rec, oracle))

    arms: dict[str, dict] = {}
    for arm, ms in by_arm.items():
        n = len(ms)
        forced = {}
        for k in ks:
            hits = sum(1 for m in ms if m["repo_rank"] and m["repo_rank"] <= k)
            forced[f"recall@{k}"] = _wrap(hits, n)
        ranks = [m["repo_rank"] for m in ms if m["repo_rank"]]
        forced["mrr"] = sum(1.0 / r for r in ranks) / n if n else 0.0
        forced["mean_repo_rank"] = (sum(ranks) / len(ranks)) if ranks else 0.0

        answered = [m for m in ms if m["answered"]]
        correct_answered = sum(1 for m in answered if m["correct"])
        selective = {
            "coverage": len(answered) / n if n else 0.0,
            "selective_accuracy": _wrap(correct_answered, len(answered)),
            "selective_risk": 1.0 - (correct_answered / len(answered)) if answered else 0.0,
            "phi_c": {str(c): phi_c(ms, c=c) for c in c_values},
        }
        arms[arm] = {"n": n, "forced": forced, "selective": selective}
    return {"arms": arms, "n_cases": len({m["case_id"] for ms in by_arm.values() for m in ms})}
