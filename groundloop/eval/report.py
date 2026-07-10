"""Render a scorecard dict to a compact markdown table (docs/type2-evaluation.md §7.4)."""
from __future__ import annotations


def _row(name: str, a: dict) -> str:
    f, s = a["forced"], a["selective"]
    return (f"| {name} | {a['n']} | {f['recall@1']['value']:.2f} | {f['mrr']:.2f} | "
            f"{s['coverage']:.2f} | {s['selective_accuracy']['value']:.2f} | {s['phi_c']['1.0']:.2f} |")


def render_markdown(card: dict) -> str:
    head = ["| arm | n | recall@1 | mrr | coverage | sel-acc | Phi_1 |",
            "|---|---|---|---|---|---|---|"]
    lines = ["# Type-2 scorecard", "", f"cases: {card.get('n_cases', 0)}", "", *head]
    for arm, a in card["arms"].items():
        lines.append(_row(arm, a))

    split = [(arm, bk, sub) for arm, a in card["arms"].items()
             for bk, sub in a.get("by_bug_kind", {}).items()]
    if split:
        lines += ["", "## by bug_kind", "",
                  "| arm / kind | n | recall@1 | mrr | coverage | sel-acc | Phi_1 |",
                  "|---|---|---|---|---|---|---|"]
        for arm, bk, sub in split:
            lines.append(_row(f"{arm} / {bk}", sub))
    return "\n".join(lines) + "\n"
