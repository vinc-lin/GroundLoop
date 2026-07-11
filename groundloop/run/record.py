"""Serialize the frozen RunRecord (+ a materialize sidecar) to a loop-only, oracle-free run-record JSON.
The run pass writes it; the offline grade pass reads it. No oracle fields ever appear here."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from groundloop.core.workflow import RunRecord

ORACLE_KEYS = ("owning_repo", "expected_files", "required_apis")


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


class RunRecordIO:
    @staticmethod
    def write(path: str, rec: RunRecord, *, materialize: MaterializeOutcome, match_arm: str,
              patch_applies: bool) -> None:
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
            "events": list(rec.events),
            "materialize": {"repo": materialize.repo, "path": materialize.path,
                            "present": materialize.present, "n_files": materialize.n_files},
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
            materialize=MaterializeOutcome(m["repo"], m["path"], m["present"], m["n_files"]))
