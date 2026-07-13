"""RepairPlan — the grounded, structured artifact the PlanningFixEngine emits between localize and
patch. Pure / oracle-free. See docs/superpowers/specs/2026-07-07-plan-format-fix-stage-design.md."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from groundloop.fix.patch import norm_path


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


def _as_float(v) -> float:
    """Coerce a model-supplied confidence to float; never raise (a string/list/dict -> 0.0)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _as_list(v) -> list:
    """Coerce a JSON value to a list before iterating; a bare str/dict/etc. -> [] (never char-iterate)."""
    return list(v) if isinstance(v, (list, tuple)) else []


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
    for t in _as_list(d.get("targets")):
        if isinstance(t, dict) and t.get("file"):
            targets.append(PlanTarget(file=str(t["file"]), why=str(t.get("why", "")),
                                      symbol=(str(t["symbol"]) if t.get("symbol") else None)))
        elif isinstance(t, str) and t.strip():
            targets.append(PlanTarget(file=t.strip()))
    return RepairPlan(
        root_cause=str(d.get("root_cause", "")).strip(),
        targets=tuple(targets),
        required_apis=tuple(str(a) for a in _as_list(d.get("required_apis")) if str(a).strip()),
        strategy=str(d.get("strategy", "")).strip(),
        citations=tuple(str(c) for c in _as_list(d.get("citations")) if str(c).strip()),
        risks=str(d.get("risks", "")).strip(),
        confidence=_as_float(d.get("confidence", 0.0)),
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


@dataclass(frozen=True)
class PlanCheck:
    ok: bool
    failures: tuple[str, ...]
    n_citations: int
    n_resolved: int


def _word(token: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", text) is not None


def check_plan_in_world(plan: RepairPlan | None, worktree_path: str,
                        candidates: Sequence[str]) -> PlanCheck:
    """Oracle-blind gate: every claim must cite reality. Checks (a) each target file exists in the
    work-tree, (b) each target is within the localize candidate set, (c) each target.symbol /
    required_api appears textually in an existing target file, (d) root_cause/strategy/targets present.
    Citations = target files + symbols + required_apis; groundedness = resolved / cited. Scope is
    checked BEFORE any disk read: an out-of-scope, absolute, or `..`-traversal target is NEVER read
    and NEVER counts toward n_resolved (anti-leak — a `../<case>/_oracle/...` path cannot leak in)."""
    if plan is None:
        return PlanCheck(False, ("unparseable_plan",), 0, 0)
    if plan.abstain:
        return PlanCheck(False, ("model_abstained",), 0, 0)
    failures: list[str] = []
    cand = {norm_path(c) for c in candidates}
    n_cit = n_res = 0
    text_by_file: dict[str, str] = {}
    if not plan.root_cause:
        failures.append("empty_root_cause")
    if not plan.strategy:
        failures.append("empty_strategy")
    if not plan.targets:
        failures.append("no_targets")
    for t in plan.targets:
        n_cit += 1
        tp = Path(t.file)
        in_scope = norm_path(t.file) in cand and not tp.is_absolute() and ".." not in tp.parts
        if in_scope:                                  # only read files we've proven are in-scope + safe
            p = Path(worktree_path) / t.file
            if p.is_file():
                n_res += 1
                text_by_file[t.file] = p.read_text(errors="replace")
            else:
                failures.append(f"target_file_missing:{t.file}")
        else:
            failures.append(f"target_out_of_scope:{t.file}")
        if t.symbol:
            n_cit += 1
            if t.file in text_by_file and _word(t.symbol, text_by_file[t.file]):
                n_res += 1
            else:
                failures.append(f"symbol_unresolved:{t.symbol}")
    for a in plan.required_apis:
        n_cit += 1
        if any(_word(a, txt) for txt in text_by_file.values()):
            n_res += 1
        else:
            failures.append(f"api_unresolved:{a}")
    return PlanCheck(not failures, tuple(failures), n_cit, n_res)


def plan_groundedness(check: PlanCheck) -> float:
    return (check.n_resolved / check.n_citations) if check.n_citations else 0.0
