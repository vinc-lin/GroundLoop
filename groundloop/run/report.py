"""Render a self-scoring run scorecard to markdown — the per-stage summary + a per-case table in the
shape of docs/2026-07-11-functional-10case-e2e-findings.md (an artifact, not hand-tallied prose)."""
from __future__ import annotations


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _iso1(localize) -> float | None:
    iso = localize.get("isolated")
    return iso["file@1"] if iso else None


def render_run_markdown(card: dict) -> str:
    ov = card["overall"]
    m, lz, fx = ov["match"], ov["localize"], ov["fix"]
    lines = ["# Self-scoring run scorecard", "", f"- cases: {card['n_cases']}",
             f"- match: recall@1 {_fmt(m['recall@1'])} · recall@3 {_fmt(m['recall@3'])} · "
             f"recall@5 {_fmt(m['recall@5'])}",
             f"- localize: as-run file@1 {_fmt(lz['as_run']['file@1'])} · "
             f"isolated file@1 {_fmt(_iso1(lz))}"]
    if fx:
        rs = fx.get("resolved_rate_strict")
        rsv = rs["value"] if isinstance(rs, dict) else None
        lines.append(f"- fix: gradeable {fx['n_gradeable']} · "
                     f"ungradeable(no_source) {fx['n_ungradeable_no_source']} · "
                     f"resolved_strict {_fmt(rsv)}")
    if card.get("by_bug_kind"):
        for bk, sub in sorted(card["by_bug_kind"].items()):
            sm = sub["match"]
            lines.append(f"- by_bug_kind[{bk}]: n={sm['n']} match recall@1 {_fmt(sm['recall@1'])} · "
                         f"localize isolated@1 {_fmt(_iso1(sub['localize']))}")
    lines += ["", "## Per-case",
              "| case | match rank | localize as-run@1 | localize isolated@1 | fix |",
              "|---|---|---|---|---|"]
    for r in card.get("cases", []):
        lines.append(f"| {r['case_id']} | {r['rank']} | {_fmt(r['as_run@1'])} | "
                     f"{_fmt(r['isolated@1'])} | {r['fix']} |")
    return "\n".join(lines) + "\n"
