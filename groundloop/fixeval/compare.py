"""Δ optimization surface (ported from bfl/eval/compare.py). None never counts as solved/broken."""
from __future__ import annotations


def compare(base: dict, head: dict) -> dict:
    """base/head are {case_id: resolved bool|None}. Returns newly_solved / newly_broken (sorted)."""
    keys = sorted(set(base) | set(head))
    return {
        "newly_solved": [k for k in keys if base.get(k) is False and head.get(k) is True],
        "newly_broken": [k for k in keys if base.get(k) is True and head.get(k) is False],
    }


def _val(metric):
    return metric.get("value") if isinstance(metric, dict) else metric


def _delta(base, head):
    """head - base, None-safe (None on either side -> None; never raises on empty subsets)."""
    if base is None or head is None:
        return None
    return head - base


_POS = ("file_recall@1", "file_recall@3", "file_recall@5", "resolved_rate", "patch_apply_rate")
_NEG = ("fabrication_rate",)
_COST = ("cost_per_solved", "cost_total")
_GROUNDED = ("resolved_rate_strict", "plan_target_recall@1", "plan_target_recall@5",
             "plan_api_match", "plan_groundedness")


def compare_metrics(base_arm: dict, head_arm: dict) -> dict:
    """Per-arm {metric: {base, head, delta}} for the POS/NEG/COST scalars in a fix scorecard."""
    out: dict = {}
    for m in _POS + _NEG + _COST + _GROUNDED:
        b, h = _val(base_arm.get(m)), _val(head_arm.get(m))
        out[m] = {"base": b, "head": h, "delta": _delta(b, h)}
    b = base_arm.get("phi_c", {}).get("1.0")
    h = head_arm.get("phi_c", {}).get("1.0")
    out["phi_c@1.0"] = {"base": b, "head": h, "delta": _delta(b, h)}
    return out


def accept(metrics_cmp: dict, resolved_cmp: dict, *, cost_budget: float | None = None) -> dict:
    """The SP3 two-sided verdict. POS = Δfile_recall@1>0 OR newly_solved>newly_broken; NEG (honesty) =
    Δfabrication_rate<=0 (None = no Bucket-1 in set, not a regression); COST = advisory unless a
    cost_budget is given. abstention_recall_oof is a Stage-1 metric, invariant to skills (asserted
    elsewhere), so it is not diffed here."""
    dfr = metrics_cmp["file_recall@1"]["delta"]
    dfab = metrics_cmp["fabrication_rate"]["delta"]
    dcost = metrics_cmp["cost_per_solved"]["delta"]
    ns, nb = len(resolved_cmp.get("newly_solved", [])), len(resolved_cmp.get("newly_broken", []))
    pos_ok = (dfr is not None and dfr > 0) or ns > nb
    honesty_ok = dfab is None or dfab <= 0
    cost_ok = cost_budget is None or dcost is None or dcost <= cost_budget
    reasons = []
    if not pos_ok:
        reasons.append("no positive lift (Δfile_recall@1<=0 and newly_solved<=newly_broken)")
    if not honesty_ok:
        reasons.append(f"fabrication_rate rose (Δ={dfab})")
    if not cost_ok:
        reasons.append(f"cost_per_solved rose beyond budget (Δ={dcost})")
    return {"accepted": pos_ok and honesty_ok and cost_ok, "pos_ok": pos_ok,
            "honesty_ok": honesty_ok, "cost_ok": cost_ok,
            "newly_solved": ns, "newly_broken": nb, "reasons": reasons}


def accept_grounded(metrics_cmp: dict, resolved_cmp: dict, *, cost_budget: float | None = None) -> dict:
    """Two-sided verdict on the GROUNDED plan signal (not the game-able resolved_rate) — the gate for
    validating raw KB AND distilled knowledge under --fixer plan. POS = Δplan_target_recall@1>0 OR
    Δresolved_rate_strict>0 ; HONESTY = Δfabrication_rate<=0 AND Δplan_groundedness>=0 (must not
    hallucinate more) ; COST advisory unless a budget is given. Absent plan metrics -> pos_ok False."""
    dtr = metrics_cmp.get("plan_target_recall@1", {}).get("delta")
    drs = metrics_cmp.get("resolved_rate_strict", {}).get("delta")
    dfab = metrics_cmp.get("fabrication_rate", {}).get("delta")
    dgnd = metrics_cmp.get("plan_groundedness", {}).get("delta")
    dcost = metrics_cmp.get("cost_per_solved", {}).get("delta")
    pos_ok = (dtr is not None and dtr > 0) or (drs is not None and drs > 0)
    honesty_ok = (dfab is None or dfab <= 0) and (dgnd is None or dgnd >= 0)
    cost_ok = cost_budget is None or dcost is None or dcost <= cost_budget
    reasons = []
    if not pos_ok:
        reasons.append("no grounded lift (Δplan_target_recall@1<=0 and Δresolved_rate_strict<=0)")
    if not honesty_ok:
        reasons.append(f"honesty regressed (Δfabrication={dfab}, Δgroundedness={dgnd})")
    if not cost_ok:
        reasons.append(f"cost_per_solved rose beyond budget (Δ={dcost})")
    return {"accepted": pos_ok and honesty_ok and cost_ok, "pos_ok": pos_ok,
            "honesty_ok": honesty_ok, "cost_ok": cost_ok, "reasons": reasons}
