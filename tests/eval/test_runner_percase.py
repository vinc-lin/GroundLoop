import json

from groundloop.core.types import RepoRef, RepoScore, Signals, Ticket
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef
from groundloop.eval.runner import EvalRunner


class _FakeIndex:
    """Rank each catalog repo by a fixed score map; unknown repos get 0.0 (deterministic)."""

    def __init__(self, scores):
        self.scores = scores

    def rank_repos(self, signals, catalog):
        return sorted((RepoScore(r, self.scores.get(r.name, 0.0)) for r in catalog),
                      key=lambda rs: rs.score, reverse=True)


class _FakeExtractor:
    def extract(self, logs, ticket):
        return Signals()


class _FakeIssues:
    def fetch(self, cid):
        return Ticket(id=cid, summary="", description="")


class _FakeEstate:
    def catalog(self):
        return [RepoRef("a"), RepoRef("b"), RepoRef("c")]


def _case(tmp_path, cid, catalog=None):
    d = tmp_path / cid
    d.mkdir()
    (d / "ticket.json").write_text(json.dumps({"id": cid, "logs": []}))
    if catalog is not None:
        (d / "catalog.json").write_text(json.dumps([{"name": n} for n in catalog]))
    return CaseRef(case_id=cid, case_dir=str(d))


def test_per_case_catalog_overrides_global(tmp_path):
    case = _case(tmp_path, "oof", catalog=["b", "c"])          # 'a' (the top-scorer) held out
    arm = Arm("membership+logs", _FakeIndex({"a": 5.0, "b": 1.0, "c": 0.0}), _FakeExtractor())
    runner = EvalRunner(issues=_FakeIssues(), estate=_FakeEstate(), tau_margin=1.0, tau_score=1.0)
    [rec] = runner.run([case], [arm])
    assert "a" not in rec.ranked_names and rec.ranked_names == ["b", "c"]


def test_per_arm_tau_overrides_runner_default(tmp_path):
    case = _case(tmp_path, "c")                                # global catalog (a,b,c)
    # cosine-like scores < 1.0: the runner default (tau_score 1.0) would abstain; the arm tau_score=0.0 answers
    arm = Arm("semantic+logs", _FakeIndex({"a": 0.6, "b": 0.1, "c": 0.0}), _FakeExtractor(),
              tau_margin=0.05, tau_score=0.0)
    runner = EvalRunner(issues=_FakeIssues(), estate=_FakeEstate(), tau_margin=1.0, tau_score=1.0)
    [rec] = runner.run([case], [arm])
    assert rec.predicted == "a"
