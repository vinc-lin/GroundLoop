# Localize recall — mechanical fixes (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make `--localize rerank` actually use the bge-m3 vectors already on disk and match CamelCase
identifiers, and make any degradation LOUD — so the next localize measurement is honest.

**Architecture:** Three grounded changes, all at engine/adapter/composition-root level — **no `core/` edit, no
atlas DDL edit** (A3 is content-only, behind a build flag). (1) Extract the existing CamelCase splitter into a
shared `engines/atlas/tokenize.py` so query-side (unchanged) and a new index-side path call the same code.
(2) Index-time CamelCase expansion behind `KLOOP_INDEX_CAMELCASE` (default OFF → default atlas unchanged).
(3) Harden the reranker's embedder path: fail-fast when the arm is requested but no embedder exists, and
surface (never swallow) per-case embed failures.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check
groundloop tests` (line length 110). SQLite/FTS5, bge-m3 via a TEI `GatewayEmbedder`.

**Scope note:** This is Phase 1 of `docs/superpowers/specs/2026-07-17-localize-recall-cascade-design.md`. The
benchmark re-point (§3.5), the literal-anchor cascade (§3.2–3.3), and the soft gate (§3.4) are **separate
follow-on plans** — do NOT build them here.

---

## File Structure

- **Create:** `groundloop/engines/atlas/tokenize.py` — `split_identifier(name) -> list[str]` (the single
  CamelCase/snake/digit splitter). One responsibility: identifier → sub-word tokens.
- **Modify:** `groundloop/engines/atlas/store.py` — `_fts_query` calls `split_identifier` (behavior-preserving).
- **Modify:** `groundloop/engines/atlas/index.py` — when `KLOOP_INDEX_CAMELCASE` is set, append
  `split_identifier(...)` sub-words to each symbol unit's indexed text before insert.
- **Modify:** `groundloop/config/settings.py` — add `index_camelcase: bool` (reads `KLOOP_INDEX_CAMELCASE`).
- **Modify:** `groundloop/cli/__init__.py` — the `--localize rerank` construction: fail-fast (`return 2`) when
  no embedder can be built; thread `embed_max_chars`/`embed_batch` into the reranker's `GatewayEmbedder`.
- **Modify:** `groundloop/run/grade_run.py` — same fail-fast in the isolated localize diagnostic (`_localize_index_for`).
- **Modify:** `groundloop/adapters/index/rerank_localize.py` — replace `except Exception: pass` (line ~172)
  with a counted, logged degrade; expose `.embed_failures`.
- **Test:** `tests/engines/test_tokenize.py`, `tests/engines/test_index_camelcase.py`,
  `tests/adapters/test_rerank_localize_embed.py`, `tests/cli/test_localize_rerank_failfast.py`
  (place under the existing test layout; mirror a sibling test's imports/fixtures).

---

### Task 1: Extract `split_identifier()` (DRY the CamelCase splitter)

**Files:**
- Create: `groundloop/engines/atlas/tokenize.py`
- Test: `tests/engines/test_tokenize.py`
- Modify: `groundloop/engines/atlas/store.py` (`_fts_query`, ~line 156-184)

- [ ] **Step 1: Write the failing test**

```python
# tests/engines/test_tokenize.py
from groundloop.engines.atlas.tokenize import split_identifier


def test_splits_pascal_case():
    assert split_identifier("ScreenshotUtils") == ["screenshot", "utils"]


def test_splits_camel_and_snake_and_digits():
    assert split_identifier("logManagementFragment") == ["log", "management", "fragment"]
    assert split_identifier("HTTP2Client") == ["http", "2", "client"]  # acronym + digit run
    assert split_identifier("audio_focus_helper") == ["audio", "focus", "helper"]


def test_single_word_returns_itself_lowercased():
    assert split_identifier("Screenshot") == ["screenshot"]


