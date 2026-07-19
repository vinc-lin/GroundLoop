# `--localize atlas_rerank` — Design

> **Date:** 2026-07-19 · **Status:** design deliverable → implementation plan next.
> **Provenance:** a localize-default review (this session). The current default `--localize atlas` (plain FTS5)
> is the only `[production]`-validated localize (7/10 file@5 on GEI) but weak at rank-1 (1/10 file@1). The
> measured lever for rank-1 is the **LLM file-judge** (`rerank`/`cascade_judge` `[proxy]`), not the embeddings.
> `--localize rerank` can't be a safe default because it **fails closed without a live embedder** (its hybrid
> pool needs one). This arm puts the judge on the **proven FTS5 recall floor** as the pool — no embedder — so it
> can be the production default while degrading to today's `atlas` behavior when the judge is unavailable.

## 1. Goal

Add `--localize atlas_rerank`: the **FTS5 `AtlasIndex.retrieve` recall pool reordered by the LLM file-judge**,
composed via the existing `pool_index` seam on `RerankLocalizeIndex` — **no embedder dependency**. Make it the
**production default** under the **Provisional-Core** governance tier (default-on on a fail-safe argument, before
a `[production]` read, reverting on debt), with a `[proxy]` `file@1` A/B as the resolver and `--localize atlas`
as the one-line revert. `core/` + the atlas schema stay **zero-diff**.

## 2. Why this shape (vs the alternatives)

