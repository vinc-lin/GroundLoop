"""Oracle-blind batch driver for the real loop: for each case, run the frozen run_ticket and persist an
oracle-free run-record. Grading is a separate offline pass (gloop grade-run)."""
from __future__ import annotations

from pathlib import Path

from groundloop.core.workflow import run_ticket
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.patch import patch_applies
from groundloop.run.record import MaterializeOutcome, RunRecordIO


def run_dataset(dataset: str, *, issues, extractor, estate, index, fixer, changes, match_arm: str,
                out: str) -> int:
    Path(out).mkdir(parents=True, exist_ok=True)                      # ChangeSink may write under out/ mid-run
    cases = load_cases(dataset)                                        # never reads _oracle/
    for case in cases:
        rec = run_ticket(case.case_id, issues=issues, extractor=extractor, estate=estate,
                         index=index, fixer=fixer, changes=changes)
        outcome = None
        if hasattr(estate, "outcome_for"):
            outcome = estate.outcome_for(rec.chosen.name)
        if outcome is None:                                           # non-recording estate fallback
            outcome = MaterializeOutcome(rec.chosen.name, "", False, 0)
        applies = patch_applies(rec.patch.diff, outcome.path) if outcome.present else False
        RunRecordIO.write(f"{out}/runs/{case.case_id}.json", rec, materialize=outcome,
                          match_arm=match_arm, patch_applies=applies)
    return len(cases)
