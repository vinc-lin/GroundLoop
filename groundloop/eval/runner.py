"""Oracle-blind Stage-1 eval runner. Per (case x arm): fetch ticket, extract signals, rank repos
DIRECTLY (no run_ticket), apply the abstain policy. Never reads the oracle (docs §8.2/§9)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from groundloop.eval.abstain import decide
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef, case_catalog


@dataclass(frozen=True)
class MatchRecord:
    case_id: str
    arm: str
    ranked_names: list[str]
    scores: list[float]
    predicted: str | None      # None = abstain
    margin: float
    top1_score: float


class EvalRunner:
    def __init__(self, *, issues, estate, tau_margin: float, tau_score: float):
        self.issues = issues
        self.estate = estate
        self.tau_margin = tau_margin
        self.tau_score = tau_score

    def run(self, cases: Sequence[CaseRef], arms: Sequence[Arm]) -> list[MatchRecord]:
        global_catalog = self.estate.catalog()
        records: list[MatchRecord] = []
        for case in cases:
            catalog = case_catalog(case) or global_catalog        # per-case override (OOF hold-out)
            ticket = self.issues.fetch(case.case_id)              # loop-visible only
            for arm in arms:
                signals = arm.extractor.extract(ticket.logs, ticket)
                ranked = arm.index.rank_repos(signals, catalog)
                tm = arm.tau_margin if arm.tau_margin is not None else self.tau_margin
                ts = arm.tau_score if arm.tau_score is not None else self.tau_score
                d = decide(ranked, tau_margin=tm, tau_score=ts)
                records.append(MatchRecord(
                    case_id=case.case_id, arm=arm.name,
                    ranked_names=[r.repo.name for r in ranked],
                    scores=[r.score for r in ranked],
                    predicted=d.predicted, margin=d.margin, top1_score=d.top1_score))
        return records
