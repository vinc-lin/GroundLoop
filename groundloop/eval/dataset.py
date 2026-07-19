"""Dataset loading for the Type-2 eval. `load_cases` and `case_catalog` are oracle-blind (moved to the
product surface `groundloop.run.dataset`, re-exported here for compatibility); only `load_oracle` /
`load_eval_oracle` (used solely by the offline scorecard) touch _oracle/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from groundloop.core.types import Oracle
from groundloop.run.dataset import CaseRef, case_catalog, load_cases  # noqa: F401  (moved to product surface)

_ORACLE_KEYS = ("owning_repo", "expected_files", "required_apis")


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