- **vs `atlas` (today's default):** same FTS5 recall floor, but the judge reorders it for rank-1 precision — the
  metric `atlas` is worst at.
- **vs `rerank`:** identical judge, but the **pool comes from FTS5 instead of the hybrid bge-m3∪FTS5 pool** — so
  it needs **no embedder** and never fails closed. That is the property that makes it a viable *default*.
- **vs `cascade_judge`:** `cascade_judge` has a richer (higher-recall) pool → a higher `[proxy]` ceiling
  (0.245/0.469) but needs the embedder. `atlas_rerank` trades ceiling for **zero embedder dependency + a
  degrade-to-`atlas` floor**, which is what a *default* needs. `cascade_judge` stays the opt-in high-ceiling arm.

## 3. Mechanism (composed — no new class/file, same shape as `cascade_judge`)

- New `--localize atlas_rerank` flag value.
- In the composition root (`cli/__init__.py`, the localize-dispatch branch): build the match index, construct a
  plain `AtlasIndex(index_db)` as the **pool source**, and call
  `_build_rerank_localize(match_index, args, embedder=None, pool_index=<AtlasIndex>)`, wrapped in `SplitIndex`
  (so localize stays independent of the match arm — the existing pattern for `rerank`/`cascade`/`cascade_judge`).
- `RerankLocalizeIndex.retrieve` then takes its pool from `_pool_index_hits` (the `pool_index.retrieve()` path —
  already used by `cascade_judge`) instead of `_gen_hits`, so **`embedder` is never referenced**. The
  `GatewayFileJudge` reorders the pool, grounded (it may only reorder real pool files, never add).
- **No embedder gate for this branch.** Unlike the `rerank` branch (which fail-fasts when no embedder), the
  `atlas_rerank` branch passes `embedder=None` and does **not** check for an embedder — the FTS5 pool owns recall.

## 4. Degradation semantics — the Provisional-Core / fail-safe argument

- **No judge creds** (`KLOOP_PRODUCE_API_KEY` unset) → `_build_rerank_localize` sets `judge=None` →
  `RerankLocalizeIndex` returns the **FTS5 pool order = byte-equivalent to `--localize atlas`.** A credential-less
  production run cannot regress. This is the fail-safe floor.
- **No `--repos`** → the FTS5 pool returns bare paths, so (exactly like `cascade_judge`) the judge reranks with
  reduced context (path + CodeWiki-only, no source snippet / no CBM). Still grounded; never fabricates.
- **The one honest NEW failure mode** (which the fail-safe does *not* cover): with creds present, the judge can
  rank the true file **below** where raw FTS5 placed it → a `file@1` regression vs `atlas`. Every prior `[proxy]`
  read shows the judge *helping*, but this is unmeasured for `atlas_rerank` specifically → **the `[proxy]` A/B
  (§6) is the resolver, and `--localize atlas` is the revert.**

## 5. Governance & the default flip

- Classify `atlas_rerank` **Provisional-Core** in `capabilities.md` (the existing tier: default-on on a fail-safe
  argument before a `[production]` read; resolves to Core-or-revert on the measured `file@1` A/B). Cite the
  fail-safe floor (degrades to `atlas`) and the open resolver.
- Flip the `_resolve_arms` localize default `atlas` → `atlas_rerank` (**both profiles** — the user wants the
  production default). `--localize atlas` remains the explicit opt-out/revert.
- **Cost note (record it):** production localize now spends ~$0.0014/case whenever gateway creds are present.
- No fail-close is introduced by the flip: `atlas_rerank` needs no embedder, and without creds it degrades — so a
  default `gloop run` never refuses on account of localize.

## 6. The resolver — the `[proxy]` file@1 A/B (gated Type-2 follow-up, NOT a merge gate)

- **Measurement:** the existing isolated `file@k` localize comparison (the same harness that produced the
  `cascade_judge` numbers, `mine74` n=108), three arms: `atlas` vs `atlas_rerank` vs `cascade_judge`. Needs the
  live gateway + a real atlas + `--repos`, so it **cannot run hermetically** — it is a gated follow-up the user
  runs, logged `[proxy]` in `results-log.md`.
- **Decision rule:** if `atlas_rerank file@1 ≥ atlas file@1` → keep the default (promote toward Core on a later
  `[production]` GEI read). If `atlas_rerank file@1 < atlas` → **revert the default to `atlas`** (keep the arm
  opt-in). The plan wires nothing new for this; it documents the procedure + the revert.

## 7. Testing (Type-1 hermetic — the merge gate)

- **Pool provenance + judge reorder:** with a `StubFileJudge` (deterministic order) and a real fixture atlas,
  assert `atlas_rerank`'s candidate pool equals the FTS5 `AtlasIndex.retrieve` set for the repo, and the returned
  order is the judge's reordering of that pool (a grounded subset — no fabricated paths).
- **Fail-safe floor:** with `judge=None` (no creds), assert `atlas_rerank`'s output is **identical to
  `--localize atlas`**'s `retrieve` for the same repo/query.
- **No embedder needed:** assert building `atlas_rerank` with no embedder does not raise / does not fail-close
  (the property that distinguishes it from `rerank`).
- **Default flip:** update `tests/run/test_core_defaults_unchanged.py` (and any localize-default assertion) to
  expect `atlas_rerank`; assert `_resolve_arms` returns `atlas_rerank` for localize in both profiles.

## 8. Invariants / non-goals

- **Zero `core/` + atlas-schema edits.** No new module (composed at the root). `rerank` and `cascade_judge`
  behavior **unchanged** (the `pool_index`/embedder paths already exist).
- **Import boundary:** the `atlas_rerank` wiring uses the same **function-local lazy labs imports** as the other
  localize arms (the sanctioned seam) — the product↛labs contract stays green.
- **Deferred (YAGNI):** Option B (RRF-fuse the judge order back with the FTS5 keyword ranking) — only if the A/B
  shows the judge hurting strong keyword hits. No new eval tooling (the resolver reuses the existing harness).

## 9. Module touch-map

| Change | Target |
|---|---|
| Add `atlas_rerank` to `--localize` choices + the localize-dispatch branch (AtlasIndex pool + `embedder=None`) | `groundloop/cli/__init__.py` |
| Flip the localize default `atlas`→`atlas_rerank` | `groundloop/cli/__init__.py` (`_resolve_arms`) |
| Verify `_pool_index_hits` accepts a plain `AtlasIndex` pool (bare-path contract, same as cascade) — likely no change | `groundloop/adapters/index/labs/rerank_localize.py` |
| Hermetic tests (pool provenance, fail-safe floor, no-embedder, default) | `tests/` (new + `tests/run/test_core_defaults_unchanged.py`) |
| Governance + default + resolver + cost note | `docs/capabilities.md`, `CLAUDE.md` (gloop run defaults), `docs/module-map.md`, `docs/STATUS.md` |
| Zero-diff | `groundloop/core/**`, atlas schema |

## 10. Open questions for the plan

- Confirm `_pool_index_hits` needs no change for an `AtlasIndex` pool (cascade returns bare paths; `AtlasIndex.
  retrieve` also returns bare paths — same `list[str]` contract). The plan's first task verifies by reading it.
- Confirm no other test hard-codes the localize default as `atlas` beyond `test_core_defaults_unchanged.py`
  (grep in the plan).
