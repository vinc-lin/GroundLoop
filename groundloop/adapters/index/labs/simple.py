from __future__ import annotations
import json
from pathlib import Path
from typing import Sequence
from groundloop.core.types import Signals, RepoRef, RepoScore


class TokenIndex:
    """Membership-overlap repo ranker over a {repo: [tokens]} fixture. Prefix-aware so a signal token
    `org.wysaid.nativePort.CGEImageHandler` matches an indexed namespace prefix `org.wysaid`."""

    def __init__(self, index_path: str):
        self.index = json.loads(Path(index_path).read_text())

    def _hits(self, tok: str, repo_tokens: list[str]) -> str | None:
        for rt in repo_tokens:
            if tok == rt or tok.startswith(rt + ".") or rt.startswith(tok) or rt.split(".")[0] in tok:
                return rt
        return None

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        toks = signals.tokens()
        scored: list[RepoScore] = []
        for ref in catalog:
            repo_tokens = self.index.get(ref.name, [])
            ev = [t for t in toks if self._hits(t, repo_tokens)]
            scored.append(RepoScore(repo=ref, score=float(len(ev)), evidence=tuple(ev)))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return []   # within-repo file retrieval arrives with the real atlas engine (later milestone)
