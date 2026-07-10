"""Offline grade pass — the ONLY reader of the oracle. Produces the two-view scorecard
(forced ceiling + selective) per arm (docs/type2-evaluation.md §7)."""
from __future__ import annotations

from collections import defaultdict

from groundloop.eval.runner import MatchRecord
from groundloop.eval.metrics import repo_rank, wilson, phi_c


def score_match(rec: MatchRecord, oracle) -> dict:
    owner = oracle.owning_repo
    is_answerable = bool(getattr(oracle, "is_answerable", True))
    negative_class = getattr(oracle, "negative_class", None)
    bug_kind = getattr(oracle, "bug_kind", None)
    rank = repo_rank(rec.ranked_names, owner)
    answered = rec.predicted is not None
    return {
        "case_id": rec.case_id,
        "repo_rank": rank,
        "recall@1": bool(rec.ranked_names[:1] == [owner]),   # forced view (abstain-agnostic)
        "answered": answered,
        "correct": bool(answered and rec.predicted == owner),
        "answerable": is_answerable,
        "negative_class": negative_class,
        "bug_kind": bug_kind,
        "ranked_names": rec.ranked_names,
    }


def per_case_rows(records, *, oracle_by_case) -> list[dict]:
    """One row per (case x arm): the runner's prediction joined with the offline grade, so
    'which repo did we predict for ticket X' becomes a saved fact (written to predictions.jsonl).
    OFFLINE — reads the oracle (owning_repo) exactly like score_match; never fed to the loop."""
    rows: list[dict] = []
    for rec in records:
        oracle = oracle_by_case[rec.case_id]
        g = score_match(rec, oracle)
        rows.append({
            "case_id": rec.case_id,
            "arm": rec.arm,
            "owning_repo": oracle.owning_repo,
            "predicted": rec.predicted,                             # None = abstained
            "ranked_top1": rec.ranked_names[0] if rec.ranked_names else None,
            "oracle_rank": g["repo_rank"],                          # 1-based; 0 = not in ranking
            "recall@1": g["recall@1"],                              # forced view (abstain-agnostic)
            "correct": g["correct"],                                # selective view (answered & right)
            "answered": g["answered"],
            "answerable": g["answerable"],
            "margin": rec.margin,
            "top1_score": rec.top1_score,
            "ranked_names": rec.ranked_names,
            "scores": rec.scores,
        })
    return rows


def _wrap(k: int, n: int) -> dict:
    return {"value": (k / n if n else 0.0), "wilson95": list(wilson(k, n))}


def grade_all(records, *, oracle_by_case, ks=(1, 3, 5), c_values=(0.5, 1.0, 2.0)) -> dict:
    by_arm: dict[str, list] = defaultdict(list)
    for rec in records:
        by_arm[rec.arm].append(score_match(rec, oracle_by_case[rec.case_id]))

    arms: dict[str, dict] = {}
    for arm, ms in by_arm.items():
        n = len(ms)
        # FORCED view: recall/mrr over the ANSWERABLE subset (an OOF case can never be recall@1)
        ans = [m for m in ms if m["answerable"]]
        na = len(ans)
        forced = {"n_answerable": na}
        for k in ks:
            hits = sum(1 for m in ans if m["repo_rank"] and m["repo_rank"] <= k)
            forced[f"recall@{k}"] = _wrap(hits, na)
        ranks = [m["repo_rank"] for m in ans if m["repo_rank"]]
        forced["mrr"] = sum(1.0 / r for r in ranks) / na if na else 0.0
        forced["mean_repo_rank"] = (sum(ranks) / len(ranks)) if ranks else 0.0

        # SELECTIVE view over ALL cases (Phi_c handles answerable vs unanswerable)
        answered = [m for m in ms if m["answered"]]
        correct_answered = sum(1 for m in answered if m["correct"])
        unans = [m for m in ms if not m["answerable"]]
        abst_unans = sum(1 for m in unans if not m["answered"])
        selective = {
            "coverage": len(answered) / n if n else 0.0,
            "selective_accuracy": _wrap(correct_answered, len(answered)),
            "selective_risk": 1.0 - (correct_answered / len(answered)) if answered else 0.0,
            "phi_c": {str(c): phi_c(ms, c=c) for c in c_values},
            "abstention_recall_oof": {"value": (abst_unans / len(unans) if unans else None),
                                      "n_unanswerable": len(unans)},
        }

        # Per negative_class breakdown (for Bucket-1, abstaining is the correct action)
        per_class: dict[str, dict] = {}
        for m in ms:
            cls = m["negative_class"]
            if cls is None:
                continue
            b = per_class.setdefault(cls, {"n": 0, "abstained": 0})
            b["n"] += 1
            b["abstained"] += 0 if m["answered"] else 1
        for b in per_class.values():
            b["abstain_rate"] = b["abstained"] / b["n"] if b["n"] else 0.0

        arms[arm] = {"n": n, "forced": forced, "selective": selective, "per_class": per_class}
    return {"arms": arms, "n_cases": len({m["case_id"] for ms in by_arm.values() for m in ms})}
