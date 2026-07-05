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


def build_arms(*, membership_index) -> list[Arm]:
    return [
        Arm("membership+text", membership_index, TextOnlyExtractor()),
        Arm("membership+logs", membership_index, AndroidSignalExtractor()),
    ]
