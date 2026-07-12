"""Task 3: PlanningFixEngine wired into `gloop run` as the default --fixer plan (guarded)."""
from __future__ import annotations


def test_build_run_fixer_plan_returns_planning_engine(monkeypatch):
    monkeypatch.setenv("KLOOP_PRODUCE_API_KEY", "x")
    from groundloop.cli import _build_run_fixer
    from groundloop.adapters.fix.planning import PlanningFixEngine
    fixer, model = _build_run_fixer("plan", max_replan=2)
    assert isinstance(fixer, PlanningFixEngine) and fixer.max_replan == 2
    assert model is not None                          # the GatewayModel handle for cost capture (later task)


def test_build_run_fixer_canned_returns_none_model():
    from groundloop.cli import _build_run_fixer
    fixer, model = _build_run_fixer("canned")
    assert model is None


def test_run_fixer_default_is_plan():
    from groundloop.cli import build_parser
    ns = build_parser().parse_args(["run", "--dataset", "d", "--catalog", "c", "--work", "w",
                                    "--changes", "ch", "--index-db", "a.db", "--out", "o", "--repos", "r"])
    assert ns.fixer == "plan"
