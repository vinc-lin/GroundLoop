# tests/fixeval/test_planning_engine.py
from groundloop.core.types import RepoRef, Ticket, WorkTree
from groundloop.adapters.fix.planning import PlanningFixEngine


class SeqModel:
    """Deterministic sequential model: returns scripted responses in order (last repeats)."""
    def __init__(self, responses):
        self._r = list(responses)
        self.i = 0
        self.cost_usd = 0.0

    def complete(self, prompt: str) -> str:
        r = self._r[min(self.i, len(self._r) - 1)]
        self.i += 1
        return r


def _wt(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "F.java").write_text("class F { void onBind(){ } }")
    return WorkTree(repo=RepoRef(name="r"), path=str(tmp_path))   # core WorkTree needs a RepoRef


def _ticket():
    return Ticket(id="c1", summary="crash", description="npe", logs=())   # core Ticket ctor


_GOOD_PLAN = ('{"root_cause":"npe","targets":[{"file":"src/F.java","symbol":"onBind"}],'
              '"required_apis":[],"strategy":"guard","citations":["src/F.java"]}')
_DIFF = "```diff\n--- a/src/F.java\n+++ b/src/F.java\n@@ -1 +1 @@\n-class F { void onBind(){ } }\n+class F { void onBind(){ if(true){} } }\n```"


def test_happy_path_plan_then_patch(tmp_path):
    m = SeqModel([_GOOD_PLAN, _DIFF])
    eng = PlanningFixEngine(m)
    plan, patch, meta = eng.propose_with_plan(_wt(tmp_path), _ticket(), ["src/F.java"])
    assert plan is not None and patch.diff.startswith("--- a/src/F.java")
    assert meta["replans"] == 0 and meta["groundedness"] == 1.0
    assert m.i == 2                               # exactly two model calls


def test_replan_recovers_from_hallucination(tmp_path):
    bad = '{"root_cause":"x","targets":[{"file":"src/Ghost.java"}],"strategy":"s"}'
    m = SeqModel([bad, _GOOD_PLAN, _DIFF])
    plan, patch, meta = PlanningFixEngine(m, max_replan=1).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff and meta["replans"] == 1
    assert meta["groundedness"] == 1.0            # groundedness reflects the FINAL recovered plan


def test_unparseable_plan_abstains(tmp_path):
    m = SeqModel(["not json", "not json"])
    plan, patch, meta = PlanningFixEngine(m, max_replan=1).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff == ""                       # never grounds -> honest refusal, no execute call


def test_persistent_hallucination_abstains(tmp_path):
    bad = '{"root_cause":"x","targets":[{"file":"src/Ghost.java"}],"strategy":"s"}'
    m = SeqModel([bad, bad, _DIFF])
    plan, patch, meta = PlanningFixEngine(m, max_replan=1).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff == ""                       # abstain — no execute call
    assert m.i == 2                               # 2 plan calls, patch never requested


def test_model_abstain_short_circuits(tmp_path):
    m = SeqModel(['{"abstain":true,"root_cause":"","targets":[],"strategy":""}', _DIFF])
    plan, patch, meta = PlanningFixEngine(m, max_replan=0).propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff == "" and m.i == 1


def test_satisfies_fixengine_propose(tmp_path):
    patch = PlanningFixEngine(SeqModel([_GOOD_PLAN, _DIFF])).propose(_wt(tmp_path), _ticket(), ["src/F.java"])
    assert patch.diff.startswith("--- a/src/F.java")


class RecModel(SeqModel):
    """SeqModel that also records every prompt (for asserting where a preamble lands)."""
    def __init__(self, responses):
        super().__init__(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return super().complete(prompt)


def test_execute_prepends_preamble_when_set(tmp_path):
    # a code-understanding preamble (skills/knowledge/CodeWiki/CBM) must reach PATCH-WRITING, not just plan.
    m = RecModel([_GOOD_PLAN, _DIFF])
    PlanningFixEngine(m, preamble="# FIXCTX injected").propose_with_plan(
        _wt(tmp_path), _ticket(), ["src/F.java"])
    assert len(m.prompts) == 2                       # [0]=plan, [1]=execute
    assert m.prompts[0].startswith("# FIXCTX injected")   # plan prompt (existing behavior)
    assert m.prompts[1].startswith("# FIXCTX injected")   # execute prompt (NEW: patch-writing sees it)


def test_execute_no_preamble_by_default(tmp_path):
    m = RecModel([_GOOD_PLAN, _DIFF])
    PlanningFixEngine(m).propose_with_plan(_wt(tmp_path), _ticket(), ["src/F.java"])
    assert m.prompts[1].startswith("Bug:")           # no preamble -> execute prompt unchanged
