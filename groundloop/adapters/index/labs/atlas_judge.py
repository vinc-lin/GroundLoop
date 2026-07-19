"""CodeIndex that reranks a base index's top-k candidate repos via an LLM judge (the +judge arm).

The judge sees only candidate repo names + the scrubbed signal query — never the oracle — so it
reasons behavior->repo. GatewayJudge adapted from knowledgeLoop eval/judge.py; StubJudge is the
hermetic substitute. Live (GatewayJudge) -> Type-2/gated (docs §6.1)."""
from __future__ import annotations

from typing import Protocol, Sequence

from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.eval.cost import cost_of


class Judge(Protocol):
    def rerank(self, query: str, candidates: list[str]) -> list[str]: ...


class StubJudge:
    """Canned reranks keyed by the candidate tuple; unmapped -> candidates unchanged. For tests."""
    def __init__(self, verdicts: dict):
        self._v = verdicts

    def rerank(self, query: str, candidates: list[str]) -> list[str]:
        return list(self._v.get(tuple(candidates), candidates))


class GatewayJudge:
    """LLM rerank via the gateway chat endpoint (temperature 0). Tracks cumulative USD in .cost_usd.

    Returns candidates reordered by the model's judgement; on any malformed/error response it
    falls back to the input order (never crashes the eval)."""
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self.cost_usd = 0.0
        self.calls = 0

    def rerank(self, query: str, candidates: list[str]) -> list[str]:
        import httpx
        self.calls += 1
        prompt = (
            "A defect ticket produced these failure signals. Rank the candidate repositories from "
            "MOST to LEAST likely to OWN the defect. Answer ONLY a comma-separated list of the "
            "repo names in ranked order, nothing else.\n\n"
            f"SIGNALS: {query}\n\nCANDIDATES: {', '.join(candidates)}\n\nRanked:")
        try:
            resp = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}"},
                              json={"model": self._model, "temperature": 0,
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            self.cost_usd += cost_of(int(usage.get("prompt_tokens", 0)),
                                     int(usage.get("completion_tokens", 0)), self._model)
        except Exception:      # noqa: BLE001 — never sink the eval on a judge hiccup
            return list(candidates)
        return _parse_order(text, candidates)


def _parse_order(text: str, candidates: list[str]) -> list[str]:
    """Extract a ranked subset of `candidates` from the model's free text; append any it omitted."""
    lowered = text.lower()
    picked, seen = [], set()
    # honor the order names appear in the reply
    for tok in [t.strip() for t in text.replace("\n", ",").split(",")]:
        for c in candidates:
            if c.lower() == tok.lower() and c not in seen:
                picked.append(c)
                seen.add(c)
    if not picked:                                  # fallback: order by first mention
        picked = sorted((c for c in candidates), key=lambda c: (lowered.find(c.lower()) + 1) or 1e9)
        seen = set(picked)
    picked += [c for c in candidates if c not in seen]
    return picked


class LLMJudgeIndex:
    def __init__(self, base_index, judge: Judge, *, top_k: int = 5):
        self.base = base_index
        self.judge = judge
        self.top_k = top_k

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        base = self.base.rank_repos(signals, catalog)
        cands = [r.repo.name for r in base[:self.top_k]]
        if len(cands) <= 1:
            return base
        ordered = self.judge.rerank(" ".join(signals.tokens()), cands)
        score = {name: float(len(ordered) - i) for i, name in enumerate(ordered)}
        ranked = [RepoScore(rs.repo, score.get(rs.repo.name, 0.0)) for rs in base]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        return self.base.retrieve(repo, query)
