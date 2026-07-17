# Localize as recall-first cascade + soft gate + patch-level grading — design

**Date:** 2026-07-17 · **Status:** design (approved direction: Option B) · **Track:** Type-2 / Stage-1+fix
**Supersedes the ambition of:** the pending "wire+harden bge-m3 vector lane + CamelCase-split + re-index"
plan (that work survives as this design's **Phase 1 prerequisite**, but its *purpose* changes — see §2, §8).

---

## 0. Why this exists (the reframe)

We were about to optimize the `--localize rerank` candidate pool (wire the silently-off bge-m3 vector
lane; CamelCase-split identifiers so `screenshot` can match `ScreenshotUtils`; re-index). A first-principles
review (5-frame panel + adjudication, 2026-07-17) stopped that and asked whether the **Localize stage** is
even the right shape. It is — but two things about *how* it's used are wrong, and the recall leak is a
symptom, not the disease.

The measured failure: on functional GEI cases the rerank **judge works** — it promotes the oracle file to
rank 1 *whenever it is in the candidate pool* — but `file@5 ≈ 0.20` because the oracle is **absent from the
pool** for ~8/10 cases. Pool-widening (k=200 + noise filter + prose∪code fusion) did **not** move it. Root
causes: (1) the bge-m3 vector lane was **silently OFF** (`_build_embedder()` returns `None` when
`KLOOP_EMBED_BASE_URL` is unset, and `rerank_localize.py:172-173` swallows live embed errors with
`except: pass`); (2) FTS5 `unicode61` does not segment CamelCase. **You cannot conclude retrieval is
exhausted from an experiment run on a mis-wired config.** So the mechanical fixes are a prerequisite — but
they don't touch the two real design defects below.

## 1. Is Localize necessary? Three separate rulings (verified against code)

- **As a concept (narrow repo → files): YES, irreducible.** You cannot patch what you have not located.
- **As a HARD GATE that fix cannot escape: NO — this is the actual defect.** Verified: `core/workflow.py:35`
  is `patch = fixer.propose(wt, ticket, locations)` — fix receives the **full worktree** and the **full
  ticket** next to `locations`. Nothing in the frozen control plane restricts edits to `locations`; that
  restriction is a *convention in the fix adapter* (`planning.py:54` literally prompts "cite ONLY these").
  On functional tickets it converts a soft prior into an absolute cap: every recall miss is an
  unrecoverable fix failure. **Relaxable without editing `core/`.**
- **As a file@1-PRECISION retriever: NO — Goodhart.** The observed loss is **recall** (absence from top-k),
  not **precision** (mis-ranking); the judge already supplies precision when the file is present. Optimizing
  `file@1` sharpens a ranker that works while ignoring the binding constraint (pool coverage).
  `compare.py:25,49` currently bakes `file_recall@1` into the promotion gate — that is the metric to demote.

> **Localize's real job is RECALL.** Precision is owned downstream by the rerank judge and by the fixer.

## 2. Design overview (Option B)

A **recall-first, operator-per-information-type** localize that unions grounded tiers, plus a **soft gate**
so fix can escape a localize miss, plus a **benchmark re-point** so we stop measuring the wrong thing. Every
piece lives at **adapter / engine / grader** level. **Zero `core/` edits, zero atlas-schema (DDL) edits.**

Verified structural facts this design leans on:
1. Fix already gets the full worktree + ticket (`workflow.py:35`) → soft gate is a fix-adapter change.
2. `retrieve(chosen, ticket.summary)` gets only the summary, but `rank_repos(signals,…)` runs first on the
   **same index instance** (`workflow.py:28→33`) → a stateful adapter can stash `signals` and reuse them
   (the `signal_query.py` / `rerank_localize.py` `_last_signals` pattern). No core edit.
3. Fault-site is already gradeable off the patch: `scorecard.py:27` computes `touched_files(rec.patch_diff)`
   and intersects with the oracle → a soft-gate / agentic fixer stays measurable.

## 3. Components

### 3.1 Phase-1 prerequisites — the mechanical recall fixes (subsumes the pending plan)

- **A1 · Fire & harden the bge-m3 vector lane.** Wire the embedder for `--localize rerank`; **fail-fast**
  (hard error / non-zero exit, mirroring `--match-arm semantic` at `cli:1385-1388`) when the arm is requested
  but no embedder can be built — a rerank read must never silently degrade to keyword-only again. Replace the
  blind `except Exception: pass` (`rerank_localize.py:172-173`) with a **counted, logged, surfaced** degrade
  (per-case embed failures appear in `manifest.json`, never silent). Forward `embed_max_chars`/`embed_batch`
  into `GatewayEmbedder` (`cli:1124`) — the 8000-vs-server-413 mismatch would otherwise raise→get swallowed.
  Files: `cli/__init__.py`, `run/grade_run.py` (same wiring in the isolated diagnostic), `rerank_localize.py`.
- **A2/A3 · One CamelCase splitter, applied at two points.** New `engines/atlas/tokenize.py::split_identifier(name)`
  (extract the existing splitter at `store.py:177`) splits CamelCase / snake_case / digit runs → sub-words.
  Applied **at query time (A2)** in the localize adapter's query-prep (rerank-local; does *not* touch the
  shared `_fts_query`/match path), and **at index time (A3)** in `engines/atlas/index.py` build-units, behind
  a **build flag** (`KLOOP_INDEX_CAMELCASE`) so the default atlas is unchanged. A3 is **content-only** — same
  columns, same tokenizer, DDL untouched → schema-safe, but forces a re-index.
