# Type-2 LLM-Judge Arms (E3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add the `+LLM-judge` matcher strategy — an `LLMJudgeIndex` that reranks a base index's top-k candidate repos via a gateway model — so the eval gains the two arms testing whether an LLM adjudicator beats retrieval, with per-run cost captured.

**Architecture:** Pure edge composition (`core/` frozen). `LLMJudgeIndex(base_index, judge, top_k)` implements the `CodeIndex` protocol: it takes the base ranking, sends the top-k repo names + the (scrubbed) signal query to a `Judge`, and reorders by the judge's verdict. The judge sees ONLY loop-visible inputs (candidate names + scrubbed signals) — never the oracle — so it must reason behavior→repo. `Judge` is a protocol with a hermetic `StubJudge` (canned) and a live `GatewayJudge` (adapted from knowledgeLoop). Cost is captured on the judge object via the migrated `cost.py`. Live path → Type-2 gated.

**Tech Stack:** Python 3.12, pytest (hermetic via `StubJudge`; live arm `skipif`-gated). Migrates knowledgeLoop `eval/cost.py` + adapts `eval/judge.py:GatewayJudge`. Reuses the E1-C `eval` harness + E2 `SemanticAtlasIndex` (a judge can wrap either base).

**Canonical design:** [`docs/type2-evaluation.md`](../../type2-evaluation.md) §6.1 (+LLM-judge arm), §7 (cost). Eval stage **E3**; builds on E1-C + E2.

---

## File Structure

- **Create** `groundloop/eval/cost.py` — migrated `PRICES`/`cost_of`/`tokens_from_raw`/`cost_from_raw` (+ DeepSeek row).
- **Create** `groundloop/adapters/index/atlas_judge.py` — `Judge`, `StubJudge`, `GatewayJudge`, `LLMJudgeIndex`.
- **Modify** `groundloop/eval/arms.py` — `build_arms(..., judge_index=None)` adds judge arms.
- **Modify** `groundloop/cli/__init__.py` — `gloop eval --judge`.
- **Create** `tests/eval/test_cost.py`, `tests/adapters/test_atlas_judge.py`, `tests/e2e/test_judge_arm_live.py` (gated), extend `tests/eval/test_arms.py`.

**Commands:** as before. Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## Task 1: Migrate `cost.py`

**Files:** Create `groundloop/eval/cost.py`; Test `tests/eval/test_cost.py`.

- [ ] **Step 1: Failing test** — `tests/eval/test_cost.py`:

```python
from groundloop.eval.cost import cost_of, tokens_from_raw, cost_from_raw, PRICES


def test_cost_of_uses_price_row():
    # 1M input + 1M output at (10, 20) per 1e6 -> 30.0
    c = cost_of(1_000_000, 1_000_000, "m", prices={"m": (10.0, 20.0)})
    assert abs(c - 30.0) < 1e-9


def test_cost_of_unknown_model_is_zero():
    assert cost_of(1000, 1000, "nope", prices={"m": (1.0, 1.0)}) == 0.0


def test_tokens_and_cost_from_raw():
    raw = {"usage": {"input_tokens": 12, "output_tokens": 3}, "total_cost_usd": 0.0042}
    assert tokens_from_raw(raw) == (12, 3)
    assert abs(cost_from_raw(raw) - 0.0042) < 1e-9
    assert tokens_from_raw("bad") == (0, 0)
    assert cost_from_raw(None) == 0.0


def test_deepseek_priced():
    assert "deepseek-chat" in PRICES     # the served workhorse model must have a row
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/eval/cost.py` (migrate verbatim, extend PRICES):

```python
"""Token->USD cost for live eval arms (migrated from knowledgeLoop eval/cost.py).

PRICES is ILLUSTRATIVE per 1e6 tokens (input, output) — CONFIRM before a billed run; the scorecard
records the table actually used so a stale row is visible, not silent."""
from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.28, 0.42),          # the served produce/judge workhorse (illustrative)
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}


def cost_of(input_tokens: int, output_tokens: int, model: str, *, prices: dict = PRICES) -> float:
    row = prices.get(model)
    if row is None:
        return 0.0
    in_price, out_price = row
    return input_tokens / 1_000_000 * in_price + output_tokens / 1_000_000 * out_price


def tokens_from_raw(raw) -> tuple[int, int]:
    usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def cost_from_raw(raw) -> float:
    if not isinstance(raw, dict):
        return 0.0
    try:
        return float(raw.get("total_cost_usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): migrate cost.py (token->USD, DeepSeek row)`).

