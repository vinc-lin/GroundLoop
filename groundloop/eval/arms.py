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


def build_arms(*, membership_index, semantic_index=None, judge_index=None) -> list[Arm]:
    arms = [
        Arm("membership+text", membership_index, TextOnlyExtractor()),
        Arm("membership+logs", membership_index, AndroidSignalExtractor()),
    ]
    if semantic_index is not None:
        arms += [
            Arm("semantic+text", semantic_index, TextOnlyExtractor()),
            Arm("semantic+logs", semantic_index, AndroidSignalExtractor()),
        ]
    if judge_index is not None:
        arms += [
            Arm("judge+text", judge_index, TextOnlyExtractor()),
            Arm("judge+logs", judge_index, AndroidSignalExtractor()),
        ]
    return arms
