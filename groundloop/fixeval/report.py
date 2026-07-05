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
        "| arm | n | file_recall@1 | api_pass | apply_rate | resolved(adv) | fabrication | $/solved |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm, a in card.get("arms", {}).items():
        cps = a.get("cost_per_solved")
        lines.append(
            f"| {arm} | {a['n']} | {_fmt(a['file_recall@1'])} | {_fmt(a['required_api_pass_rate'])} "
            f"| {a['patch_apply_rate']:.2f} | {_fmt(a['resolved_rate'])} (n={a['n_gradeable']}) "
            f"| {_fmt(a['fabrication_rate'])} | {'n/a' if cps is None else f'{cps:.4f}'} |")
    return "\n".join(lines) + "\n"
