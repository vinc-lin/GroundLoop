"""Staged per-claim attribution + lifecycle governance (design spec §5.4/§5.5). Three primitives:
  * screen_claims (C2) — a cheap, ORACLE-BLIND directional screen over the plan archive's per-case
    `groundedness` -> a shortlist of promising/suspicious claims (correlational; prioritizes, never
    promotes);
  * lofo_claims (C3) — leave-one-CLAIM-out ablation Δ (mirrors kb/distill/lofo.lofo_fragments);
  * attribute_and_govern (C4) — LOFO-confirm vs the per-claim placebo -> accept_grounded two-sided verdict
    -> apply_verdict per claim (promote/retire), bridged onto the Claim via a small ClaimRecord adapter.
The SCREEN reads only the archive (no oracle, no new spend); the CONFIRM re-runs the plan-format fix eval
whose grade_fix_all is the sole, offline oracle read. The loop stays oracle-blind throughout."""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterable
from pathlib import Path

from groundloop.fixeval.compare import accept_grounded, compare, compare_metrics
from groundloop.kb.claim import Claim
from groundloop.kb.claim_placebo import build_claim_placebo
from groundloop.kb.lifecycle import TIERS, apply_verdict


def load_archive(plans_dir: str) -> list[dict]:
    """Load every per-case plan payload written by fixeval/archive.archive_plans (<dir>/*.json). A missing
    dir is an empty archive (nothing to attribute yet), not an error; a malformed file is skipped, not
    fatal — mirrors kb/provenance.load_sidecar's tolerance."""
    d = Path(plans_dir)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _case_groundedness(payload: dict) -> float | None:
    """The archive's per-case ORACLE-BLIND grounded signal (fraction of a plan's cited entities that resolve
    in the atlas). None when absent (e.g. an abstain-only case) -> excluded from the mean."""
    g = (payload.get("outcome") or {}).get("groundedness")
    return float(g) if isinstance(g, (int, float)) else None


