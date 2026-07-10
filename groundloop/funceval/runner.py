"""Functional-bug matching eval: reuse the Stage-1 EvalRunner + grade_all (with by_bug_kind) over a
labeled dataset. Offline oracle reads happen ONLY in grade_all — never in the runner arms."""
from __future__ import annotations

from pathlib import Path

from groundloop.adapters.estate import MockEstate
from groundloop.adapters.mock.jira import MockJira
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.runner import EvalRunner
from groundloop.eval.scorecard import grade_all
from groundloop.funceval.arms import TAU_FUNC, build_functional_arms


def run_funceval(dataset: str, profile_db: str, index_db: str, *, embedder,
                 arms=("functional", "dispatch", "flood", "faultslice", "routing")) -> dict:
    cases = load_cases(dataset)
    catalog_path = str(Path(dataset) / "catalog.json")
    issues = MockJira(dataset)
    estate = MockEstate(catalog_path, dataset + "/_work")
    runner = EvalRunner(issues=issues, estate=estate, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1])
    records = runner.run(cases, build_functional_arms(profile_db, index_db, embedder=embedder, names=arms))
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    return {"attribution": grade_all(records, oracle_by_case=oracle_by_case)}
