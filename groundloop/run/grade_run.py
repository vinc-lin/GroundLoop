"""Offline per-stage grader over run-records — the SOLE oracle read (load_eval_oracle), mirroring
fixeval. Emits match / localize(as-run + isolated) / fix(or honest-abstain) with automatic counts and a
by_bug_kind split. Never re-runs the loop; the only re-execution is the isolated-localize diagnostic."""
from __future__ import annotations

import json
from pathlib import Path

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import RepoRef
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.eval.metrics import recall_at_k, repo_rank
from groundloop.fix.patch import canonical_path
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all
from groundloop.run.record import RunRecordIO

_KS = (1, 3, 5)


def _signals_from_doc(doc):
    """Reconstruct a Signals from the persisted run-record dict (JSON round-trip -> lists).
    Unknown keys are dropped; missing -> Signals defaults (anchorless -> functional route)."""
    from groundloop.core.types import Signals
    raw = getattr(doc, "signals", None) or {}
    fields = ("packages", "classes", "methods", "symbols", "libraries", "errors")
    return Signals(**{k: tuple(raw[k]) for k in fields if k in raw})


def _localize_index_for(runs_dir, index_db, embedder):
    """Build the isolated-diagnostic localize index matching the arm the run used (manifest.localize).
    Falls back to AtlasIndex (FTS5) when the arm needs an embedder and none is available."""
    arm = "atlas"
    mpath = Path(runs_dir) / "manifest.json"
    if mpath.exists():
        try:
            arm = json.loads(mpath.read_text()).get("localize", "atlas")
        except (json.JSONDecodeError, OSError):
            arm = "atlas"
    if arm == "tokens":
        from groundloop.adapters.index.signal_query import SignalQueryIndex
        return SignalQueryIndex(AtlasIndex(index_db), AtlasIndex(index_db)), arm
    if arm == "semantic" and embedder is not None:
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        return SemanticAtlasIndex(index_db, embedder), arm
    if arm == "rerank":
        # The offline grader has no LLM judge, so the reranker degrades to its grounded candidate POOL
        # (find_related_units symbol+doc). That measures the arm's rank-1 ceiling honestly — the LLM
        # reorder cannot be reproduced offline. But the vector candidate-gen still needs an embedder:
        # fail-fast (same as the live run's `--localize rerank` guard) so the isolated diagnostic cannot
        # silently diverge into a keyword-only reranker while a rerank scorecard looks valid.
        if embedder is None:
            raise RuntimeError(
                "grade-run localize=rerank: no embedder — set KLOOP_EMBED_BASE_URL (bge-m3 gateway) "
                "so the isolated diagnostic matches the live rerank run instead of silently degrading "
                "to a keyword-only reranker.")
        from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex
        from groundloop.engines.atlas.store import Store
        return (RerankLocalizeIndex(AtlasIndex(index_db), store=Store(index_db),
                                    embedder=embedder, judge=None), "rerank(no-judge:pool)")
    if arm == "cascade":
        # Recall-first RRF cascade, reconstructed for the isolated diagnostic. The semantic tier degrades
        # gracefully: with no embedder it is omitted (crash-tokens + literal-anchor FTS tiers still fire),
        # so — unlike rerank — cascade never fails-fast offline.
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
        from groundloop.engines.atlas.store import Store
        sem = SemanticAtlasIndex(index_db, embedder) if embedder is not None else None
        cascade = CascadeLocalizeIndex(AtlasIndex(index_db), fts=AtlasIndex(index_db), semantic=sem,
                                       store=Store(index_db))
        return cascade, (arm if embedder is not None else "cascade(no-embedder:fts-only)")
    if arm == "cascade_judge":
        # The live arm is a rerank LLM judge over a recall-first cascade POOL. The offline grader has no
        # judge, so the reranker degrades to reordering its injected cascade pool (find nothing to reorder
        # -> the cascade pool order) — an honest rank-1 ceiling. Like cascade (and unlike rerank), the
        # missing-embedder path never fails-fast: the cascade omits its semantic tier and the reranker
        # draws its POOL from the cascade's retrieve() (not vector candidate-gen), so embedder=None is fine.
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        from groundloop.adapters.index.cascade_localize import CascadeLocalizeIndex
        from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex
        from groundloop.engines.atlas.store import Store
        sem = SemanticAtlasIndex(index_db, embedder) if embedder is not None else None
        cascade = CascadeLocalizeIndex(AtlasIndex(index_db), fts=AtlasIndex(index_db), semantic=sem,
                                       store=Store(index_db))
        rer = RerankLocalizeIndex(AtlasIndex(index_db), store=Store(index_db),
                                  embedder=embedder, judge=None, pool_index=cascade)
        return rer, "cascade_judge(no-judge:cascade-pool)"
    if arm == "dispatch":     # localize dispatch retired (archived 2026-07-16) -> grade on the FTS5 floor
        return AtlasIndex(index_db), "dispatch->atlas(retired)"
    fell_back = arm == "semantic"     # wanted embedder, none available
    return AtlasIndex(index_db), (f"{arm}->atlas(no-embedder)" if fell_back else "atlas")


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
        return sum(recall_at_k([canonical_path(x) for x in r["locations"]],
                               {canonical_path(e) for e in r["expected"]}, k) for r in loc) / n
    return {f"file@{k}": fk(k) for k in _KS}