def screen_claims(archive: Iterable[dict], claims: dict[str, Claim], *,
                  threshold: float = 0.0, min_fired: int = 1) -> list[str]:
    """Cheap oracle-blind directional screen (spec §5.4). Pinned formula, per claim:
        screen_lift = mean(groundedness | claim FIRED) - mean(groundedness | claim did NOT fire).
    Shortlist = claims with |screen_lift| >= threshold (promising OR suspicious), sorted by |screen_lift|
    desc (so a --max-lofo cap keeps the strongest signals). No firing case (< min_fired) or no baseline
    case -> no contrast -> skipped. Correlational only: it PRIORITIZES the LOFO shortlist, never promotes."""
    rows = list(archive)
    scored: list[tuple[float, str]] = []
    for cid in claims:
        fv = [g for g in (_case_groundedness(p) for p in rows
                          if cid in (p.get("fired_claims") or [])) if g is not None]
        bv = [g for g in (_case_groundedness(p) for p in rows
                          if cid not in (p.get("fired_claims") or [])) if g is not None]
        if len(fv) < min_fired or not bv:
            continue
        lift = sum(fv) / len(fv) - sum(bv) / len(bv)
        if abs(lift) >= threshold:
            scored.append((abs(lift), cid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [cid for _, cid in scored]


def lofo_claims(claim_ids: Iterable[str], run_fn: Callable[[frozenset[str]], float]) -> dict[str, float]:
    """Leave-one-CLAIM-out attribution — the claim-granular analogue of kb/distill/lofo.lofo_fragments.
    baseline = run_fn(full_set); for each claim, Δ = baseline - run_fn(full_set without that claim). A
    POSITIVE Δ means removing the claim dropped the metric (the claim was load-bearing). `run_fn(set[str])
    -> float` is a driver-supplied closure that re-runs the grounded fix eval with exactly that claim set
    (grade_fix_all inside it is the sole, offline oracle read). Returns {claim_id: Δ}, first-seen order."""
    ids = list(dict.fromkeys(claim_ids))            # de-dup, preserve first-seen order
    full = frozenset(ids)
    baseline = run_fn(full)
    return {cid: baseline - run_fn(full - {cid}) for cid in ids}


@dataclasses.dataclass(frozen=True)
class ClaimRecord:
    """The minimal record kb/lifecycle.apply_verdict reads/replaces — a bridge so the REUSED tier ladder
    can govern a Claim whose fail_count/demotions live inside its evidence bag."""
    id: str
    tier: str
    fail_count: int = 0
    demotions: tuple[str, ...] = ()


def to_record(claim: Claim) -> ClaimRecord:
    ev = claim.evidence or {}
    return ClaimRecord(id=claim.id, tier=claim.tier, fail_count=int(ev.get("fail_count", 0)),
                       demotions=tuple(ev.get("demotions", ())))


def promote_or_retire(claim: Claim, passed: bool, *, hysteresis: int = 2,
                      measured_lift: dict | None = None, wilson95=None,
                      validating_case_ids: Iterable[str] | None = None) -> Claim:
    """Fold one per-claim verdict into the tier ladder and return the updated (new) Claim. `passed` ->
    apply_verdict promotes one rung + resets the streak; a failing streak reaching `hysteresis` demotes one
    rung, EXCEPT at the bottom rung (candidate) where it RETIRES the claim (terminal — 'retired' is outside
    TIERS, so the Phase-B ClaimRegistry never fires it again). Writes tier + evidence (fail_count, demotions,
    and optional measured_lift/wilson95/validating_case_ids) back onto the frozen Claim."""
    if claim.tier not in TIERS:                       # retired (or any non-TIER) is terminal
        return claim
    rec = to_record(claim)
    retiring = (not passed and rec.tier == TIERS[0] and rec.fail_count + 1 >= hysteresis)
    if retiring:
        new_tier, new_fail = "retired", 0
        new_demotions = rec.demotions + (f"{rec.tier}->retired",)
    else:
        nr = apply_verdict(rec, passed, hysteresis=hysteresis)
        new_tier, new_fail, new_demotions = nr.tier, nr.fail_count, nr.demotions
    ev = dict(claim.evidence or {})
    ev["fail_count"] = new_fail
    ev["demotions"] = list(new_demotions)
    if measured_lift is not None:
        ev["measured_lift"] = measured_lift
    if wilson95 is not None:
        ev["wilson95"] = wilson95
    if validating_case_ids is not None:
        ev["validating_case_ids"] = list(validating_case_ids)
    return dataclasses.replace(claim, tier=new_tier, evidence=ev)


def _metric_value(card: dict, key: str) -> float:
    m = card.get(key)
    v = m.get("value") if isinstance(m, dict) else m
    return float(v) if isinstance(v, (int, float)) else 0.0


def attribute_and_govern(claims: dict[str, Claim], shortlist: Iterable[str],
                         run_card_fn: Callable[[frozenset[str]], dict], *,
                         primary: str = "plan_target_recall@1", cost_budget: float | None = None,
                         hysteresis: int = 2) -> dict[str, Claim]:
    """Confirm each shortlisted candidate causally, then govern its tier — one claim at a time (spec §5.5).
    `run_card_fn(claim_id_set) -> eval-arm scorecard dict` re-runs the grounded fix eval with EXACTLY that
    claim set injected (candidates + their per-claim placebos, resolved by the driver's pool) and returns
    the arm's grounded metrics; grade_fix_all inside it is the sole, offline oracle read. Per claim:
      * LOFO Δ (C3) over the active shortlist — the claim must be load-bearing (Δ > 0);
      * placebo-swap comparison — the claim arm (head) vs the arm with the claim replaced by its
        length-matched placebo (base, same firing set) -> accept_grounded's two-sided grounded gate;
    promote iff BOTH pass; else fail -> promote_or_retire records the streak/retirement. Returns the full
    updated store (non-shortlisted claims pass through unchanged)."""
    valid = [cid for cid in dict.fromkeys(shortlist) if cid in claims]
    active = frozenset(valid)
    placebos = build_claim_placebo({cid: claims[cid] for cid in valid})     # C1: one placebo per candidate

    def metric_fn(s: frozenset[str]) -> float:
        return _metric_value(run_card_fn(frozenset(s)), primary)

    deltas = lofo_claims(valid, metric_fn)                                  # C3: leave-one-claim-out Δ
    updated = dict(claims)
    for cid in valid:
        pid = "placebo-" + cid
        assert pid in placebos                                             # C1 built one per shortlisted claim
        head = run_card_fn(active)                                         # claim present
        base = run_card_fn((active - {cid}) | {pid})                       # claim swapped for its placebo
        metrics_cmp = compare_metrics(base, head)
        resolved_cmp = compare(base.get("resolved_by_case", {}), head.get("resolved_by_case", {}))
        verdict = accept_grounded(metrics_cmp, resolved_cmp, cost_budget=cost_budget)
        passed = bool(verdict["accepted"]) and deltas.get(cid, 0.0) > 0    # load-bearing AND two-sided-clean
        updated[cid] = promote_or_retire(
            claims[cid], passed, hysteresis=hysteresis,
            measured_lift={"lofo_delta": deltas.get(cid, 0.0),
                           primary: metrics_cmp.get(primary, {}).get("delta")})
    return updated
