"""Serialize the frozen RunRecord (+ a materialize sidecar) to a loop-only, oracle-free run-record JSON.
The run pass writes it; the offline grade pass reads it. No oracle fields ever appear here."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from groundloop.core.workflow import RunRecord

ORACLE_KEYS = ("owning_repo", "expected_files", "required_apis")


def _signals_to_dict(signals) -> dict:
    """Serialize a Signals-shaped object to a plain JSON-able dict. None -> {}. Frozen dataclass ->
    dataclasses.asdict (tuples serialize fine); otherwise fall back to its __dict__."""
    if signals is None:
        return {}
    if dataclasses.is_dataclass(signals) and not isinstance(signals, type):
        return dataclasses.asdict(signals)
    return dict(vars(signals))


@dataclass(frozen=True)
class MaterializeOutcome:
    repo: str
    path: str
    present: bool
    n_files: int


@dataclass(frozen=True)
class RunDoc:
    ticket_id: str
    match_arm: str
    ranked: list[dict]
    chosen: str
    locations: list[str]
    patch: dict
    patch_applies: bool
    change_id: str
    bound: bool
    events: list[str]
    materialize: MaterializeOutcome
    signals: dict
    cost_usd: float
    tokens: dict
    model_calls: int
    fixer: str
    bind_kind: str = "mock"


class RunRecordIO:
    @staticmethod
    def write(path: str, rec: RunRecord, *, materialize: MaterializeOutcome, match_arm: str,
              patch_applies: bool, signals=None, cost=None, fixer: str = "",
              bind_kind: str = "mock") -> None:
        blob = {
            "ticket_id": rec.ticket_id,
            "match_arm": match_arm,
            "ranked": [{"repo": rs.repo.name, "score": rs.score, "evidence": list(rs.evidence)}
                       for rs in rec.ranked],
            "chosen": rec.chosen.name,
            "locations": list(rec.locations),
            "patch": {"diff": rec.patch.diff, "files": list(rec.patch.files)},
            "patch_applies": bool(patch_applies),
            "change_id": rec.change.change_id,
            "bound": rec.bound,
            "bind_kind": bind_kind,
            "events": list(rec.events),
            "materialize": {"repo": materialize.repo, "path": materialize.path,
                            "present": materialize.present, "n_files": materialize.n_files},
            "signals": _signals_to_dict(signals),
            "cost_usd": (cost or {}).get("cost_usd", 0.0),
            "tokens": {"input": (cost or {}).get("input_tokens", 0),
                       "output": (cost or {}).get("output_tokens", 0)},
            "model_calls": (cost or {}).get("calls", 0),
            "fixer": fixer,
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(blob, indent=2, ensure_ascii=False))

    @staticmethod
    def read(path: str) -> RunDoc:
        raw = json.loads(Path(path).read_text())
        m = raw["materialize"]
        return RunDoc(
            ticket_id=raw["ticket_id"], match_arm=raw["match_arm"], ranked=raw["ranked"],
            chosen=raw["chosen"], locations=raw["locations"], patch=raw["patch"],
            patch_applies=raw["patch_applies"], change_id=raw["change_id"], bound=raw["bound"],
            events=raw["events"],
            materialize=MaterializeOutcome(m["repo"], m["path"], m["present"], m["n_files"]),
            signals=raw.get("signals", {}), cost_usd=raw.get("cost_usd", 0.0),
            tokens=raw.get("tokens", {}), model_calls=raw.get("model_calls", 0),
            fixer=raw.get("fixer", ""), bind_kind=raw.get("bind_kind", "mock"))
