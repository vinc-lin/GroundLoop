"""A4 — strengthened two-sided accept for the KB A/B verdict. Wraps SP3's
fixeval.compare.{compare,compare_metrics,accept} and ADDS two gates the base verdict lacks:
  * phi_ok  — Δphi_c >= 0 at EVERY c in the sweep (a KB set may never regress effective
    reliability at any risk aversion, not just at c=1.0);
  * wilson_lo — the Wilson-95 lower bound of newly_solved/(newly_solved+newly_broken) must
    clear 0, so a "lift" backed by too few actually-resolved cases (or none) is rejected.
accepted = pos_ok and honesty_ok and phi_ok and (wilson_lo > 0) and cost_ok."""
from __future__ import annotations

from groundloop.eval.metrics import wilson
from groundloop.fixeval.compare import accept, compare, compare_metrics


def strengthened_accept(base_arm: dict, head_arm: dict, *, c_values=(0.5, 1.0, 2.0),
                        cost_budget: float | None = None) -> dict:
    resolved_cmp = compare(base_arm.get("resolved_by_case", {}),
                           head_arm.get("resolved_by_case", {}))
    metrics_cmp = compare_metrics(base_arm, head_arm)
    base = accept(metrics_cmp, resolved_cmp, cost_budget=cost_budget)
    pos_ok = base["pos_ok"]
    honesty_ok = base["honesty_ok"]
    cost_ok = base["cost_ok"]
    ns, nb = base["newly_solved"], base["newly_broken"]

    base_phi, head_phi = base_arm.get("phi_c", {}), head_arm.get("phi_c", {})
    phi_deltas = {str(c): head_phi.get(str(c), 0.0) - base_phi.get(str(c), 0.0) for c in c_values}
    phi_ok = all(d >= 0 for d in phi_deltas.values())

    wilson_lo, _ = wilson(ns, ns + nb)

    reasons = list(base["reasons"])
    if not phi_ok:
        regressed = [c for c, d in phi_deltas.items() if d < 0]
        reasons.append(f"phi_c regressed at c={regressed}")
    if wilson_lo <= 0:
        reasons.append(f"newly-solved evidence too thin (Wilson-95 lo={wilson_lo:.3f} "
                       f"at {ns}/{ns + nb})")

    accepted = pos_ok and honesty_ok and phi_ok and (wilson_lo > 0) and cost_ok
    return {"accepted": accepted, "pos_ok": pos_ok, "honesty_ok": honesty_ok, "phi_ok": phi_ok,
            "wilson_lo": wilson_lo, "cost_ok": cost_ok, "reasons": reasons}
