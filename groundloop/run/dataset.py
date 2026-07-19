"""Oracle-free case/catalog loaders — the product-surface half of the old eval/dataset.py (Core/Labs
boundary). Reads the case dir's ticket/catalog, NEVER the hidden _oracle/. The oracle side (load_eval_oracle,
EvalOracle) stays in eval/dataset.py (labs)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaseRef:
    case_id: str
    case_dir: str


def load_cases(root: str) -> list[CaseRef]:
    """Discover case dirs (those containing ticket.json). Never reads _oracle/."""
    out: list[CaseRef] = []
    for d in sorted(Path(root).iterdir()):
        if d.is_dir() and (d / "ticket.json").is_file():
            out.append(CaseRef(case_id=d.name, case_dir=str(d)))
    return out


def case_catalog(case: CaseRef):
    """Loop-visible per-case candidate catalog (a catalog.json in the case dir), or None to fall back
    to the estate's global catalog. Used for OOF hold-out — the owner is removed from THIS ticket's
    candidate list. Reads only the loop-visible catalog.json, never _oracle/."""
    import json
    from groundloop.core.types import RepoRef
    p = Path(case.case_dir) / "catalog.json"
    if not p.is_file():
        return None
    return [RepoRef(r["name"]) for r in json.loads(p.read_text())]