---

## Task 2: `LLMJudgeIndex` + Judge (Stub + Gateway)

**Files:** Create `groundloop/adapters/index/atlas_judge.py`; Test `tests/adapters/test_atlas_judge.py`.

- [ ] **Step 1: Failing test** — `tests/adapters/test_atlas_judge.py`:

```python
from groundloop.adapters.index.atlas_judge import LLMJudgeIndex, StubJudge
from groundloop.core.types import RepoRef, RepoScore, Signals


class _BaseIndex:
    """Deterministic base ranking a>b>c>d by score."""
    def __init__(self, order):
        self._order = order

    def rank_repos(self, signals, catalog):
        allowed = [r.name for r in catalog]
        ranked = [n for n in self._order if n in allowed]
        return [RepoScore(RepoRef(n), float(len(ranked) - i)) for i, n in enumerate(ranked)]

    def retrieve(self, repo, query):
        return [f"{repo.name}/f.ext"]


def _cat(*names):
    return [RepoRef(n) for n in names]


def test_judge_reranks_base_topk():
    base = _BaseIndex(["a", "b", "c", "d"])
    # judge flips the top-3 to c,a,b
    judge = StubJudge({("a", "b", "c"): ["c", "a", "b"]})
    idx = LLMJudgeIndex(base, judge, top_k=3)
    ranked = idx.rank_repos(Signals(classes=("X",)), _cat("a", "b", "c", "d"))
    assert [r.repo.name for r in ranked][:3] == ["c", "a", "b"]
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_non_candidate_repos_sink_below_reranked():
    base = _BaseIndex(["a", "b", "c", "d"])
    judge = StubJudge({("a", "b"): ["b", "a"]})
    idx = LLMJudgeIndex(base, judge, top_k=2)
    names = [r.repo.name for r in idx.rank_repos(Signals(classes=("X",)), _cat("a", "b", "c", "d"))]
    assert names[:2] == ["b", "a"]           # reranked top-2
    assert set(names[2:]) == {"c", "d"}      # the rest below, order among them unspecified


def test_single_candidate_returns_base_unchanged():
    base = _BaseIndex(["a"])
    idx = LLMJudgeIndex(base, StubJudge({}), top_k=3)
    ranked = idx.rank_repos(Signals(classes=("X",)), _cat("a"))
    assert [r.repo.name for r in ranked] == ["a"]   # nothing to rerank


def test_retrieve_delegates_to_base():
    idx = LLMJudgeIndex(_BaseIndex(["a"]), StubJudge({}), top_k=3)
    assert idx.retrieve(RepoRef("a"), "q") == ["a/f.ext"]


def test_stub_judge_falls_back_to_input_order_when_unmapped():
    base = _BaseIndex(["a", "b", "c"])
    idx = LLMJudgeIndex(base, StubJudge({}), top_k=3)   # empty verdict map
    names = [r.repo.name for r in idx.rank_repos(Signals(classes=("X",)), _cat("a", "b", "c"))]
    assert names == ["a", "b", "c"]                     # unchanged (judge returns candidates as-is)
```

- [ ] **Step 2: Run → fail. Step 3: Implement** `groundloop/adapters/index/atlas_judge.py`:

```python
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
```

- [ ] **Step 4: Run → pass. Step 5: ruff + commit** (`feat(eval): LLMJudgeIndex + Stub/GatewayJudge (repo rerank)`).

---

## Task 3: Judge arms in the factory + `gloop eval --judge` + gated test

**Files:** Modify `groundloop/eval/arms.py`, `groundloop/cli/__init__.py`; extend `tests/eval/test_arms.py`; create `tests/e2e/test_judge_arm_live.py`.

- [ ] **Step 1: Failing tests** —

Add to `tests/eval/test_arms.py`:
```python
def test_build_arms_adds_judge_when_index_given():
    from groundloop.eval.arms import build_arms
    arms = build_arms(membership_index=_FakeIndex(), judge_index=_FakeIndex())
    names = {a.name for a in arms}
    assert {"judge+text", "judge+logs"} <= names
```

