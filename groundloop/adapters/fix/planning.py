"""Two-phase PLAN-then-ACT FixEngine. Phase 1 emits a grounded RepairPlan; an oracle-blind in-world
gate validates it (re-plan on failure, abstain after the bound); phase 2 executes the validated plan
into a unified diff over fault-site context. Satisfies the frozen core FixEngine.propose."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from groundloop.core.types import Patch, Ticket, WorkTree
from groundloop.fix.patch import extract_unified_diff, norm_path, touched_files
from groundloop.fix.plan import (RepairPlan, check_plan_in_world, parse_plan, plan_groundedness)


class PlanningFixEngine:
    def __init__(self, model, *, preamble: str = "", max_replan: int = 1, context_window: int = 120):
        self.model = model
        self.preamble = preamble
        self.max_replan = max_replan
        self.context_window = context_window

    def with_preamble(self, preamble: str) -> "PlanningFixEngine":
        """Skills-aware clone sharing self.model (so GatewayModel.cost_usd keeps accruing)."""
        return PlanningFixEngine(self.model, preamble=preamble, max_replan=self.max_replan,
                                 context_window=self.context_window)

    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch:
        _plan, patch, _meta = self.propose_with_plan(worktree, ticket, locations)
        return patch

    def propose_with_plan(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]):
        """Returns (RepairPlan|None, Patch, meta{replans, groundedness}). Empty Patch = abstain."""
        locs = list(locations)
        plan = self._plan(worktree, ticket, locs, feedback="")
        chk = check_plan_in_world(plan, worktree.path, locs)
        attempts = 0
        while not chk.ok and attempts < self.max_replan:
            attempts += 1
            fb = ("The previous plan did not ground: " + "; ".join(chk.failures)
                  + ". Cite ONLY files from the candidate list and symbols/APIs that exist in them.")
            plan = self._plan(worktree, ticket, locs, feedback=fb)
            chk = check_plan_in_world(plan, worktree.path, locs)
        meta = {"replans": attempts, "groundedness": plan_groundedness(chk)}
        if not chk.ok:                                    # gate failed / abstained -> honest refusal
            return plan, Patch(diff="", files=()), meta
        patch = self._execute(worktree, ticket, plan)
        cand = {norm_path(loc) for loc in locs}
        if any(norm_path(f) not in cand for f in patch.files):   # anti-leak: executed diff must stay in scope
            return plan, Patch(diff="", files=()), {**meta, "abstain_reason": "diff_out_of_scope"}
        return plan, patch, meta

    def _plan(self, worktree, ticket, locations, *, feedback) -> RepairPlan | None:
        heads = "\n\n".join(self._head(worktree.path, loc) for loc in locations)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Candidate files (cite ONLY these): {', '.join(locations)}\n\n"
                  f"File heads:\n{heads}\n\n"
                  "Produce a REPAIR PLAN as a JSON object with keys: root_cause, "
                  "targets (list of {file, symbol, why}; file MUST be a candidate file), required_apis "
                  "(list), strategy, citations (candidate files your reasoning rests on), risks, "
                  "confidence (0..1), abstain (true if you cannot ground a fix). Reply ONLY with JSON.")
        if feedback:
            prompt += "\n\n" + feedback
        if self.preamble:
            prompt = self.preamble + "\n\n" + prompt
        return parse_plan(self.model.complete(prompt) or "")

    def _execute(self, worktree, ticket, plan: RepairPlan) -> Patch:
        ctx = "\n\n".join(self._window(worktree.path, t) for t in plan.targets)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Root cause: {plan.root_cause}\nStrategy: {plan.strategy}\n"
                  f"Targets: {', '.join(t.file for t in plan.targets)}\n"
                  f"Required APIs: {', '.join(plan.required_apis)}\n\n"
                  f"Fault-site context:\n{ctx}\n\n"
                  "Reply ONLY with a unified diff (```diff fenced) implementing this plan, or empty.")
        if self.preamble:                                 # so injected context (skills/knowledge/CodeWiki/
            prompt = self.preamble + "\n\n" + prompt       # CBM) reaches PATCH-WRITING, not just planning
        diff = extract_unified_diff(self.model.complete(prompt) or "")
        return Patch(diff=diff, files=tuple(touched_files(diff)))

    def _head(self, wt_path, loc, max_lines: int = 40) -> str:
        p = Path(wt_path) / loc
        if not p.is_file():
            return ""
        return f"### {loc}\n" + "\n".join(p.read_text(errors="replace").splitlines()[:max_lines])

    def _window(self, wt_path, target) -> str:
        p = Path(wt_path) / target.file
        if not p.is_file():
            return ""
        lines = p.read_text(errors="replace").splitlines()
        if target.symbol:
            for i, ln in enumerate(lines):
                if target.symbol in ln:
                    lo = max(0, i - self.context_window)
                    hi = min(len(lines), i + self.context_window)
                    return (f"### {target.file} (around {target.symbol}, lines {lo + 1}-{hi})\n"
                            + "\n".join(lines[lo:hi]))
        return f"### {target.file} (head)\n" + "\n".join(lines[: self.context_window * 2])
