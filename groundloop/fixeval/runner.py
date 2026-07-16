"""Oracle-blind whole-loop fix eval. Per (case x arm): Stage-1 match+abstain (SP1a decide) ->
localize -> propose -> apply-check (bounded refine). Emits an abstain-capable FixRecord. Never calls
run_ticket (frozen/branchless); never reads _oracle/ (offline grade is the sole oracle read)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from groundloop.core.types import RepoRef, WorkTree
from groundloop.eval.abstain import decide
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef, case_catalog
from groundloop.fixeval.base_checkout import checkout_base
from groundloop.fixeval.localize import localize
from groundloop.fixeval.patch import patch_applies
from groundloop.kb.render import render_knowledge
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
    fired_knowledge: tuple[str, ...] = ()


class FixEvalRunner:
    def __init__(self, *, issues, estate, catalog, tau_margin: float, tau_score: float,
                 max_refine: int = 1, skills=None, knowledge=None, knowledge_tier_floor: str = "validated",
                 skill_inject: str = "both", base_checkout: bool = False, repos_root: str | None = None,
                 base_work_root: str | None = None, fix_context=None):
        self.issues = issues
        self.estate = estate                     # materialize only
        self.catalog = list(catalog)             # list[RepoRef] for rank_repos
        self.tau_margin = tau_margin
        self.tau_score = tau_score
        self.max_refine = max_refine
        self.skills = skills                     # a SkillRegistry or None (the `--skills` arm knob)
        self.knowledge = knowledge               # a KnowledgeRegistry or None (the `--knowledge` arm knob)
        # OPT-IN Dev-Labs code-understanding fix context: a FixContextProvider (CodeWiki module summaries +
        # live CBM call-graph) or None. Injected as a fix-prompt preamble AFTER localize (it keys on the
        # localized files). Default None -> byte-identical to today; oracle-blind (loop-visible only).
        self.fix_context = fix_context
        self.knowledge_tier_floor = knowledge_tier_floor  # TIERS floor: `candidate` in eval, `validated` prod
        self.skill_inject = skill_inject         # both (localize query + fix prompt) | fix-only (fix prompt only)
        # OPT-IN Dev-Labs @base=fix^ substrate: per-case checkout of the pre-fix source so the fix
        # stage is gradeable (default OFF -> byte-identical to today; oracle-side, never a matcher input).
        self.base_checkout = base_checkout
        self.repos_root = repos_root             # root of local repo clones: <repos_root>/<repo>
        self.base_work_root = base_work_root     # where per-case @base work-trees are checked out

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
        # SKILL/KNOWLEDGE INJECTION (post-match, oracle-blind): key on the arm's signals + the predicted repo
        # + the raw ticket/log haystack. Empty when nothing applies -> byte-identical to none/none.
        f = fixer
        skill_query = ""
        fired: tuple = ()
        selected_knowledge: list = []            # B4 captures ids off this local
        ctx = None
        if self.skills is not None or self.knowledge is not None:
            ctx = build_ctx(signals, ticket, predicted)       # loop-visible only (oracle-blind)
        skill_pre = ""
        if self.skills is not None:
            selected = self.skills.select(ctx)
            fired = tuple(getattr(s, "id", "") for s in selected)
            skill_pre = render_skills(selected)
            # fix-only: skills feed ONLY the fix/plan prompt (skill_pre) -> localize stays byte-identical
            # to the `none` arm. both (default): they also bias the localize retrieval query.
            skill_query = _skill_query(selected) if self.skill_inject == "both" else ""
        knowledge_pre = ""
        if self.knowledge is not None:
            selected_knowledge = self.knowledge.select(ctx, self.knowledge_tier_floor)
            knowledge_pre = render_knowledge(selected_knowledge)   # PLAN-prompt preamble only
        preamble = skill_pre + knowledge_pre                   # skills first; each is "" when its arm is off
        if preamble:
            f = fixer.with_preamble(preamble)
        fired_knowledge = tuple(getattr(k, "id", "") for k in selected_knowledge)
        c0 = self._cost(fixer)
        wt = self._materialize(case, predicted)
        locations = localize(arm.index, predicted, signals, ticket.summary, skill_query=skill_query)
        if not locations:                                     # SECONDARY: localize abstain
            return rec(predicted_repo=predicted, abstain_reason="no_localization",
                       cost_usd=self._cost(fixer) - c0, fired_skills=fired, fired_knowledge=fired_knowledge)
        # CODE-UNDERSTANDING FIX CONTEXT (post-localize: keys on the localized files + signals). Re-clone
        # from the ORIGINAL fixer with the FULL preamble (skills+knowledge+codewiki+cbm). Fail-safe + opt-in:
        # fix_context=None -> byte-identical; empty context -> preamble unchanged.
        if self.fix_context is not None:
            try:
                codewiki_pre, cbm_pre = self.fix_context.preambles(predicted, locations, signals)
            except Exception:      # noqa: BLE001 — enrichment is best-effort, never sink the fix
                codewiki_pre, cbm_pre = "", ""
            full = preamble + codewiki_pre + cbm_pre
            if full:
                f = fixer.with_preamble(full)
        plan_dict, patch, meta = _do_propose(f, wt, ticket, locations)
        applies = patch_applies(patch.diff, wt.path)
        iters = 0
        while patch.diff and not applies and iters < self.max_refine:   # bounded in-world refine
            iters += 1
            plan_dict, patch, meta = _do_propose(f, wt, ticket, locations)
            applies = patch_applies(patch.diff, wt.path)
        pmeta = dict(plan=plan_dict, groundedness=meta.get("groundedness"),
                     replans=meta.get("replans", 0), fired_skills=fired, fired_knowledge=fired_knowledge)
        if not patch.diff or not applies:                     # SECONDARY: unappliable -> abstain
            return rec(predicted_repo=predicted, locations=locations, refine_iters=iters,
                       abstain_reason="patch_unappliable", cost_usd=self._cost(fixer) - c0, **pmeta)
        return FixRecord(case_id=case.case_id, arm=arm.name, predicted_repo=predicted,
                         locations=locations, patch_diff=patch.diff, patch_files=list(patch.files),
                         patch_emitted=True, patch_applies=True, abstained=False, abstain_reason=None,
                         refine_iters=iters, cost_usd=self._cost(fixer) - c0, **pmeta)

    def _materialize(self, case, predicted: str) -> WorkTree:
        """Estate materialize by default. When --base-checkout is ON, replace the (empty/name-keyed)
        worktree with a per-case checkout of @base=fix^ so the fix stage runs on the real buggy source.
        Fail-safe: any miss (no SHA / no clone / checkout failure) falls back to today's estate worktree."""
        wt = self.estate.materialize(RepoRef(predicted))
        if not self.base_checkout:
            return wt
        base = self._base_worktree(case, predicted)
        return WorkTree(RepoRef(predicted), base) if base is not None else wt

    def _base_worktree(self, case, predicted: str) -> str | None:
        """Check out @base=fix^ for this case's predicted repo -> a per-case worktree path, or None."""
        if not self.repos_root:
            return None
        sha = self._case_fix_sha(case)
        if not sha:
            return None
        src = Path(self.repos_root) / predicted
        if not src.is_dir():
            return None
        root = Path(self.base_work_root) if self.base_work_root else (Path(self.repos_root).parent / "_base")
        return checkout_base(str(src), sha, str(root / case.case_id / predicted))

    @staticmethod
    def _case_fix_sha(case) -> str | None:
        """Read owning_repo_sha from the case's hidden oracle. Gated by base_checkout (opt-in), so the
        DEFAULT runner path never touches _oracle/ — the oracle-blind invariant holds. Oracle-side use
        only: the SHA builds the downstream fix substrate, never feeds the matcher."""
        import json
        p = Path(case.case_dir) / "_oracle" / "oracle.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text()).get("owning_repo_sha") or None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _cost(fixer) -> float:
        model = getattr(fixer, "model", None)
        return float(getattr(model, "cost_usd", 0.0))
