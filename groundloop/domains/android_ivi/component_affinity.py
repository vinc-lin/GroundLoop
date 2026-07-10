"""Empirical JIRA-component -> owning-repo affinity prior. Stores RAW co-occurrence counts so
leave-one-out can subtract a case's own contribution before normalizing. Runtime reads only the
loop-visible component; the LOO `exclude` argument is eval/grader-side only (never the loop path)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ComponentAffinity:
    counts: dict[str, dict[str, int]]

    @classmethod
    def load(cls, path: str) -> "ComponentAffinity":
        raw = json.loads(Path(path).read_text())
        return cls({c: {r: int(n) for r, n in repos.items()} for c, repos in raw.items()})

    def affinity(self, component: str, *, exclude: str | None = None) -> dict[str, float]:
        """L1-normalized repo weights for `component`. If `exclude` is a repo, subtract one unit of
        its count first (leave-one-out). Unknown component / zero total -> empty."""
        repos = dict(self.counts.get(component, {}))
        if exclude and exclude in repos:
            repos[exclude] -= 1
            if repos[exclude] <= 0:
                del repos[exclude]
        total = sum(repos.values())
        if total <= 0:
            return {}
        return {r: n / total for r, n in repos.items() if n > 0}
