"""Retrieval + selective-prediction metrics for the Type-2 scorecard.

recall_at_k migrated verbatim from knowledgeLoop offline/metrics.py (file-level
any-of; used for Stage-2 localization). repo_rank/wilson/phi_c are the Stage-1 +
selective additions (docs/type2-evaluation.md §7)."""
from __future__ import annotations

import math


def recall_at_k(ranked_files: list, gold: set, k: int) -> float:
    if not gold:
        return 0.0
    return len(gold & set(ranked_files[:k])) / len(gold)


def repo_rank(ranked_names: list, owning_repo: str) -> int:
    """1-indexed rank of the single owning repo; 0 if absent (Stage-1 exact match)."""
    return ranked_names.index(owning_repo) + 1 if owning_repo in ranked_names else 0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI for k successes in n trials. n=0 -> (0.0, 1.0)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def phi_c(records: list[dict], c: float = 1.0) -> float:
    """Effective Reliability (Whitehead et al.): per record with keys answered/correct/answerable —
    answered&correct=+1; answered&wrong=-c; abstain on answerable=0; abstain on unanswerable=+1;
    answered on unanswerable=-c. Mean over records. Empty -> 0.0."""
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        if r["answered"]:
            total += 1.0 if (r["answerable"] and r["correct"]) else -c
        else:
            total += 0.0 if r["answerable"] else 1.0
    return total / len(records)
