"""Margin-based abstain policy over a ranked RepoScore list (docs/type2-evaluation.md §7.2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from groundloop.core.types import RepoScore


@dataclass(frozen=True)
class Decision:
    predicted: Optional[str]     # repo name, or None = ABSTAIN
    margin: float
    top1_score: float


def decide(ranked: Sequence[RepoScore], *, tau_margin: float, tau_score: float) -> Decision:
    """Predict top-1 iff (top1 - top2) margin >= tau_margin AND top1 score >= tau_score; else abstain.
    Scale-robust: gates on the margin (raw FTS5 counts are uncalibrated)."""
    if not ranked:
        return Decision(predicted=None, margin=0.0, top1_score=0.0)
    top1 = ranked[0].score
    runner = ranked[1].score if len(ranked) > 1 else 0.0
    margin = top1 - runner if len(ranked) > 1 else top1
    predicted = ranked[0].repo.name if (margin >= tau_margin and top1 >= tau_score) else None
    return Decision(predicted=predicted, margin=margin, top1_score=top1)
