"""Deterministic, oracle-free localize: candidate repo-relative paths from the matched repo."""
from __future__ import annotations

from groundloop.core.types import RepoRef
from groundloop.fixeval.patch import norm_path


def localize(index, repo: str, signals, summary: str = "", *, k: int = 5) -> list[str]:
    """Query = signals.tokens() (fallback: summary). index.retrieve(RepoRef(repo), query) → dedup
    top-k repo-relative paths. Empty result => localize-abstain."""
    query = " ".join(signals.tokens()) if signals.tokens() else summary
    if not query.strip():
        return []
    out: list[str] = []
    for hit in index.retrieve(RepoRef(repo), query):
        p = norm_path(hit)
        if p and p not in out:
            out.append(p)
        if len(out) >= k:
            break
    return out
