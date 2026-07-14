"""Staged per-item attribution + lifecycle governance (design spec §5.4/§5.5). Three primitives:
  * screen_knowledge (C2) — a cheap, ORACLE-BLIND directional screen over a composite of the plan archive's
    per-case `groundedness` + `patch_applies` -> a shortlist of promising/suspicious items (correlational;
    prioritizes, never promotes);
  * lofo_knowledge (C3) — leave-one-ITEM-out ablation Δ (the knowledge-granular LOFO);
  * attribute_and_govern (C4) — LOFO-confirm vs the per-item placebo -> accept_grounded two-sided verdict
    -> apply_verdict per item, bridged onto the Knowledge via a small KnowledgeRecord adapter.
The SCREEN reads only the archive (no oracle, no new spend); the CONFIRM re-runs the plan-format fix eval
whose grade_fix_all is the sole, offline oracle read. The loop stays oracle-blind throughout."""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterable
from pathlib import Path

from groundloop.fixeval.compare import accept_grounded, compare, compare_metrics
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.lifecycle import TIERS, apply_verdict


def load_archive(plans_dir: str) -> list[dict]:
    """Load every per-case plan payload written by fixeval/archive.archive_plans (<dir>/*.json). A missing
    dir is an empty archive (nothing to attribute yet), not an error; a malformed file is skipped, not
    fatal."""
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


def _case_signal(payload: dict) -> float | None:
    """The archive's per-case ORACLE-BLIND screen signal: a documented composite of the two grounded fields
    the loop already writes — `0.5*groundedness + 0.5*(patch_applies?1:0)`. groundedness alone would score an
    item that lifts `patch_applies` without moving groundedness at 0 (filtered before LOFO at any
    threshold>0); the composite catches it. Both fields are oracle-blind (in the archive, no oracle read).
    None when groundedness is absent (e.g. an abstain-only case) -> excluded from the mean."""
    outcome = payload.get("outcome") or {}
    g = outcome.get("groundedness")
    if not isinstance(g, (int, float)):
        return None
    return 0.5 * float(g) + 0.5 * (1.0 if outcome.get("patch_applies") else 0.0)


