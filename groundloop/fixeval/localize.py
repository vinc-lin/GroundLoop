"""Deterministic, oracle-free localize: candidate repo-relative paths from the matched repo."""
from __future__ import annotations

from groundloop.core.types import RepoRef
from groundloop.fixeval.patch import norm_path


def localize(index, repo: str, signals, summary: str = "", *, k: int = 5,
             skill_query: str = "") -> list[str]:
    """Query = signals.tokens() (fallback: summary), optionally biased by a Skill's skill_query (its
    .signals + the 'Localize:' hint). index.retrieve(RepoRef(repo), query) -> dedup top-k repo-relative
    paths. Empty result => localize-abstain. skill_query='' is BYTE-IDENTICAL to the pre-A5 query."""
    query = " ".join(signals.tokens()) if signals.tokens() else summary
    if skill_query.strip():
        query = (query + " " + skill_query).strip()
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
