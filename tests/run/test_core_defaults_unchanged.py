"""Governance lock: with the labs profile OFF (KLOOP_LABS unset, no --profile), the `gloop run` defaults
MUST stay Core-aligned — match `component`, localize `atlas` (the [production]-validated FTS5 floor;
`tokens`/SignalQueryIndex was reverted from default → reachable opt-in on 2026-07-15), fix `plan`. The labs arms are opt-in Candidates;
none may become a silent production default. If this test fails, a default drifted (see capabilities.md §4)."""
from __future__ import annotations


def test_core_defaults_unchanged_without_labs(monkeypatch):
    monkeypatch.delenv("KLOOP_LABS", raising=False)
    from groundloop.cli import _resolve_arms, build_parser
    args = build_parser().parse_args(
        ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
         "--index-db", "a.db", "--out", "o", "--repos", "r"])
    assert _resolve_arms(args) == ("component", "atlas", "core")   # Core-aligned defaults, profile off
    assert args.fixer == "plan"                                     # Provisional-Core fix default (unchanged)
