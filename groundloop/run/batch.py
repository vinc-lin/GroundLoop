"""Oracle-blind batch driver for the real loop: for each case, run the frozen run_ticket and persist an
oracle-free run-record. Grading is a separate offline pass (gloop grade-run)."""
from __future__ import annotations

from pathlib import Path

from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.core.workflow import run_ticket
from groundloop.fix.patch import patch_applies
from groundloop.run.dataset import load_cases
from groundloop.run.record import MaterializeOutcome, RunRecordIO


def run_dataset(dataset: str, *, issues, extractor, estate, index, fixer, changes, match_arm: str,
                out: str, extractor_rec=None, cost_model=None, fixer_kind: str = "", mint=None) -> int:
    """`mint`, when given, is called `mint(case_id, signals, locations, patch_diff)` once per case whose
    patch cleanly applies (opt-in; `None` — the default — leaves this function byte-identical to before
    the KB mint hook existed)."""
    Path(out).mkdir(parents=True, exist_ok=True)                      # ChangeSink may write under out/ mid-run
    cases = load_cases(dataset)                                        # never reads _oracle/
    for case in cases:
        c0 = ((cost_model.cost_usd, cost_model.input_tokens, cost_model.output_tokens,
               cost_model.calls) if cost_model else (0.0, 0, 0, 0))    # snapshot cost BEFORE the loop
        rec = run_ticket(case.case_id, issues=issues, extractor=extractor, estate=estate,
                         index=index, fixer=fixer, changes=changes)
        sig = getattr(extractor_rec, "last_signals", None)            # signals the loop just computed
        cost = ({"cost_usd": cost_model.cost_usd - c0[0],
                 "input_tokens": cost_model.input_tokens - c0[1],
                 "output_tokens": cost_model.output_tokens - c0[2],
                 "calls": cost_model.calls - c0[3]} if cost_model else
                {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "calls": 0})
        outcome = None
        if hasattr(estate, "outcome_for"):
            outcome = estate.outcome_for(rec.chosen.name)
        if outcome is None:                                           # non-recording estate fallback
            outcome = MaterializeOutcome(rec.chosen.name, "", False, 0)
        applies = patch_applies(rec.patch.diff, outcome.path) if outcome.present else False
        if mint is not None and applies:
            mint(case.case_id, sig, list(rec.locations), rec.patch.diff)
        bind_kind = "mock" if isinstance(changes, MockGerrit) else "live"
        RunRecordIO.write(f"{out}/runs/{case.case_id}.json", rec, materialize=outcome,
                          match_arm=match_arm, patch_applies=applies,
                          signals=sig, cost=cost, fixer=fixer_kind, bind_kind=bind_kind)
    return len(cases)
