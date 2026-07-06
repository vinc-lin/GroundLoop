"""Offline grade for the fix loop — the SOLE oracle read. Mirrors eval/scorecard.grade_all.
Whole-loop metrics: file_recall@k, patch_apply_rate, required_api_pass_rate, resolved_rate (ADVISORY
over the grounded-gradeable subset), fabrication_rate (Bucket-1 refusal), and whole-loop phi_c."""
from __future__ import annotations

from collections import defaultdict

from groundloop.eval.metrics import phi_c, recall_at_k, wilson
from groundloop.fixeval.patch import norm_path, references_api, references_api_code, touched_files


def _wrap(v, n):
    """{value, wilson95, n}. value None (undefined) when the subset is empty."""
    if not n:
        return {"value": None, "n": 0}
    return {"value": v, "wilson95": list(wilson(round(v * n), n)), "n": n}


def _file_recall(rec, oracle, k):
    return recall_at_k([norm_path(x) for x in rec.locations],
                       {norm_path(e) for e in oracle.expected_files}, k)


def _resolved_strict(rec, oracle) -> bool:
    """Hardened resolution: the PATCH's own touched files intersect expected_files (not localize's
    locations), and every required_api appears on an added CODE line (comments excluded)."""
    tf = {norm_path(x) for x in touched_files(rec.patch_diff)}
    ef = {norm_path(e) for e in oracle.expected_files}
    return bool(rec.patch_applies and (tf & ef)
                and all(references_api_code(rec.patch_diff, a) for a in oracle.required_apis))


def grade_fix_all(records, *, oracle_by_case, ks=(1, 3, 5), c_values=(0.5, 1.0, 2.0)) -> dict:
    by_arm: dict = defaultdict(list)
    for r in records:
        by_arm[r.arm].append(r)

    arms: dict = {}
    for arm, recs in by_arm.items():
        n = len(recs)
        pairs = [(r, oracle_by_case[r.case_id]) for r in recs]
        answered = [r for r in recs if r.patch_emitted]
        loc = [(r, o) for r, o in pairs if o.expected_files]
        api = [(r, o) for r, o in pairs if o.required_apis]
        api_pass = [all(references_api(r.patch_diff, a) for a in o.required_apis) for r, o in api]
        # grounded-gradeable = expected_files AND required_apis both present (else advisory-excluded)
        grd = [(r, o) for r, o in pairs if o.expected_files and o.required_apis]
        solved = [r for r, o in grd if r.patch_applies and _file_recall(r, o, 1) > 0
                  and all(references_api(r.patch_diff, a) for a in o.required_apis)]
        solved_strict = [r for r, o in grd if _resolved_strict(r, o)]
        gradeable_ids = {r.case_id for r, _ in grd}
        solved_ids = {r.case_id for r in solved}
        # per-case resolved bit for `gloop compare` (None = not grounded-gradeable, never counts)
        resolved_by_case = {r.case_id: (r.case_id in solved_ids if r.case_id in gradeable_ids else None)
                            for r in recs}
        # whole-loop phi_c: answered:=patch_emitted, answerable:=is_answerable, correct:=applies & recall
        phi_recs = [{"answered": r.patch_emitted, "answerable": o.is_answerable,
                     "correct": bool(r.patch_applies and o.expected_files and _file_recall(r, o, 1) > 0)}
                    for r, o in pairs]
        # fabrication = Bucket-1 (is_answerable=false) case that emitted a CLEAN-APPLYING patch
        bucket1 = [r for r, o in pairs if not o.is_answerable]
        fabricated = [r for r in bucket1 if r.patch_emitted and r.patch_applies]
        cost_total = sum(r.cost_usd for r in recs)
        arms[arm] = {
            "n": n,
            "fix_coverage": len(answered) / n if n else 0.0,
            "abstain_rate": (n - len(answered)) / n if n else 0.0,
            **{f"file_recall@{k}": (_wrap(sum(_file_recall(r, o, k) for r, o in loc) / len(loc), len(loc))
                                    if loc else {"value": None, "n": 0}) for k in ks},
            "patch_apply_rate": (sum(r.patch_applies for r in answered) / len(answered)) if answered else 0.0,
            "required_api_pass_rate": (_wrap(sum(api_pass) / len(api_pass), len(api_pass))
                                       if api_pass else {"value": None, "n": 0}),
            "resolved_rate": _wrap(len(solved) / len(grd), len(grd)) if grd else {"value": None, "n": 0},
            "resolved_rate_strict": (_wrap(len(solved_strict) / len(grd), len(grd))
                                     if grd else {"value": None, "n": 0}),
            "n_gradeable": len(grd),
            "n_excluded": n - len(grd),
            "fabrication_rate": (_wrap(len(fabricated) / len(bucket1), len(bucket1))
                                 if bucket1 else {"value": None, "n": 0}),
            "phi_c": {str(c): phi_c(phi_recs, c=c) for c in c_values},
            "cost_total": cost_total,
            "cost_per_solved": (cost_total / len(solved)) if solved else None,
            "resolved_by_case": resolved_by_case,
        }
    return {"arms": arms, "n_cases": len({r.case_id for recs in by_arm.values() for r in recs})}
