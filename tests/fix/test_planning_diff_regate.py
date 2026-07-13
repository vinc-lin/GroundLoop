"""End-to-end anti-leak re-gate for PlanningFixEngine: the EXECUTED diff (not just the plan) must
touch only files inside the localize candidate set, else the engine abstains (empty Patch). This
guards the production default fixer against an in-scope plan that nonetheless emits an out-of-scope
diff (docs/fix-loop.md anti-leak; consistent with plan-level check_plan_in_world scope enforcement)."""
from __future__ import annotations

from groundloop.adapters.fix.planning import PlanningFixEngine
from groundloop.core.types import RepoRef, Ticket, WorkTree


class _ScriptedModel:
    """Deterministic model: returns scripted replies in order (last repeats)."""
    def __init__(self, replies):
        self._r = list(replies)
        self.i = 0

    def complete(self, prompt):
        r = self._r[self.i]
        self.i = min(self.i + 1, len(self._r) - 1)
        return r


def _wt(tmp_path):
    (tmp_path / "in_scope.py").write_text("def fix_me():\n    return 1\n")
    return WorkTree(repo=RepoRef(name="r"), path=str(tmp_path))


def _ticket():
    return Ticket(id="c1", summary="crash", description="npe", logs=())


# Plan cites in_scope.py + symbol fix_me (both real on disk) -> plan gate passes, engine reaches execute.
_GOOD_PLAN = ('{"root_cause":"npe","targets":[{"file":"in_scope.py","symbol":"fix_me"}],'
              '"required_apis":[],"strategy":"guard","citations":["in_scope.py"]}')
_DIFF_OUT = ("```diff\n--- a/other/secret.py\n+++ b/other/secret.py\n@@ -1 +1 @@\n"
             "-x = 1\n+x = 2\n```")
_DIFF_IN = ("```diff\n--- a/in_scope.py\n+++ b/in_scope.py\n@@ -1,2 +1,2 @@\n"
            "-def fix_me():\n-    return 1\n+def fix_me():\n+    return 2\n```")


def test_out_of_scope_diff_abstains(tmp_path):
    m = _ScriptedModel([_GOOD_PLAN, _DIFF_OUT])
    plan, patch, meta = PlanningFixEngine(m).propose_with_plan(
        _wt(tmp_path), _ticket(), ["in_scope.py"])
    assert plan is not None                              # plan grounded (gate passed)
    assert patch.diff == ""                              # executed diff left scope -> abstained
    assert meta.get("abstain_reason") == "diff_out_of_scope"


def test_in_scope_diff_returned(tmp_path):
    m = _ScriptedModel([_GOOD_PLAN, _DIFF_IN])
    plan, patch, meta = PlanningFixEngine(m).propose_with_plan(
        _wt(tmp_path), _ticket(), ["in_scope.py"])
    assert patch.diff and patch.files == ("in_scope.py",)
    assert "abstain_reason" not in meta
