"""Offline harvester: cluster loop-visible failure cases by a coarse crash SIGNATURE, then mint a
split-firewalled candidate playbook from a cluster.

Grounding rules baked in:
- The signature is the case's single most discriminative signal (top error, else top .so, else the
  next non-empty family) — a coarse key so genuinely-related failures land in one cluster.
- `candidate_from_cluster` only mints a Skill dict for MINING splits (`calib`/`train`); for `eval`/
  `holdout` (or anything else) it returns None. This is the split firewall: no eval/holdout case may
  ever author a playbook that is later scored against eval/holdout (would be a leak).
- The minted dict is repo-agnostic + leak-safe by construction: guidance/provenance are generic
  templates, and a signature that is itself a fleet-owner token is refused (returns None) rather than
  seeding a lookup-table row. The result passes `groundloop.kb.validate.validate_corpus`.

Offline only — no network, no model, no atlas.
"""
from __future__ import annotations

import re

from groundloop.kb.validate import owner_denylist

# Signal families in priority order for the coarse signature (top error, then .so, then the rest).
_SIGNATURE_FAMILIES = ("errors", "libraries", "symbols", "classes", "methods", "packages")

# Split firewall: only these splits may author candidates.
_MINING_SPLITS = frozenset({"calib", "train"})


def _signature_of(signals: dict) -> str:
    """The coarse cluster key: the first non-empty value across the priority families, lowercased."""
    for fam in _SIGNATURE_FAMILIES:
        for val in signals.get(fam) or ():
            if val:
                return str(val).strip().lower()
    return "unknown"


def cluster_by_signature(cases: list[dict]) -> dict[str, list[str]]:
    """Group case ids by coarse crash signature.

    Each case is `{"case_id": str, "signals": {family: [tokens]}}`. Returns
    `{signature: [case_id, ...]}` preserving input order within each group.
    """
    groups: dict[str, list[str]] = {}
    for case in cases:
        cid = case.get("case_id")
        if not cid:
            continue
        sig = _signature_of(case.get("signals") or {})
        groups.setdefault(sig, []).append(cid)
    return groups


def candidate_from_cluster(signature: str, case_ids: list[str], *, split_tag: str) -> dict | None:
    """Mint a candidate Skill dict from a cluster, or None if the split firewall forbids it.

    Returns a `validate_corpus`-clean skill dict ONLY when `split_tag` is a mining split
    (`calib`/`train`); returns None for `eval`/`holdout`/anything else, for an empty signature/cluster,
    or for a signature that is itself a fleet-owner token (can't seed a repo-agnostic playbook).
    """
    if split_tag not in _MINING_SPLITS:
        return None
    sig = str(signature or "").strip()
    if not sig or not case_ids:
        return None
    sig_low = sig.lower()
    if any(tok in sig_low for tok in owner_denylist()):
        return None  # a leaky signature can't seed a repo-agnostic playbook
    slug = re.sub(r"[^a-z0-9]+", "-", sig_low).strip("-") or "signature"
    n = len(case_ids)
    guidance = (
        f"Signature: Failures clustered by the recurring crash signature '{sig}' seen across "
        f"{n} case(s) sharing this top signal.\n"
        f"Localize: Rank source files by the frame, class, or method that raises '{sig}'; begin at "
        f"the first application frame beneath the framework frames.\n"
        f"Fix: Address the root cause behind '{sig}' at that boundary; add the missing lifecycle, "
        f"null, or ownership guard and re-run the reproducing case to confirm."
    )
    return {
        "id": f"harvest-{slug}",
        "provenance": (
            f"Auto-harvested candidate (split={split_tag}) from {n} clustered case(s) "
            f"with signature '{sig}'"
        ),
        "signals": [sig_low],
        "hint_apis": [],
        "guidance": guidance,
        "match": {"any_text": [sig_low]},
    }
