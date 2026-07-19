"""Markdown board for the fix loop (mirrors eval/report.py)."""
from __future__ import annotations


def _fmt(w) -> str:
    v = w.get("value") if isinstance(w, dict) else w
    return "n/a" if v is None else f"{v:.2f}"


def render_fix_markdown(card: dict) -> str:
    lines = [
        "# Fix-loop scorecard",
        "",
        "> `resolved_rate` is ADVISORY over the grounded-gradeable subset (expected_files AND required_apis).",
        "",
        "| arm | n | file_recall@1 | api_pass | apply_rate | resolved(adv) | resolved_rate_strict "
        "| fabrication | plan_groundedness | plan_target_recall@1 | plan_api_match | $/solved |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, a in card.get("arms", {}).items():
        cps = a.get("cost_per_solved")
        lines.append(
            f"| {arm} | {a['n']} | {_fmt(a['file_recall@1'])} | {_fmt(a['required_api_pass_rate'])} "
            f"| {a['patch_apply_rate']:.2f} | {_fmt(a['resolved_rate'])} (n={a['n_gradeable']}) "
            f"| {_fmt(a.get('resolved_rate_strict'))} | {_fmt(a['fabrication_rate'])} "
            f"| {_fmt(a.get('plan_groundedness'))} | {_fmt(a.get('plan_target_recall@1'))} "
            f"| {_fmt(a.get('plan_api_match'))} | {'n/a' if cps is None else f'{cps:.4f}'} |")
    return "\n".join(lines) + "\n"


def _yn(v) -> str:
    if v is None:
        return "n/a"
    return "yes" if v else "no"


def render_e2e_funnel(scorecard: dict, per_case: list[dict] | None = None) -> str:
    """Honest end-to-end funnel: match -> localize -> fix, on the SAME N cases as one arm's
    `grade_fix_all(...)["arms"][arm]` dict. Localize/fix rows are read straight off that dict —
    grade_fix_all already computes them, so they are never recomputed here. `grade_fix_all` is
    oracle-blind to match correctness (fixeval/scorecard.py never reads oracle.owning_repo — match
    grading is a separate Stage-1 concern in eval/scorecard.py), so the match row is a coverage
    tally over `per_case` (per-case rows carrying at least case_id/match/localize_at_5/resolved),
    not a scorecard key. submit/bind is always reported as the mock adapter it is — never scored
    as "bound"."""
    per_case = list(per_case or [])
    n = scorecard.get("n", len(per_case))
    match_rate = (sum(1 for r in per_case if r.get("match")) / len(per_case)) if per_case else None

    lines = [
        "## End-to-end funnel",
        "",
        "| stage | metric | value |",
        "|---|---|---|",
        f"| match | matched | {_fmt(match_rate)} |",
        f"| localize | file@1 | {_fmt(scorecard.get('file_recall@1'))} |",
        f"| localize | file@5 | {_fmt(scorecard.get('file_recall@5'))} |",
        f"| fix | patch_applies | {_fmt(scorecard.get('patch_apply_rate'))} |",
        f"| fix | resolved_strict | {_fmt(scorecard.get('resolved_rate_strict'))} |",
        f"| fix | required_api_pass | {_fmt(scorecard.get('required_api_pass_rate'))} |",
        "",
        "**submit / bind:** mock — not scored (live Gerrit/JIRA out of scope)",
        "",
    ]
    if not per_case:
        lines.append(f"_0 cases (n={n})._")
        return "\n".join(lines) + "\n"

    lines += ["| case | match | localize@5 | resolved |", "|---|---|---|---|"]
    for row in per_case:
        lines.append(
            f"| {row.get('case_id', '?')} | {_yn(row.get('match'))} "
            f"| {_yn(row.get('localize_at_5'))} | {_yn(row.get('resolved'))} |")
    return "\n".join(lines) + "\n"
