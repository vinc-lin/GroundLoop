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

import json
from collections.abc import Callable, Iterable
from pathlib import Path

from groundloop.kb.claim import Claim


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
