"""Δ optimization surface (ported from bfl/eval/compare.py). None never counts as solved/broken."""
from __future__ import annotations


def compare(base: dict, head: dict) -> dict:
    """base/head are {case_id: resolved bool|None}. Returns newly_solved / newly_broken (sorted)."""
    keys = sorted(set(base) | set(head))
    return {
        "newly_solved": [k for k in keys if base.get(k) is False and head.get(k) is True],
        "newly_broken": [k for k in keys if base.get(k) is True and head.get(k) is False],
    }