def _localize_isolated(rows):
    """Match-independent localize ceiling: `retrieved` was re-run on the ORACLE repo in the grade pass
    (the sole re-execution), so this isolates localize from match contamination — the '7/10 not 0/10'
    correction. Populated only when the caller precomputed `row['retrieved']` (i.e. an index was given)."""
    loc = [r for r in rows if r["expected"]]
    n = len(loc)

    def fk(k):
        if not n:
            return None
        return sum(recall_at_k([canonical_path(x) for x in r["retrieved"]],
                               {canonical_path(e) for e in r["expected"]}, k) for r in loc) / n
    return {f"file@{k}": fk(k) for k in _KS}


def _case_row(row):
    exp = {canonical_path(e) for e in row["expected"]}
    as_run1 = recall_at_k([canonical_path(x) for x in row["locations"]], exp, 1) if exp else None
    iso1 = None
    if "retrieved" in row and exp:
        iso1 = recall_at_k([canonical_path(x) for x in row["retrieved"]], exp, 1)
    present = row["doc"].materialize.present
    fix = "ungradeable(no_source)" if not present else (
        "applies" if row["doc"].patch_applies else "unappliable")
    return {"case_id": row["case_id"], "rank": row["rank"], "as_run@1": as_run1,
            "isolated@1": iso1, "fix": fix,
            "predicted_repo": row["doc"].chosen,
            "oracle_repo": row["owner"],
            "signals": getattr(row["doc"], "signals", None),
            "cost_usd": getattr(row["doc"], "cost_usd", 0.0),
            "fixer": getattr(row["doc"], "fixer", "")}


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


def _grade_subset(rows, oracle_by_case, with_isolated):
    mb = _match_block(rows)
    return {
        "match": {"n": mb["n"], **{f"recall@{k}": mb[f"recall@{k}"] for k in _KS},
                  "recall_rank_avg": (sum(r["rank"] for r in rows) / len(rows)) if rows else 0.0},
        "localize": {"as_run": _localize_as_run(rows),
                     "isolated": _localize_isolated(rows) if with_isolated else None},
        "fix": _fix_block(rows, oracle_by_case),
        "counts": {"n": mb["n"], "match_hits@1": round(mb["_hits1"])},
    }


def grade_run(runs_dir: str, dataset: str, *, index_db: str | None = None, embedder=None) -> dict:
    cases = load_cases(dataset)
    rows = []
    for c in cases:
        doc = RunRecordIO.read(f"{runs_dir}/runs/{c.case_id}.json")
        o = load_eval_oracle(c)                                        # the ONLY oracle read
        query = json.loads((Path(c.case_dir) / "ticket.json").read_text()).get("summary", "")
        rows.append({
            "case_id": c.case_id, "case": c, "doc": doc, "owner": o.owning_repo, "oracle": o,
            "bug_kind": o.bug_kind, "expected": list(o.expected_files), "query": query,
            "ranked_names": [x["repo"] for x in doc.ranked],
            "rank": repo_rank([x["repo"] for x in doc.ranked], o.owning_repo),
            "locations": list(doc.locations),
        })
    # The isolated-localize diagnostic: re-run retrieve on the ORACLE repo (grade-only, never the loop).
    # Reconstruct the localize index the run actually used (manifest.localize) and seed per-case signals.
    iso_arm = None
    if index_db:
        idx, iso_arm = _localize_index_for(runs_dir, index_db, embedder)
        for r in rows:
            if r["expected"]:
                if hasattr(idx, "note_signals"):
                    idx.note_signals(_signals_from_doc(r["doc"]))
                r["retrieved"] = idx.retrieve(RepoRef(r["owner"]), r["query"])
    with_isolated = bool(index_db)
    oracle_by_case = {r["case_id"]: r["oracle"] for r in rows}
    card = {"n_cases": len(rows), "overall": _grade_subset(rows, oracle_by_case, with_isolated)}
    if index_db:
        card["overall"]["localize"]["isolated_arm"] = iso_arm       # honest attribution of the diagnostic
    kinds = sorted({r["bug_kind"] for r in rows if r["bug_kind"]})
    card["by_bug_kind"] = {bk: _grade_subset([r for r in rows if r["bug_kind"] == bk],
                                             oracle_by_case, with_isolated) for bk in kinds}
    card["cases"] = [_case_row(r) for r in rows]
    return card
