"""Dataset loading for the Type-2 eval. `load_cases` is oracle-blind; only `load_oracle`
(used solely by the offline scorecard) touches _oracle/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from groundloop.core.types import Oracle

_ORACLE_KEYS = ("owning_repo", "expected_files", "required_apis")


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


def load_oracle(case: CaseRef) -> Oracle:
    """Read the hidden oracle. OFFLINE-GRADE ONLY — never call from the runner/arm path."""
    import json
    raw = json.loads((Path(case.case_dir) / "_oracle" / "oracle.json").read_text())
    return Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                     for k, v in raw.items() if k in _ORACLE_KEYS})