def test_empty_and_symbols():
    assert split_identifier("") == []
    assert split_identifier("__") == []
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/engines/test_tokenize.py -q`
Expected: FAIL (`ModuleNotFoundError: groundloop.engines.atlas.tokenize`).

- [ ] **Step 3: Implement `split_identifier`** by lifting the exact regex already in `store.py:_fts_query`
(line 171 word-split + line 177 camelCase split), lowercased and deduped, order-preserving.

```python
# groundloop/engines/atlas/tokenize.py
"""Identifier tokenization shared by the FTS query builder (query side) and the optional index-time
CamelCase expansion (build side). One splitter, two call sites — keeps query/index tokenization identical."""
from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9]+")
_SUB = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)")


def split_identifier(name: str) -> list[str]:
    """`ScreenshotUtils` -> ['screenshot','utils']. Splits on non-alphanumerics AND camelCase/PascalCase/
    digit runs; lowercased, order-preserving, deduped. '' / all-symbols -> []."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in _WORD.findall(name or ""):
        for part in _SUB.findall(tok):
            p = part.lower()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out
```

- [ ] **Step 4: Run test, verify PASS.** `.venv/bin/python -m pytest tests/engines/test_tokenize.py -q`

- [ ] **Step 5: Refactor `_fts_query` to call `split_identifier` (behavior-preserving).** In
`store.py`, replace the inline `parts = re.findall(...)` loop so the sub-words come from
`split_identifier(tok)`; keep the "emit the whole token as-is, then its sub-words, OR-joined, quoted" output
shape EXACTLY (so ranking is unchanged). Verify no other regex behavior changed.

- [ ] **Step 6: Run the FTS/index suite, verify still green.**
Run: `.venv/bin/python -m pytest tests/ -q -k "atlas or fts or index or store"`
Expected: PASS (no ranking/behavior change).

- [ ] **Step 7: Commit.**

```bash
git add groundloop/engines/atlas/tokenize.py groundloop/engines/atlas/store.py tests/engines/test_tokenize.py
git commit -m "refactor(atlas): extract split_identifier; _fts_query reuses it"
```

---

### Task 2: A3 — index-time CamelCase expansion behind `KLOOP_INDEX_CAMELCASE`

**Files:**
- Modify: `groundloop/config/settings.py` (add `index_camelcase`)
- Modify: `groundloop/engines/atlas/index.py` (append sub-words to indexed text when the flag is set)
- Test: `tests/engines/test_index_camelcase.py`

- [ ] **Step 1: Write the failing test** — build a tiny in-memory/temp atlas with one symbol `ScreenshotUtils`,
index it with the flag ON, and assert a plain-word `screenshot` keyword_search finds it (and does NOT when the
flag is OFF). Mirror the fixture-atlas construction in the existing atlas tests (find them via
`rg -l "reindex_repo|Store\(" tests/`).

```python
# tests/engines/test_index_camelcase.py  (skeleton — adapt fixture helpers to the existing atlas test style)
import os
from groundloop.engines.atlas.store import Store  # match the real import used by sibling atlas tests


def _index_one(tmp_path, camelcase: bool, unit_name="ScreenshotUtils"):
    if camelcase:
        os.environ["KLOOP_INDEX_CAMELCASE"] = "1"
    else:
        os.environ.pop("KLOOP_INDEX_CAMELCASE", None)
    # ... build a Store at tmp_path, index one repo with a single symbol unit whose qualified_name/name
    # is `unit_name`; return the Store. Reuse the existing test's unit-construction helper.


def test_camelcase_flag_makes_subword_findable(tmp_path):
    st = _index_one(tmp_path, camelcase=True)
    rows = st.keyword_search("screenshot", k=5, repos=["r"], kinds=["symbol"])
    assert any("ScreenshotUtils" in (u.qualified_name or u.name or "") for u, _ in rows)


def test_default_off_keeps_atlas_unchanged(tmp_path):
    st = _index_one(tmp_path, camelcase=False)
    rows = st.keyword_search("screenshot", k=5, repos=["r"], kinds=["symbol"])
    assert not rows  # plain-word query cannot match the atomic token when the flag is OFF
```

- [ ] **Step 2: Run it, verify it fails** (flag not read yet). `.venv/bin/python -m pytest tests/engines/test_index_camelcase.py -q`

- [ ] **Step 3: Add the setting.** In `settings.py`, add `index_camelcase: bool` reading
`os.environ.get("KLOOP_INDEX_CAMELCASE", "").strip() not in ("", "0", "false")` (match the existing bool-env idiom).

- [ ] **Step 4: Apply at index time.** In `index.py`, where a symbol unit's FTS text is assembled (the
`name+label+qn+file` region — find it via `rg -n "qualified_name|def build_units|text=" groundloop/engines/atlas/index.py`),
when `settings.index_camelcase` is set, append `" ".join(split_identifier(qualified_name))` (and the symbol
name) to the indexed text. **Do NOT change the schema / column set — only the text CONTENT grows.** Guard so
the default (flag OFF) produces byte-identical unit text to today.

- [ ] **Step 5: Run test, verify PASS.** `.venv/bin/python -m pytest tests/engines/test_index_camelcase.py -q`

- [ ] **Step 6: Assert schema unchanged.** Add an assertion (or reuse an existing schema test) that the
`CREATE ... fts5` DDL string is unchanged with the flag on. Run: `rg -n "CREATE VIRTUAL TABLE|USING fts5" groundloop/engines/atlas/store.py`
and confirm the plan touched none of it.

- [ ] **Step 7: Commit.**

```bash
git add groundloop/config/settings.py groundloop/engines/atlas/index.py tests/engines/test_index_camelcase.py
git commit -m "feat(atlas): opt-in KLOOP_INDEX_CAMELCASE index-time identifier expansion (content-only)"
```

---

### Task 3: A1 — fail-fast when `--localize rerank` has no embedder

**Files:**
- Modify: `groundloop/cli/__init__.py` (the `rerank` localize branch + `_build_embedder` call site)
- Modify: `groundloop/run/grade_run.py` (`_localize_index_for` isolated diagnostic)
- Test: `tests/cli/test_localize_rerank_failfast.py`

- [ ] **Step 1: Write the failing test.** With `KLOOP_EMBED_BASE_URL` unset, invoking the run/eval path with
`--localize rerank` must exit non-zero with a clear message (mirror the `--match-arm semantic` no-embedder
behavior). Find that existing pattern first: `rg -n "emb is None|return 2|no embedder|KLOOP_EMBED_BASE_URL" groundloop/cli/__init__.py`
and clone its test style.

```python
# tests/cli/test_localize_rerank_failfast.py  (adapt invocation to how sibling CLI tests call the entrypoint)
import os


def test_rerank_without_embedder_fails_fast(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    rc = _invoke_run(localize="rerank")  # sibling helper / Runner; assert it does NOT build a keyword-only rerank
    assert rc == 2
    assert "embed" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run it, verify it fails** (today it silently builds a keyword-only reranker).

- [ ] **Step 3: Implement fail-fast.** At the `--localize rerank` construction, after `_build_embedder()`
returns, add: `if embedder is None: print("--localize rerank requires an embedder (set KLOOP_EMBED_BASE_URL)", file=sys.stderr); return 2`
— matching the `--match-arm semantic` guard. Apply the SAME guard in `grade_run._localize_index_for` so the
isolated diagnostic cannot silently diverge from the live run.

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Guard the Core default is untouched.** Run `.venv/bin/python -m pytest tests/run/test_core_defaults_unchanged.py -q`
Expected: PASS (default localize is still `atlas`; rerank stays opt-in).

- [ ] **Step 6: Commit.**

```bash
git add groundloop/cli/__init__.py groundloop/run/grade_run.py tests/cli/test_localize_rerank_failfast.py
git commit -m "feat(localize): fail-fast when --localize rerank has no embedder (no silent keyword-only)"
```

---

### Task 4: A1 — surface (never swallow) per-case embed failures

**Files:**
- Modify: `groundloop/adapters/index/rerank_localize.py` (`__init__` + `_gen_hits`, line ~161-174)
- Test: `tests/adapters/test_rerank_localize_embed.py`

- [ ] **Step 1: Write the failing test.** A `RerankLocalizeIndex` built with an embedder whose `.embed`
raises must NOT silently return keyword-only with no trace — it must increment a visible counter.

```python
# tests/adapters/test_rerank_localize_embed.py
from groundloop.adapters.index.rerank_localize import RerankLocalizeIndex


class _BoomEmbedder:
    def embed(self, texts):
        raise RuntimeError("embed 500")


def test_embed_failure_is_counted_not_silent(atlas_store_with_one_repo):  # reuse an existing fixture
    idx = RerankLocalizeIndex(match_index=_StubMatch(), store=atlas_store_with_one_repo,
                              embedder=_BoomEmbedder(), judge=None)
    idx.note_signals(_signals_with_one_token("screenshot"))
    _ = idx.retrieve(_repo("r"), "screenshots are JPG not PNG")
    assert idx.embed_failures == 1  # a swallowed embed error must be visible
```

- [ ] **Step 2: Run it, verify it fails** (no `embed_failures` attribute today).

- [ ] **Step 3: Implement the counted degrade.** In `__init__` add `self.embed_failures = 0`. In `_gen_hits`,
change the `except Exception: pass` (line ~172-173) to:

```python
            except Exception as e:  # noqa: BLE001 — degrade to keyword-only, but VISIBLY
                self.embed_failures += 1
                import logging
                logging.getLogger("groundloop.localize").warning(
                    "rerank embed lane failed (%s); degrading to keyword-only for repo=%s", e, repo_name)
        return self._keyword_hits(repo_name, query_str)
```

(Keep the outer keyword-only fallback; only the swallow becomes counted+logged.)

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Thread `embed_failures` into the run manifest** (so a partially-degraded run is visible in
`manifest.json`, per spec §3.1). Find where the reranker/localize index is summarized into the manifest:
`rg -n "manifest|embed_failures|cost_usd" groundloop/run/*.py groundloop/cli/__init__.py`. Add
`embed_failures` alongside the existing `cost_usd` aggregation. If no clean seam exists, note it in the commit
and leave the counter exposed on the adapter (a follow-up wires the manifest). Do NOT invent a manifest field
schema not already present.

- [ ] **Step 6: Commit.**

```bash
git add groundloop/adapters/index/rerank_localize.py tests/adapters/test_rerank_localize_embed.py
git commit -m "feat(localize): count+log rerank embed-lane failures (no silent keyword-only degrade)"
```

---

### Task 5: A1 — thread `embed_max_chars`/`embed_batch` into the reranker's embedder

**Files:**
- Modify: `groundloop/cli/__init__.py` (the reranker's `GatewayEmbedder(...)` construction)
- Test: extend `tests/cli/test_localize_rerank_failfast.py` or a small construction test

- [ ] **Step 1: Write the failing test.** The embedder built for `--localize rerank` must carry
`max_chars=settings.embed_max_chars` (not the 8000 default that collides with the server 413 cap). Assert the
constructed `GatewayEmbedder`'s `max_chars` equals the setting.

```python
def test_rerank_embedder_uses_configured_max_chars(monkeypatch):
    monkeypatch.setenv("KLOOP_EMBED_BASE_URL", "http://x")
    monkeypatch.setenv("KLOOP_EMBED_MAX_CHARS", "2000")
    emb = _build_rerank_embedder()  # the helper the rerank branch uses
    assert emb.max_chars == 2000
```

- [ ] **Step 2: Run it, verify it fails** (current call site omits `max_chars`/`batch` — see the bare
`GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)` sites in `cli/__init__.py`).

- [ ] **Step 3: Implement.** In the rerank embedder construction (and `_build_embedder` if it's the shared
path), pass `max_chars=st.embed_max_chars` and the batch size, matching the fullest existing call site
(`GatewayEmbedder(..., max_chars=settings.embed_max_chars)`). Confirm `GatewayEmbedder.__init__` accepts and
stores `max_chars` (it does — see `engines/atlas/embed.py`).

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Commit.**

```bash
git add groundloop/cli/__init__.py tests/cli/test_localize_rerank_failfast.py
git commit -m "fix(localize): thread embed_max_chars/batch into the rerank embedder (avoid 413→swallow)"
```

---

### Task 6: Gate — full suite, ruff, and the Core-defaults invariant

- [ ] **Step 1: Full hermetic suite.** `.venv/bin/python -m pytest -q` — Expected: all green (0 failures).
- [ ] **Step 2: Lint.** `.venv/bin/ruff check groundloop tests` — Expected: clean.
- [ ] **Step 3: Invariants.** `.venv/bin/python -m pytest tests/test_invariants.py tests/run/test_core_defaults_unchanged.py -q`
— Expected: PASS (no anti-leak / Core-default regression; default atlas build unchanged with the flag OFF).
- [ ] **Step 4: Do NOT commit if red.** Only after green + clean, the plan's code tasks are complete.

---

## Live runbook (orchestrator, NOT a subagent task) — the `[proxy]` read

Run off ext4 (`/home/vinc` directly), `.env` sourced (`set -a; . ./.env; set +a`), one atlas at a time.

1. **Build a CamelCase-expanded 6-repo `[proxy]` atlas:** `KLOOP_INDEX_CAMELCASE=1 gloop index --registry <6-repo.toml>`
   into a fresh DB path (keep the baseline atlas untouched for the A/B).
2. **Isolated localize recall A/B** (mirror the prior `localize_ab.py` isolated harness, match-independent on the
   oracle repo), three arms on the mine74 slice, split by regime:
   (i) baseline atlas + embedder OFF (reproduces the keyword-only floor),
   (ii) baseline atlas + embedder ON (vector lane fires),
   (iii) CamelCase atlas + embedder ON. Report recall@1/3/5 + `localize_hit`.
3. **Match regression check:** run the Stage-1 match eval on the CamelCase atlas vs baseline — A3 changes the
   shared index; confirm match recall does not regress before this atlas is considered for anything downstream.
4. **Log** every number to `docs/results-log.md`, `[proxy]`-tagged, with the atlas identity + embed URL
   presence recorded (so a future reader can tell the vector lane was actually ON).

**Verification of the whole plan:** vector lane demonstrably fires (arm ii pool composition differs from arm i);
`screenshot` finds `ScreenshotUtils` under the CamelCase atlas; `--localize rerank` without an embedder exits
2; a raising embedder increments `embed_failures`; suite green + ruff clean; match does not regress on the
CamelCase atlas. The `[production]` GEI read + promotion decision follow separately.

---

## Self-review notes

- **Spec coverage (Phase 1 only):** Task 1–2 = A2-extract + A3 (spec §3.1); Task 3–5 = A1 fail-fast + surface +
  config (spec §3.1); runbook = the §4 [proxy] ablation + A3 match-regression check. Re-point (§3.5), literal
  cascade (§3.2–3.3), soft gate (§3.4) are deferred to follow-on plans — intentional, stated in Scope note.
- **Type consistency:** `split_identifier` returns `list[str]` everywhere; `embed_failures: int`;
  `index_camelcase: bool`. `keyword_search(query, k, repos, kinds)` used as in `store.py:115`.
- **No placeholders:** every code step shows code or an exact `rg`/`pytest` command. The two "find the seam via
  rg" steps (Task 2 Step 4, Task 4 Step 5) are grounded discovery, not TODOs — the target is named.