- **Live/diagnostic parity.** Close the divergence where live `retrieve()` queries `ticket.summary` only while
  the isolated eval queries richer signals — so `[proxy]` localize numbers reflect what production runs.

### 3.2 The literal-anchor tier (the real functional-recall lever)

Functional tickets usually carry a **literal anchor** that appears verbatim in code/resources — quoted UI
strings, file extensions (`JPG`/`PNG`), error-message text, resource IDs. A literal match lands the oracle
deterministically exactly where semantic pool-widening failed.

- **Anchor extraction** — a domain-pack helper (`domains/android_ivi/anchors.py` or extend
  `functional_signals.py`), run **at localize time over the query prose** (not a `Signals` field — `Signals`
  is frozen in `core/types.py`). Emits **high-value literals only**: quoted spans, ALL-CAPS extensions/enums,
  resource-id patterns, rare tokens. **Anchor SELECTION is the hard part** — `"log"` over-matches thousands of
  files, `"PNG"` is gold. Selection heuristic = quoted/bracketed spans + a rarity/idf gate (drop tokens that
  hit > N files or appear in a stoplist). This is a first-class design risk (§9).
- **Anchor search** — literal FTS queries over the atlas (needs A2/A3 CamelCase-split to match compound
  indexed names). Over the **live tree** (ripgrep) belongs in the **fix layer** (which has the worktree),
  not localize (which does not) — so the literal cascade *distributes* across both layers.

### 3.3 The cascade localize adapter (RRF union + abstain)

New `adapters/index/cascade_localize.py` (a `CodeIndex`, `retrieve(repo, query) -> list[str]`, stateful
signal-stash like `signal_query.py`), composed at the root via `split.py`. It **unions existing tiers** by
information type and fuses with **RRF** (already in-repo across `component_prior`/`fault_routing`/`atlas/retrieve`):

- **Crash tier** — reuse `fault_routing.py` (stack-frame → file, ~0.88–0.94). Near-deterministic; retrieval
  is nearly unnecessary here. **Reuse, do not rebuild.**
- **Literal tier** — §3.2 anchors → literal FTS (functional front line).
- **Semantic tier** — reuse `atlas_semantic.py` (bge-m3) + the rerank judge over CodeWiki, as the **fallback**
  for the zero-shared-literal *conceptual-gap* case.
