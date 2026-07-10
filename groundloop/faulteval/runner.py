"""Fault-localization + attribution eval over a faultlog dataset. Reuses the Stage-1 EvalRunner for
attribution (recall@1 == attribution_recall) and grades fault_localization separately. Offline oracle
reads happen ONLY in grade_* / _fault_oracle — never in the runner arms."""
from __future__ import annotations

import json
from pathlib import Path

from groundloop.adapters.estate import MockEstate
from groundloop.adapters.mock.jira import MockJira
from groundloop.domains.android_ivi.fault_signals import fault_record_for_logs
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.runner import EvalRunner
from groundloop.eval.scorecard import grade_all
from groundloop.faulteval.arms import build_fault_arms
from groundloop.faulteval.metrics import FaultLocRecord, grade_fault_localization


def _fault_oracle(case) -> dict:
    raw = json.loads((Path(case.case_dir) / "_oracle" / "oracle.json").read_text())
    return {"fault_frame": raw.get("fault_frame"), "fault_file": raw.get("fault_file")}


def run_faulteval(dataset: str, index_db: str, *, arms=("flood", "faultslice", "routing")) -> dict:
    cases = load_cases(dataset)
    catalog_path = str(Path(dataset) / "catalog.json")
    issues = MockJira(dataset)
    estate = MockEstate(catalog_path, dataset + "/_work")
    runner = EvalRunner(issues=issues, estate=estate, tau_margin=1.0, tau_score=1.0)
    records = runner.run(cases, build_fault_arms(index_db, names=arms))
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    attribution = grade_all(records, oracle_by_case=oracle_by_case)

    loc_recs, loc_oracle = [], {}
    for c in cases:
        ticket = issues.fetch(c.case_id)
        fr = fault_record_for_logs(ticket.logs)
        loc_recs.append(FaultLocRecord(
            case_id=c.case_id,
            top_frame_key=fr.top_frame.key() if fr and fr.top_frame else None,
            blamed_keys=[f.key() for f in fr.frames] if fr else [],
            fault_file_hint=fr.fault_file_hint if fr else None,
            confidence=fr.confidence if fr else "NONE"))
        loc_oracle[c.case_id] = _fault_oracle(c)
    localization = grade_fault_localization(loc_recs, oracle_by_case=loc_oracle)
    return {"attribution": attribution, "localization": localization}
