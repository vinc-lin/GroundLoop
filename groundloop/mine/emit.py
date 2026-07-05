"""Emit a mined case to disk in the exact gpuimage-352 layout (docs/type2-evaluation.md §4.4).

Hidden owner-bearing metadata nests under _oracle/ so the invariant-#4 read-spy covers it for free.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_NEGATIVE_CLASSES = {None, "out_of_fleet", "coverage_gap", "insufficient_signal", "not_a_defect"}


@dataclass
class MinedCase:
    case_id: str
    summary: str
    description: str
    logs: list[dict]                 # [{kind, text}]
    owning_repo: str
    expected_files: list[str]
    required_apis: list[str]
    owning_repo_sha: str = ""
    is_answerable: bool = True
    negative_class: str | None = None
    held_out_repo: str | None = None
    case_catalog: list[str] | None = None
    provenance: dict = field(default_factory=dict)
    leakage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def emit_case(root: str, case: MinedCase) -> str:
    if case.negative_class not in _NEGATIVE_CLASSES:
        raise ValueError(f"unknown negative_class: {case.negative_class!r}")
    if case.case_catalog is not None and case.held_out_repo in case.case_catalog:
        raise ValueError("held_out_repo must be EXCLUDED from the per-case catalog")
    d = Path(root) / case.case_id
    log_entries = []
    for i, lg in enumerate(case.logs):
        rel = f"logs/{i:03d}.txt"
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(lg["text"])
        log_entries.append({"path": rel, "kind": lg.get("kind", "other")})
    _write_json(d / "ticket.json", {
        "id": case.case_id, "summary": case.summary, "description": case.description,
        "component": "",  # anti-leak: never the owner
        "status": "Open", "comments": [], "logs": log_entries,
    })
    _write_json(d / "_oracle" / "oracle.json", {
        "owning_repo": case.owning_repo,
        "expected_files": list(case.expected_files),
        "required_apis": list(case.required_apis),
        "owning_repo_sha": case.owning_repo_sha,
        "is_answerable": case.is_answerable,
        "negative_class": case.negative_class,
        "held_out_repo": case.held_out_repo,
    })
    _write_json(d / "_oracle" / "provenance.json", case.provenance)
    _write_json(d / "_oracle" / "leakage.json", case.leakage)
    _write_json(d / "_oracle" / "raw" / "issue.json", case.raw.get("issue", {}))
    _write_json(d / "_oracle" / "raw" / "pr_files.json", case.raw.get("pr_files", []))
    if case.case_catalog is not None:
        _write_json(d / "catalog.json", [{"name": n} for n in case.case_catalog])
    return str(d)


def emit_catalog(root: str, names: list[str]) -> str:
    p = Path(root) / "catalog.json"
    _write_json(p, [{"name": n} for n in names])
    return str(p)