- **RRF makes the union non-regressive** at fixed k (worst case = today's fuzzy floor). **No anchor resolved
  in any tier → first-class ABSTAIN** (route to the existing honest-refusal path), never a fabricated rank-1.

The dispatcher already labels crash|functional; the cascade *selects which anchors to extract*, not a
different pipeline — an additive union, not exclusive routing.

### 3.4 The soft gate (fix-adapter change)

New seeded mode on the planning fixer (`adapters/fix/planning.py` → a `soft`/seeded variant, or a
`SeededPlanningFixEngine`): treat `locations` as **seeds**, not a whitelist. Relax the `_plan` prompt
(`planning.py:54` "cite ONLY these") to "start from these seeds; you may also edit closely-related files";
feed **CBM neighbors** (`trace_path`/`get_code_snippet`) of the seeds so the fixer can reach the fix-site when
throw-site ≠ fix-site. This is the **bounded 80%** of the agentic idea — seeded expansion, not free
repo-walking. Grounding preserved: expansion targets are real files reachable from real seeds; **abstain
discipline extends to the expansion step** (no fabricated paths/APIs). Opt-in Candidate.

### 3.5 Benchmark re-point (stop measuring the wrong thing)

In `fixeval/scorecard.py`, `fixeval/compare.py`, `fixeval/report.py` (off-loop grader — no core edit):

- **Headline = whole-loop `resolved_rate_strict` + `fabrication_rate`, split by `bug_kind`.** The `bug_kind`
  split is net-new in the fix scorecard (it exists on the Stage-1 match side, not here). Splitting de-Goodharts
  the pooled number, which today mixes crash (~0.94) and functional (~0.10) regimes.
- **Demote `file@1`** from headline/promotion-gate to a **crash-regime diagnostic** (where symbol→file makes
  it meaningful). Update `compare.py`'s two-sided verdict to key on `resolved_rate_strict` @ non-worse
  `fabrication_rate` instead of `Δfile_recall@1` (`compare.py:25,49`).
- **Add an ungraded observability counter** `localize_hit = oracle ⊆ candidate_pool` (or `⊆ files_read` for
  the soft-gate arm) — preserves the "was the site reachable" diagnostic across both architectures without
  making it a gate.
- Fault-site accuracy continues to be graded off the **patch** (`touched_files ∩ oracle`, `scorecard.py:27`),
  which is what keeps a soft-gate fixer gradeable.

## 4. Measurement

- **[proxy] first (dev box; the 6-repo atlas has full vectors — 85,825 units / 85,825 vectors).** Isolated
  localize recall@k **with the ablation**: (i) mechanical-only (A1+A2+A3) vs (ii) +literal tier vs (iii)
  +semantic fallback — **split by regime** — so we *learn* whether the literal anchor is the lever rather than
  assuming it. Plus a **match** eval on a CamelCase-expanded 6-repo atlas to catch A3 regression cheaply
  before touching the production index.
- **[production] (you run it; GEI-only).** Re-run the 10-case functional localize read with the vector lane
  **ON**, + a **match re-validation** on the re-indexed 19-repo atlas (A3 changes the shared index).
- **Soft-gate** is gated on the existing two-sided `resolved_rate_strict` @ non-worse `fabrication_rate`
  (`compare.py`).

## 5. Reuse vs new

| Piece | Reuse | New |
|---|---|---|
| Crash tier | `fault_routing.py` | — |
| Semantic fallback + judge | `atlas_semantic.py`, `rerank_localize.py`/`atlas_judge.py` | — |
| Signal-stash pattern / composition | `signal_query.py`, `split.py` | — |
| CamelCase splitter | splitter logic in `store.py:177` | `engines/atlas/tokenize.py`; A3 build-flag path in `index.py` |
| Vector-lane wiring / fail-fast / degrade counter | `cli:1385-1388` pattern | edits in `cli`, `grade_run`, `rerank_localize` |
| Literal-anchor tier | — | `domains/android_ivi/anchors.py`; literal-FTS lane |
| Cascade adapter | RRF in `atlas/retrieve.py` | `adapters/index/cascade_localize.py` |
| Soft gate | `planning.py` `with_preamble`/`_plan`/CBM facade | seeded fix mode |
| Benchmark re-point | `scorecard.py`/`compare.py`/`report.py` | `bug_kind` split, headline swap, `localize_hit` |

## 6. Guardrails

- **Never edit `core/`** (control plane + the 7 ports + `Signals`/types). **Never alter the atlas SQLite DDL**
  (A3 is content-only). New behavior swaps at composition root / adapters / engines / off-loop grader only.
- **`Signals` is frozen** → literal anchors are derived at *localize time* from the query prose, not added as
  a `Signals` field.
- **Grounding:** every tier returns real files from a real index/graph; the soft-gate expands only along real
  seeds; abstain on no-anchor; no fabricated paths/APIs. RRF keeps the union non-regressive.
- **Governance:** the cascade arm, the CamelCase-expanded atlas, and the soft-gate fixer are **opt-in
  Candidates**, never the silent default, until a `[production]` read promotes them (localize lift **and** no
  match regression for the re-indexed atlas; `resolved_rate_strict`@fabrication for the soft gate).
- **Ops:** builds + `gloop eval/fixeval` over the multi-GB atlas run **off ext4** (`/home/vinc` directly,
  `/var/tmp`, `/dev/shm`); source `.env`; every number tagged `[proxy]`/`[production]`.
- Core-defaults-unchanged assertion (`tests/run/test_core_defaults_unchanged.py`) must still pass.

## 7. Phasing / sequencing

- **Phase 1 (now — cheap, deterministic, measurable on the existing atlas):** A1 vector wiring + fail-fast +
  degrade counter; A2 query-side CamelCase; A3 index-time CamelCase behind the build flag + re-index; the
  benchmark re-point (§3.5). Re-measure functional recall@k / `localize_hit` / `resolved_rate_strict` by regime.
- **Phase 2 (same increment, ablated):** the literal-anchor tier + cascade adapter (§3.2–3.3). Measure its
  *marginal* contribution separately.
- **Phase 3 (opt-in Candidate prototype, gated):** the soft-gate fix adapter (§3.4).
- **Deferred (until 1–3 provably plateau in numbers):** full agentic repo-navigation. Its cost/nondeterminism
  isn't justified before the corrected measurement exists, and the soft gate already banks most of its upside.

## 8. What happened to the pending plan

It **survives as Phase 1 and is subsumed, not discarded.** The vector-lane + CamelCase + re-index work is the
mandatory honest-baseline floor. But its *purpose* shifts: the **CamelCase-split is now the enabler of the
literal-anchor tier** (the real functional-recall lever), not an end in itself. "Just widen the semantic pool"
is replaced by "make the pool recall-first across grounded tiers, and stop gating fix on it."

## 9. Open risks

1. **Anchor selection quality** (§3.2) — the make-or-break for the literal tier; a bad rarity gate floods the
   pool. Mitigated by RRF non-regressiveness for recall@k, but precision at fixed k still needs a real idf/stoplist.
2. **A3 match blast radius** — index-time CamelCase changes the *shared* atlas; must re-validate match, not just
   localize. Hence the build flag + dual-atlas A/B.
3. **Soft-gate fabrication surface** — letting fix edit beyond `locations` widens where it can fabricate;
   contained by the two-sided `fabrication_rate` gate + extending abstain discipline to expansion.
4. **Underpowered production sample** — 10 functional GEI cases; treat `[production]` deltas as directional
   until the mined slice grows.

## 10. Decisions

- Option **B** (recall-fix + literal cascade + benchmark re-point; soft-gate as measured Candidate; defer
  agentic), with the **ablation refinement** (build the literal tier in the same increment but measure its
  marginal lift separately).
- Embedder-absent behavior: **fail-fast** (hard error), consistent with GroundLoop's fail-closed principle.
- Scope includes **A1+A2+A3** (index-time CamelCase + re-index), behind a build flag.
