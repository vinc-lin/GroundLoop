"""Dataset loading for the Type-2 eval. `load_cases` and `case_catalog` are oracle-blind; only
`load_oracle` / `load_eval_oracle` (used solely by the offline scorecard) touch _oracle/."""
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


@dataclass(frozen=True)
class EvalOracle:
    """The eval layer's view of the hidden oracle: the frozen-core owner + the negative-case fields
    (is_answerable / negative_class) that ride as EXTRA keys in oracle.json and are never read by the
    frozen core.types.Oracle. OFFLINE-GRADE ONLY."""
    owning_repo: str
    is_answerable: bool = True
    negative_class: str | None = None
    bug_kind: str | None = None                 # 'crash' | 'functional' | None (offline-only split)
    expected_files: tuple[str, ...] = ()
    required_apis: tuple[str, ...] = ()


def load_eval_oracle(case: CaseRef) -> EvalOracle:
    """Read the hidden oracle including the negative-case fields. OFFLINE-GRADE ONLY — never call
    from the runner/arm path (it reads _oracle/)."""
    import json
    raw = json.loads((Path(case.case_dir) / "_oracle" / "oracle.json").read_text())
    return EvalOracle(
        owning_repo=raw["owning_repo"],
        is_answerable=bool(raw.get("is_answerable", True)),
        negative_class=raw.get("negative_class"),
        bug_kind=raw.get("bug_kind"),
        expected_files=tuple(raw.get("expected_files", [])),
        required_apis=tuple(raw.get("required_apis", [])),
    )


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
