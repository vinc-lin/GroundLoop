"""Offline per-stage grader over run-records — the SOLE oracle read (load_eval_oracle), mirroring
fixeval. Emits match / localize(as-run + isolated) / fix(or honest-abstain) with automatic counts and a
by_bug_kind split. Never re-runs the loop; the only re-execution is the isolated-localize diagnostic."""
from __future__ import annotations

from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.metrics import recall_at_k, repo_rank
from groundloop.fixeval.patch import norm_path
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all
from groundloop.run.record import RunRecordIO

_KS = (1, 3, 5)


def _match_block(rows):
    n = len(rows)
    hits = {k: sum(recall_at_k(r["ranked_names"], {r["owner"]}, k) for r in rows) for k in _KS}
    return {"n": n, **{f"recall@{k}": (hits[k] / n if n else 0.0) for k in _KS},
            "_hits1": hits[1]}


def _localize_as_run(rows):
    loc = [r for r in rows if r["expected"]]
    n = len(loc)

    def fk(k):
        if not n:
            return None
        return sum(recall_at_k([norm_path(x) for x in r["locations"]],
                               {norm_path(e) for e in r["expected"]}, k) for r in loc) / n
    return {f"file@{k}": fk(k) for k in _KS}


def _fix_record(row):
    """Adapt an offline run-record into the FixRecord shape grade_fix_all iterates. patch_applies was
    computed at run time (against the live worktree) and persisted, so no worktree is needed here."""
    doc = row["doc"]
    emitted = bool(doc.patch["diff"].strip())
    return FixRecord(
        case_id=row["case_id"], arm="run", predicted_repo=doc.chosen, locations=list(doc.locations),
        patch_diff=doc.patch["diff"], patch_files=list(doc.patch["files"]),
        patch_emitted=emitted, patch_applies=bool(doc.patch_applies),
        abstained=not emitted, abstain_reason=None, refine_iters=0, cost_usd=0.0)


def _fix_block(rows, oracle_by_case):
    """Honest-abstain gate: a case whose worktree was empty (materialize.present is False) has no real
    source, so its (fabricated) patch is UNGRADEABLE — never scored, never read as a localization. The
    present-worktree subset is graded by reusing fixeval.grade_fix_all."""
    gradeable = [r for r in rows if r["doc"].materialize.present]
    ungradeable = [r for r in rows if not r["doc"].materialize.present]
    if not gradeable:
        return {"n_gradeable": 0, "n_ungradeable_no_source": len(ungradeable),
                "resolved_rate_strict": {"value": None, "n": 0},
                "fabrication_rate": {"value": None, "n": 0}, "patch_apply_rate": None}
    recs = [_fix_record(r) for r in gradeable]
    card = grade_fix_all(recs, oracle_by_case={r["case_id"]: oracle_by_case[r["case_id"]]
                                               for r in gradeable})
    arm = card["arms"]["run"]
    return {"n_gradeable": len(gradeable), "n_ungradeable_no_source": len(ungradeable),
            "file_recall@1": arm["file_recall@1"], "resolved_rate_strict": arm["resolved_rate_strict"],
            "fabrication_rate": arm["fabrication_rate"], "patch_apply_rate": arm["patch_apply_rate"]}


def _grade_subset(rows, oracle_by_case):
    mb = _match_block(rows)
    return {
        "match": {"n": mb["n"], **{f"recall@{k}": mb[f"recall@{k}"] for k in _KS},
                  "recall_rank_avg": (sum(r["rank"] for r in rows) / len(rows)) if rows else 0.0},
        "localize": {"as_run": _localize_as_run(rows), "isolated": None},   # isolated filled in Task 6
        "fix": _fix_block(rows, oracle_by_case),
        "counts": {"n": mb["n"], "match_hits@1": round(mb["_hits1"])},
    }


def grade_run(runs_dir: str, dataset: str, *, index_db: str | None = None) -> dict:
    cases = load_cases(dataset)
    rows = []
    for c in cases:
        doc = RunRecordIO.read(f"{runs_dir}/runs/{c.case_id}.json")
        o = load_eval_oracle(c)                                        # the ONLY oracle read
        rows.append({
            "case_id": c.case_id, "case": c, "doc": doc, "owner": o.owning_repo, "oracle": o,
            "bug_kind": o.bug_kind, "expected": list(o.expected_files),
            "ranked_names": [x["repo"] for x in doc.ranked],
            "rank": repo_rank([x["repo"] for x in doc.ranked], o.owning_repo),
            "locations": list(doc.locations),
        })
    oracle_by_case = {r["case_id"]: r["oracle"] for r in rows}
    card = {"n_cases": len(rows), "overall": _grade_subset(rows, oracle_by_case)}
    return card
