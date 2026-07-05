"""Render a scorecard dict to a compact markdown table (docs/type2-evaluation.md §7.4)."""
from __future__ import annotations


def render_markdown(card: dict) -> str:
    lines = ["# Type-2 scorecard", "", f"cases: {card.get('n_cases', 0)}", "",
             "| arm | n | recall@1 | mrr | coverage | sel-acc | Phi_1 |",
             "|---|---|---|---|---|---|---|"]
    for arm, a in card["arms"].items():
        f, s = a["forced"], a["selective"]
        r1 = f["recall@1"]["value"]
        lines.append(f"| {arm} | {a['n']} | {r1:.2f} | {f['mrr']:.2f} | "
                     f"{s['coverage']:.2f} | {s['selective_accuracy']['value']:.2f} | "
                     f"{s['phi_c']['1.0']:.2f} |")
    return "\n".join(lines) + "\n"
