"""Oracle-blind whole-loop fix eval. Per (case x arm): Stage-1 match+abstain (SP1a decide) ->
localize -> propose -> apply-check (bounded refine). Emits an abstain-capable FixRecord. Never calls
run_ticket (frozen/branchless); never reads _oracle/ (offline grade is the sole oracle read)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from groundloop.core.types import RepoRef
from groundloop.eval.abstain import decide
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef, case_catalog
from groundloop.fixeval.localize import localize
from groundloop.fixeval.patch import patch_applies
from groundloop.skills.base import render_skills
from groundloop.skills.ctx import build_ctx


def _skill_query(skills) -> str:
    """Build a localize-bias query from selected skills: their retrieval .signals plus the token(s) on
    any 'Localize:' line of their guidance. Empty -> localize() stays byte-identical to skills=none."""
    parts: list[str] = []
    for s in skills:
        parts.extend(s.signals)
        for line in s.guidance.splitlines():
            t = line.strip()
            if t.lower().startswith("localize:"):
                parts.append(t.split(":", 1)[1].strip())
    return " ".join(p for p in parts if p).strip()


@dataclass(frozen=True)
class FixRecord:
    case_id: str
    arm: str
    predicted_repo: str | None
    locations: list[str]
    patch_diff: str
    patch_files: list[str]
    patch_emitted: bool
    patch_applies: bool
    abstained: bool
    abstain_reason: str | None
    refine_iters: int
    cost_usd: float


class FixEvalRunner:
    def __init__(self, *, issues, estate, catalog, tau_margin: float, tau_score: float,
                 max_refine: int = 1, skills=None):
        self.issues = issues
        self.estate = estate                     # materialize only
        self.catalog = list(catalog)             # list[RepoRef] for rank_repos
        self.tau_margin = tau_margin
        self.tau_score = tau_score
        self.max_refine = max_refine
        self.skills = skills                     # a SkillRegistry or None (the `--skills` arm knob)

    def run(self, cases: Sequence[CaseRef], arms: Sequence[Arm], *, fixer) -> list[FixRecord]:
        records: list[FixRecord] = []
        for case in cases:
            catalog = case_catalog(case) or self.catalog
            ticket = self.issues.fetch(case.case_id)          # loop-visible only
            for arm in arms:
                records.append(self._one(case, arm, ticket, catalog, fixer))
        return records

    def _one(self, case, arm, ticket, catalog, fixer) -> FixRecord:
        def rec(**kw):
            base = dict(case_id=case.case_id, arm=arm.name, predicted_repo=None, locations=[],
                        patch_diff="", patch_files=[], patch_emitted=False, patch_applies=False,
                        abstained=True, abstain_reason=None, refine_iters=0, cost_usd=0.0)
            base.update(kw)
            return FixRecord(**base)

        signals = arm.extractor.extract(ticket.logs, ticket)
        ranked = arm.index.rank_repos(signals, catalog)
        tm = arm.tau_margin if arm.tau_margin is not None else self.tau_margin
        ts = arm.tau_score if arm.tau_score is not None else self.tau_score
        d = decide(ranked, tau_margin=tm, tau_score=ts)
        if d.predicted is None:                               # PRIMARY abstain gate (match)
            return rec(abstain_reason="no_repo_match")
        predicted = d.predicted
        # SKILL INJECTION (post-match, oracle-blind): key on the arm's signals + the predicted repo +
        # the raw ticket/log haystack. Empty when no playbook applies -> byte-identical to skills=none.
        f = fixer
        skill_query = ""
        if self.skills is not None:
            selected = self.skills.select(build_ctx(signals, ticket, predicted))
            preamble = render_skills(selected)
            if preamble:
                f = fixer.with_preamble(preamble)
            skill_query = _skill_query(selected)
        c0 = self._cost(fixer)
        wt = self.estate.materialize(RepoRef(predicted))
        locations = localize(arm.index, predicted, signals, ticket.summary, skill_query=skill_query)
        if not locations:                                     # SECONDARY: localize abstain
            return rec(predicted_repo=predicted, abstain_reason="no_localization",
                       cost_usd=self._cost(fixer) - c0)
        patch = f.propose(wt, ticket, locations)
        applies = patch_applies(patch.diff, wt.path)
        iters = 0
        while patch.diff and not applies and iters < self.max_refine:   # bounded in-world refine
            iters += 1
            patch = f.propose(wt, ticket, locations)
            applies = patch_applies(patch.diff, wt.path)
        if not patch.diff or not applies:                     # SECONDARY: unappliable -> abstain
            return rec(predicted_repo=predicted, locations=locations, refine_iters=iters,
                       abstain_reason="patch_unappliable", cost_usd=self._cost(fixer) - c0)
        return FixRecord(case_id=case.case_id, arm=arm.name, predicted_repo=predicted,
                         locations=locations, patch_diff=patch.diff, patch_files=list(patch.files),
                         patch_emitted=True, patch_applies=True, abstained=False, abstain_reason=None,
                         refine_iters=iters, cost_usd=self._cost(fixer) - c0)

    @staticmethod
    def _cost(fixer) -> float:
        model = getattr(fixer, "model", None)
        return float(getattr(model, "cost_usd", 0.0))