`tests/e2e/test_judge_arm_live.py`:
```python
import os
import pytest

_GATE = bool(os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_PRODUCE_API_KEY not set — live judge arm skipped")
def test_gateway_judge_reranks_live(tmp_path):
    """Live: GatewayJudge reorders candidate repos via the gateway model + tracks cost."""
    from groundloop.adapters.index.atlas_judge import GatewayJudge
    judge = GatewayJudge(os.environ["KLOOP_PRODUCE_BASE_URL"], os.environ["KLOOP_PRODUCE_API_KEY"],
                         os.environ.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"))
    order = judge.rerank("UnsatisfiedLinkError native audio underrun liboboe",
                         ["osmand", "oboe", "newpipe"])
    assert set(order) == {"osmand", "oboe", "newpipe"}   # a permutation of the candidates
    assert judge.calls == 1
```

Add the help test to `tests/eval/test_cli_eval.py`:
```python
def test_eval_help_lists_judge_flag():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "groundloop.cli", "eval", "--help"],
                         capture_output=True, text=True)
    assert "--judge" in out.stdout
```

- [ ] **Step 2: Run → fail. Step 3: Implement** —

`build_arms` in `groundloop/eval/arms.py` gains `judge_index`:
```python
def build_arms(*, membership_index, semantic_index=None, judge_index=None) -> list[Arm]:
    arms = [
        Arm("membership+text", membership_index, TextOnlyExtractor()),
        Arm("membership+logs", membership_index, AndroidSignalExtractor()),
    ]
    if semantic_index is not None:
        arms += [Arm("semantic+text", semantic_index, TextOnlyExtractor()),
                 Arm("semantic+logs", semantic_index, AndroidSignalExtractor())]
    if judge_index is not None:
        arms += [Arm("judge+text", judge_index, TextOnlyExtractor()),
                 Arm("judge+logs", judge_index, AndroidSignalExtractor())]
    return arms
```

CLI in `groundloop/cli/__init__.py` — add the flag to the `eval` subparser:
```python
    ev.add_argument("--judge", action="store_true",
                    help="add the LLM-judge arms (reranks membership top-k via KLOOP_PRODUCE_* model)")
```
and in `_run_eval`, build the judge index (wrapping the membership index) when set:
```python
    judge_index = None
    if args.judge:
        from groundloop.adapters.index.atlas_judge import LLMJudgeIndex, GatewayJudge
        from groundloop.config.settings import Settings as _S
        s = _S.load()
        gj = GatewayJudge(s.produce_base_url, s.produce_api_key, s.produce_main_model)
        judge_index = LLMJudgeIndex(AtlasIndex(args.index_db), gj)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db),
                                           semantic_index=semantic_index, judge_index=judge_index))
```
(Confirm `Settings` exposes `produce_base_url`/`produce_api_key`/`produce_main_model`; read `groundloop/config/settings.py`. If those attribute names differ, match the real ones — the produce CLI reads `KLOOP_PRODUCE_*`, so the fields exist under some names; adjust to match and keep behavior.)

- [ ] **Step 4: Run → pass.** Then `.venv/bin/python -m pytest -q` (full suite green; live judge test skips), `.venv/bin/ruff check groundloop tests`, `.venv/bin/gloop eval --help` (lists `--judge`).
- [ ] **Step 5: Commit** (`feat(eval): gloop eval --judge (LLM rerank arms, gated live)`).

---

## Self-Review

**Spec coverage (`type2-evaluation.md` §6.1/§7):** LLMJudgeIndex reranking base top-k (Task 2) ✓; the judge sees only scrubbed signals + candidate names, never the oracle (Task 2 — it consumes `signals.tokens()` + catalog names) ✓; two judge arms (Task 3) ✓; `gloop eval --judge` gated (Task 3) ✓; cost captured via migrated `cost.py` on `GatewayJudge.cost_usd` (Tasks 1, 2) ✓; gated live test (Task 3) ✓. **Deferred (noted):** per-arm cost in the scorecard JSON — `GatewayJudge.cost_usd` is tracked and can be surfaced via the CLI; threading it into `MatchRecord`→scorecard is a fast-follow (the scorecard's `cost` block stays a reserved field until then); RRF-hybrid base for the judge (judge can already wrap `SemanticAtlasIndex` — the CLI wires it over membership for the clean A/B).

**Placeholder scan:** none.

**Type consistency:** `LLMJudgeIndex.rank_repos(signals, catalog) -> list[RepoScore]` matches the `CodeIndex` protocol (drops into `build_arms`/`EvalRunner` identically); `Judge.rerank(query, candidates) -> list[str]` implemented by both `StubJudge` and `GatewayJudge`; `build_arms(judge_index=...)` extends the E1-C/E2 signature additively (defaults `None`); `cost_of` reused by `GatewayJudge`; `RepoScore(repo, score)` construction matches `core/types.py`.
