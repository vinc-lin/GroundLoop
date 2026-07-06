"""RepairPlan — the grounded, structured artifact the PlanningFixEngine emits between localize and
patch. Pure / oracle-free. See docs/superpowers/specs/2026-07-07-plan-format-fix-stage-design.md."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanTarget:
    file: str
    why: str = ""
    symbol: str | None = None


@dataclass(frozen=True)
class RepairPlan:
    root_cause: str
    targets: tuple[PlanTarget, ...]
    required_apis: tuple[str, ...] = ()
    strategy: str = ""
    citations: tuple[str, ...] = ()
    risks: str = ""
    confidence: float = 0.0
    abstain: bool = False


_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def parse_plan(text: str) -> RepairPlan | None:
    """Tolerant decode of a model plan (```json fenced or a bare {...} span). Returns None on any
    failure — the caller treats None as a gate failure (re-plan, then abstain). Never raises."""
    if not text or not text.strip():
        return None
    m = _JSON_FENCE.search(text)
    raw = m.group(1) if m else text
    if not m:
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1 or j < i:
            return None
        raw = raw[i:j + 1]
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    targets: list[PlanTarget] = []
    for t in d.get("targets", []) or []:
        if isinstance(t, dict) and t.get("file"):
            targets.append(PlanTarget(file=str(t["file"]), why=str(t.get("why", "")),
                                      symbol=(str(t["symbol"]) if t.get("symbol") else None)))
        elif isinstance(t, str) and t.strip():
            targets.append(PlanTarget(file=t.strip()))
    return RepairPlan(
        root_cause=str(d.get("root_cause", "")).strip(),
        targets=tuple(targets),
        required_apis=tuple(str(a) for a in (d.get("required_apis", []) or []) if str(a).strip()),
        strategy=str(d.get("strategy", "")).strip(),
        citations=tuple(str(c) for c in (d.get("citations", []) or []) if str(c).strip()),
        risks=str(d.get("risks", "")).strip(),
        confidence=float(d.get("confidence", 0.0) or 0.0),
        abstain=bool(d.get("abstain", False)),
    )


def plan_to_dict(plan: RepairPlan) -> dict:
    return {
        "root_cause": plan.root_cause,
        "targets": [{"file": t.file, "symbol": t.symbol, "why": t.why} for t in plan.targets],
        "required_apis": list(plan.required_apis),
        "strategy": plan.strategy,
        "citations": list(plan.citations),
        "risks": plan.risks,
        "confidence": plan.confidence,
        "abstain": plan.abstain,
    }