def screen_knowledge(archive: Iterable[dict], knowledge: dict[str, Knowledge], *,
                     threshold: float = 0.0, min_fired: int = 1) -> list[str]:
    """Cheap oracle-blind directional screen (spec §5.4). Pinned formula, per LIVE item (tier in TIERS):
        screen_lift = mean(signal | item FIRED) - mean(signal | item did NOT fire)
    where `signal` is the oracle-blind composite of groundedness + patch_applies (see _case_signal).
    Shortlist = items with |screen_lift| >= threshold (promising OR suspicious), sorted by |screen_lift|
    desc (so a --max-lofo cap keeps the strongest signals). A retired / non-TIER item is skipped (the
    KnowledgeRegistry never fires it, so its LOFO run would be a no-op — no spend on the dead). No firing case
    or no baseline case -> no contrast -> skipped. Correlational only: PRIORITIZES the shortlist, never
    promotes."""
    rows = list(archive)
    scored: list[tuple[float, str]] = []
    for kid, item in knowledge.items():
        if item.tier not in TIERS:                        # retired/dead never re-enters the LOFO shortlist
            continue
        fv = [g for g in (_case_signal(p) for p in rows
                          if kid in (p.get("fired_knowledge") or [])) if g is not None]
        bv = [g for g in (_case_signal(p) for p in rows
                          if kid not in (p.get("fired_knowledge") or [])) if g is not None]
        if not fv or not bv or len(fv) < min_fired:       # guard min_fired<=0 too (no ZeroDivisionError)
            continue
        lift = sum(fv) / len(fv) - sum(bv) / len(bv)
        if abs(lift) >= threshold:
            scored.append((abs(lift), kid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [kid for _, kid in scored]


def lofo_knowledge(knowledge_ids: Iterable[str], run_fn: Callable[[frozenset[str]], float]) -> dict[str, float]:
    """Leave-one-ITEM-out attribution — the knowledge-granular LOFO.
    baseline = run_fn(full_set); for each item, Δ = baseline - run_fn(full_set without that item). A
    POSITIVE Δ means removing the item dropped the metric (the item was load-bearing). `run_fn(set[str])
    -> float` is a driver-supplied closure that re-runs the grounded fix eval with exactly that item set
    (grade_fix_all inside it is the sole, offline oracle read). Returns {knowledge_id: Δ}, first-seen
    order."""
    ids = list(dict.fromkeys(knowledge_ids))        # de-dup, preserve first-seen order
    full = frozenset(ids)
    baseline = run_fn(full)
    return {kid: baseline - run_fn(full - {kid}) for kid in ids}


@dataclasses.dataclass(frozen=True)
class KnowledgeRecord:
    """The minimal record kb/lifecycle.apply_verdict reads/replaces — a bridge so the REUSED tier ladder
    can govern a Knowledge item whose fail_count/demotions live inside its evidence bag."""
    id: str
    tier: str
    fail_count: int = 0
    demotions: tuple[str, ...] = ()


def to_record(knowledge: Knowledge) -> KnowledgeRecord:
    ev = knowledge.evidence or {}
    return KnowledgeRecord(id=knowledge.id, tier=knowledge.tier, fail_count=int(ev.get("fail_count", 0)),
                           demotions=tuple(ev.get("demotions", ())))


def promote_or_retire(knowledge: Knowledge, passed: bool, *, hysteresis: int = 2,
                      measured_lift: dict | None = None, wilson95=None,
                      validating_case_ids: Iterable[str] | None = None) -> Knowledge:
    """Fold one per-item verdict into the tier ladder and return the updated (new) Knowledge. `passed` ->
    apply_verdict promotes one rung + resets the streak; a failing streak reaching `hysteresis` demotes one
    rung, EXCEPT at the bottom rung (candidate) where it RETIRES the item (terminal — 'retired' is outside
    TIERS, so the Phase-B KnowledgeRegistry never fires it again). Writes tier + evidence (fail_count,
    demotions, and optional measured_lift/wilson95/validating_case_ids) back onto the frozen Knowledge."""
    if knowledge.tier not in TIERS:                   # retired (or any non-TIER) is terminal
        return knowledge
    rec = to_record(knowledge)
    retiring = (not passed and rec.tier == TIERS[0] and rec.fail_count + 1 >= hysteresis)
    if retiring:
        new_tier, new_fail = "retired", 0
        new_demotions = rec.demotions + (f"{rec.tier}->retired",)
    else:
        nr = apply_verdict(rec, passed, hysteresis=hysteresis)
        new_tier, new_fail, new_demotions = nr.tier, nr.fail_count, nr.demotions
    ev = dict(knowledge.evidence or {})
    ev["fail_count"] = new_fail
    ev["demotions"] = list(new_demotions)
    if measured_lift is not None:
        ev["measured_lift"] = measured_lift
    if wilson95 is not None:
        ev["wilson95"] = wilson95
    if validating_case_ids is not None:
        ev["validating_case_ids"] = list(validating_case_ids)
    return dataclasses.replace(knowledge, tier=new_tier, evidence=ev)


def _metric_value(card: dict, key: str) -> float:
    m = card.get(key)
    v = m.get("value") if isinstance(m, dict) else m
    return float(v) if isinstance(v, (int, float)) else 0.0


def attribute_and_govern(knowledge: dict[str, Knowledge], shortlist: Iterable[str],
                         run_card_fn: Callable[[frozenset[str]], dict], *,
                         primary: str = "plan_target_recall@1", cost_budget: float | None = None,
                         hysteresis: int = 2) -> dict[str, Knowledge]:
    """Confirm each shortlisted candidate causally, then govern its tier — one item at a time (spec §5.5).
    `run_card_fn(knowledge_id_set) -> eval-arm scorecard dict` re-runs the grounded fix eval with EXACTLY
    that item set injected (candidates + their per-item placebos, resolved by the driver's pool) and returns
    the arm's grounded metrics; grade_fix_all inside it is the sole, offline oracle read. Per item:
      * LOFO Δ (C3) over the active shortlist — the item must be load-bearing (Δ > 0);
      * placebo-swap comparison — the item arm (head) vs the arm with the item replaced by its
        length-matched placebo (base, same firing set) -> accept_grounded's two-sided grounded gate;
    promote iff BOTH pass; else fail -> promote_or_retire records the streak/retirement. Returns the full
    updated store (non-shortlisted AND retired/non-TIER items pass through unchanged)."""
    valid = [kid for kid in dict.fromkeys(shortlist) if kid in knowledge and knowledge[kid].tier in TIERS]
    active = frozenset(valid)                                               # loop-invariant; never rebinds

    # Memoize the (expensive, live) fix-eval by item set: head, the LOFO baseline (== head's set), and
    # every per-item head collapse to ONE run per distinct set. Mirrors _build_attribute_run_card_fn's
    # hoisted baseline — bounds live spend to 1 + one placebo-swap run per shortlisted item.
    _cache: dict[frozenset[str], dict] = {}

    def card(s: frozenset[str]) -> dict:
        key = frozenset(s)
        if key not in _cache:
            _cache[key] = run_card_fn(key)
        return _cache[key]

    def metric_fn(s: frozenset[str]) -> float:
        return _metric_value(card(s), primary)

    deltas = lofo_knowledge(valid, metric_fn)                              # C3: leave-one-item-out Δ
    head = card(active)                                                    # item present (loop-invariant)
    updated = dict(knowledge)
    for kid in valid:
        pid = "placebo-" + kid
        base = card((active - {kid}) | {pid})                              # item swapped for its placebo
        metrics_cmp = compare_metrics(base, head)
        resolved_cmp = compare(base.get("resolved_by_case", {}), head.get("resolved_by_case", {}))
        verdict = accept_grounded(metrics_cmp, resolved_cmp, cost_budget=cost_budget)
        passed = bool(verdict["accepted"]) and deltas.get(kid, 0.0) > 0    # load-bearing AND two-sided-clean
        updated[kid] = promote_or_retire(
            knowledge[kid], passed, hysteresis=hysteresis,
            measured_lift={"lofo_delta": deltas.get(kid, 0.0),
                           primary: metrics_cmp.get(primary, {}).get("delta")})
    return updated
