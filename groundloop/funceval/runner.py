"""Functional-bug matching eval: reuse the Stage-1 EvalRunner + grade_all (with by_bug_kind) over a
labeled dataset. Offline oracle reads happen ONLY in grade_all (and, for the LOO `component` arm, the
per-case owner read below) — never in the runtime index/extractor modules."""
from __future__ import annotations

from pathlib import Path

from groundloop.adapters.estate import MockEstate
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.component_prior import ComponentPriorIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.domains.android_ivi.component_affinity import ComponentAffinity
from groundloop.domains.android_ivi.component_signals import ComponentExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.abstain import decide
from groundloop.eval.dataset import case_catalog, load_cases, load_eval_oracle
from groundloop.eval.runner import EvalRunner, MatchRecord
from groundloop.eval.scorecard import grade_all
from groundloop.funceval.arms import TAU_FUNC, build_functional_arms


class _LOOView:
    """Per-case leave-one-out affinity view: excludes this case's own (component, owner) contribution.
    Eval/grader-side ONLY (it knows the owner); never used on the production runtime path."""

    def __init__(self, affinity: ComponentAffinity, owner: str):
        self._aff = affinity
        self._owner = owner

    def affinity(self, component: str) -> dict:
        return self._aff.affinity(component, exclude=self._owner)


def _component_records(cases, issues, global_catalog, index_db, affinity, *, loo: bool):
    extractor = ComponentExtractor(AndroidSignalExtractor())
    base = AtlasIndex(index_db)
    recs = []
    for case in cases:
        catalog = case_catalog(case) or global_catalog
        ticket = issues.fetch(case.case_id)
        view = affinity
        if loo:                                            # grader-side owner read (offline eval only)
            owner = load_eval_oracle(case).owning_repo
            view = _LOOView(affinity, owner)
        idx = ComponentPriorIndex(base, view)
        ranked = idx.rank_repos(extractor.extract(ticket.logs, ticket), catalog)
        d = decide(ranked, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1])
        recs.append(MatchRecord(case.case_id, "component", [r.repo.name for r in ranked],
                                [r.score for r in ranked], d.predicted, d.margin, d.top1_score))
    return recs


def run_funceval(dataset: str, profile_db: str, index_db: str, *, embedder,
                 arms=("functional", "dispatch", "flood", "faultslice", "routing"),
                 affinity_path: str | None = None, loo: bool = False) -> dict:
    cases = load_cases(dataset)
    catalog_path = str(Path(dataset) / "catalog.json")
    issues = MockJira(dataset)
    estate = MockEstate(catalog_path, dataset + "/_work")
    global_catalog = estate.catalog()
    records = []
    std_arms = tuple(a for a in arms if a != "component")
    if std_arms:
        runner = EvalRunner(issues=issues, estate=estate, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1])
        records += runner.run(cases, build_functional_arms(profile_db, index_db, embedder=embedder,
                                                            names=std_arms))
    if "component" in arms:
        if affinity_path is None:
            raise ValueError("the 'component' arm requires --affinity")
        affinity = ComponentAffinity.load(affinity_path)
        records += _component_records(cases, issues, global_catalog, index_db, affinity, loo=loo)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    return {"attribution": grade_all(records, oracle_by_case=oracle_by_case)}
