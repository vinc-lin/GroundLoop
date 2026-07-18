"""TEST-ONLY FIXTURE (hidden-oracle bridge). `grade(record, oracle) -> Scores` and the core `Oracle`/`Scores`
types are called ONLY by tests; the real `gloop grade-run`/eval path uses `eval.dataset.EvalOracle` +
`run/grade_run.py`. Kept because `core/` is frozen (cannot delete `Oracle`/`Scores`). Never wire into the loop."""
from __future__ import annotations
from groundloop.core.workflow import RunRecord
from groundloop.core.types import Oracle, Scores


def grade(record: RunRecord, oracle: Oracle) -> Scores:
    names = [rs.repo.name for rs in record.ranked]
    rank = names.index(oracle.owning_repo) + 1 if oracle.owning_repo in names else 0
    recall1 = 1.0 if names[:1] == [oracle.owning_repo] else 0.0
    exp = set(oracle.expected_files)
    loc = (len(set(record.locations) & exp) / len(exp)) if exp else 0.0
    return Scores(repo_recall_at_1=recall1, repo_rank=rank, localization_recall=loc, bound=record.bound)
