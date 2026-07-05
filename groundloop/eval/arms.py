"""Arm construction: strategy x signal. v1 = membership x {text-only, +logs}
(docs/type2-evaluation.md §6). Semantic (E2) / judge (E3) add strategies later."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.extractors import TextOnlyExtractor


@dataclass(frozen=True)
class Arm:
    name: str
    index: Any        # a CodeIndex: .rank_repos(signals, catalog)
    extractor: Any    # .extract(logs, ticket) -> Signals
    tau_margin: float | None = None   # per-arm abstain thresholds; None -> runner default
    tau_score: float | None = None


# Per-strategy abstain thresholds so refusal is REACHABLE on each score scale: FTS5 integer evidence
# counts (membership) vs bge-m3 cosine ~0.3-0.7 (semantic) vs the judge ladder. (docs SP1 §1.3 item 4)
_TAU = {"membership": (1.0, 1.0), "semantic": (0.05, 0.0), "judge": (1.0, 0.0)}


def build_arms(*, membership_index, semantic_index=None, judge_index=None) -> list[Arm]:
    mm, msc = _TAU["membership"]
    arms = [
        Arm("membership+text", membership_index, TextOnlyExtractor(), mm, msc),
        Arm("membership+logs", membership_index, AndroidSignalExtractor(), mm, msc),
    ]
    if semantic_index is not None:
        sm, ssc = _TAU["semantic"]
        arms += [
            Arm("semantic+text", semantic_index, TextOnlyExtractor(), sm, ssc),
            Arm("semantic+logs", semantic_index, AndroidSignalExtractor(), sm, ssc),
        ]
    if judge_index is not None:
        jm, jsc = _TAU["judge"]
        arms += [
            Arm("judge+text", judge_index, TextOnlyExtractor(), jm, jsc),
            Arm("judge+logs", judge_index, AndroidSignalExtractor(), jm, jsc),
        ]
    return arms
