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
from groundloop.kb.render import render_claims
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


def _do_propose(f, wt, ticket, locations):
    """Use the plan-aware path when the fixer exposes it, else the frozen propose. Returns
    (plan_dict|None, Patch, meta)."""
    if hasattr(f, "propose_with_plan"):
        plan, patch, meta = f.propose_with_plan(wt, ticket, locations)
        from groundloop.fixeval.plan import plan_to_dict
        pd = plan_to_dict(plan) if plan is not None and not isinstance(plan, dict) else plan
        return pd, patch, (meta or {})
    return None, f.propose(wt, ticket, locations), {}


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
    plan: dict | None = None
    groundedness: float | None = None
    replans: int = 0
    fired_skills: tuple[str, ...] = ()
    fired_claims: tuple[str, ...] = ()


class FixEvalRunner:
    def __init__(self, *, issues, estate, catalog, tau_margin: float, tau_score: float,
                 max_refine: int = 1, skills=None, claims=None, claims_tier_floor: str = "validated"):
        self.issues = issues
        self.estate = estate                     # materialize only
        self.catalog = list(catalog)             # list[RepoRef] for rank_repos
        self.tau_margin = tau_margin
        self.tau_score = tau_score
        self.max_refine = max_refine
        self.skills = skills                     # a SkillRegistry or None (the `--skills` arm knob)
        self.claims = claims                     # a ClaimRegistry or None (the `--claims` arm knob)
        self.claims_tier_floor = claims_tier_floor   # TIERS floor: `candidate` in eval, `validated` in prod

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
        # SKILL/CLAIM INJECTION (post-match, oracle-blind): key on the arm's signals + the predicted repo
        # + the raw ticket/log haystack. Empty when nothing applies -> byte-identical to none/none.
        f = fixer
        skill_query = ""
        fired: tuple = ()
        selected_claims: list = []               # B4 captures ids off this local
        ctx = None
        if self.skills is not None or self.claims is not None:
            ctx = build_ctx(signals, ticket, predicted)       # loop-visible only (oracle-blind)
        skill_pre = ""
        if self.skills is not None:
            selected = self.skills.select(ctx)
            fired = tuple(getattr(s, "id", "") for s in selected)
            skill_pre = render_skills(selected)
            skill_query = _skill_query(selected)              # claims DO NOT feed the localize query
        claim_pre = ""
        if self.claims is not None:
            selected_claims = self.claims.select(ctx, self.claims_tier_floor)
            claim_pre = render_claims(selected_claims)         # PLAN-prompt preamble only
        preamble = skill_pre + claim_pre                       # skills first; each is "" when its arm is off
        if preamble:
            f = fixer.with_preamble(preamble)
        fired_claims = tuple(getattr(c, "id", "") for c in selected_claims)
        c0 = self._cost(fixer)
        wt = self.estate.materialize(RepoRef(predicted))
        locations = localize(arm.index, predicted, signals, ticket.summary, skill_query=skill_query)
        if not locations:                                     # SECONDARY: localize abstain
            return rec(predicted_repo=predicted, abstain_reason="no_localization",
                       cost_usd=self._cost(fixer) - c0, fired_skills=fired, fired_claims=fired_claims)
        plan_dict, patch, meta = _do_propose(f, wt, ticket, locations)
        applies = patch_applies(patch.diff, wt.path)
        iters = 0
        while patch.diff and not applies and iters < self.max_refine:   # bounded in-world refine
            iters += 1
            plan_dict, patch, meta = _do_propose(f, wt, ticket, locations)
            applies = patch_applies(patch.diff, wt.path)
        pmeta = dict(plan=plan_dict, groundedness=meta.get("groundedness"),
                     replans=meta.get("replans", 0), fired_skills=fired, fired_claims=fired_claims)
        if not patch.diff or not applies:                     # SECONDARY: unappliable -> abstain
            return rec(predicted_repo=predicted, locations=locations, refine_iters=iters,
                       abstain_reason="patch_unappliable", cost_usd=self._cost(fixer) - c0, **pmeta)
        return FixRecord(case_id=case.case_id, arm=arm.name, predicted_repo=predicted,
                         locations=locations, patch_diff=patch.diff, patch_files=list(patch.files),
                         patch_emitted=True, patch_applies=True, abstained=False, abstain_reason=None,
                         refine_iters=iters, cost_usd=self._cost(fixer) - c0, **pmeta)

    @staticmethod
    def _cost(fixer) -> float:
        model = getattr(fixer, "model", None)
        return float(getattr(model, "cost_usd", 0.0))
