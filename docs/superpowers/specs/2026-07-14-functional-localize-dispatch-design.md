# No-crash localize via semantic-retrieve dispatch (Approach A, staged)

**Date:** 2026-07-14 · **Status:** design approved, ready for plan · **Track:** Stage-1 localize (functional / no-crash)

## 1. Context & grounded baseline

A prior RCA claimed functional-bug localize fails because an "existing hybrid retrieval
pipeline (keyword + bge-m3 + Qwen rerank), gated on `_embedder`/`_model` and activated by a
`prime()` call" was never wired into `run_ticket`. **This was verified against the code and is
fabricated:** `AtlasIndex.__init__` takes only `db_path` (no embedder), `atlas.py` is 37 lines
(the cited `atlas.py:56-62` does not exist), `grep "prime("` over all code+docs+tests returns
zero hits, and no keyword+vector+rerank retrieve pipeline exists anywhere. The RCA's grain of
truth is a single accurate log line (`results-log.md:82`): `run_ticket` localize is plain FTS5
over symbols; richer retrieval differs only in the *query* and *which index object* is passed.

**The real, measured problem** (`results-log.md:82`, `[production]`, GEI n=10, isolated on the
oracle repo): functional localize is **`file@5 = 7/10` but `file@1 = 1/10`**. The correct file is
usually *already in the top-5 pool*; it almost never lands at rank-1. The cause is structural:
`run_ticket` localizes with `query = ticket.summary` (natural-language symptom prose) against an
FTS5 index over **symbol names** — for a no-crash ticket there is no class/method/`.so`/stack
token in the prose to match a symbol, so the right file ranks poorly.

**Goal.** Lift functional (no-crash) *isolated* localize `file@1` (and `file@5`) by routing
prose-marked tickets to bge-m3 semantic retrieval, while leaving the (working) crash FTS5 path
byte-identical. Composition-root only.

**Non-goals / out of scope (staged for later).** (B) signal-tokens query enrichment and
(C) hybrid RRF + LLM rerank are deferred; they are the staged follow-ons if the proxy A/B shows
semantic-alone leaves `file@1` short (see §7). Match-stage behavior is untouched. No new
honest-refusal negatives.

## 2. Hard constraints (must hold)

- **`groundloop/core/` is FROZEN.** `run_ticket` builds the localize query as `ticket.summary`
  and calls `index.retrieve(chosen, ticket.summary)` (`core/workflow.py:33`). We cannot change
  the query construction or the port signature. `retrieve(repo, query)` is **signal-blind**.
- **The atlas SQLite schema is FROZEN** (`engines/atlas/store.py`). No new columns / re-index.
- **Localize-query-pollution confound** (`[[kb-reverdict]]`, `results-log.md`): naively enriching
  the localize query has been *measured* to hurt `file@1` (Δ−0.10 to −0.14). This design does
  **not** change the query (query stays `ticket.summary`); it changes the *retriever* for
  prose-marked tickets. This sidesteps the confound by construction.
- **Embedder dependency.** Semantic retrieve needs the gateway bge-m3 embedder at query time
  (`KLOOP_EMBED_BASE_URL`). Production already pins bge-m3 by the reuse contract; hermetic
  (Type-1) tests must not require it (use a fake embedder / doubles).

## 3. Architecture

Four components, all composition-root or eval-harness; **zero `core/` or schema edits.**

### Component 1 — `LocalizeDispatchIndex`  *(new: `groundloop/adapters/index/localize_dispatch.py`)*

Mirrors the existing `DispatchIndex` (`adapters/index/functional_text.py:50`) but dispatches the
*retrieve* (localize) side rather than `rank_repos`.

```
class LocalizeDispatchIndex:
    def __init__(self, match, crash_localize, functional_localize):
        self._match = match; self._crash = crash_localize
        self._functional = functional_localize; self._last_signals = None

    def rank_repos(self, signals, catalog):
        self._last_signals = signals            # stash for the retrieve that run_ticket calls next
        return self._match.rank_repos(signals, catalog)

    def retrieve(self, repo, query):
        sig = self._last_signals
        if sig is not None and is_functional(sig):
            return self._functional.retrieve(repo, query)
        return self._crash.retrieve(repo, query)   # crash path == today, byte-identical

    def note_signals(self, signals):            # explicit seed for out-of-loop callers (grade-run)
        self._last_signals = signals
```

- **Discriminator.** Factor the existing `DispatchIndex._is_functional`
  (`signals.symbols and signals.symbols[0].startswith(PROSE_MARK)`) into **one shared free
  function** `is_functional(signals)` (co-located with `DispatchIndex`), used by both dispatchers
  so they cannot drift. `PROSE_MARK` comes from `domains/android_ivi/functional_signals`.
- **Safe fallback.** No signals stashed/seeded → crash FTS5 path (never worse than today).
- **`note_signals`** is an honest, documented seam for callers that invoke `retrieve` without a
  preceding `rank_repos` (the grade-run isolated diagnostic). It is **not** the RCA's phantom
  `prime()`: different name, different purpose, real code, ~1 line.

**Why the stateful stash is sound (not a hack).** `run/batch.py:17` runs `run_ticket`
**sequentially** (`for case in cases:`) on one shared `index` instance, and `run_ticket` calls
`rank_repos` then `retrieve` back-to-back per ticket — so the stash cannot race across tickets.
This codebase already blesses the identical pattern (`extractor_rec.last_signals`,
`run/batch.py:22`). Regression safety is structural: crash tickets take the exact FTS5 path they
take today; only prose-marked tickets change — precisely the `file@1 = 1/10` population.

### Component 2 — composition-root wiring  *(`cli/__init__.py`, the `run` path ~1360–1442)*

- Extend `--localize` choices: `atlas | semantic | dispatch`.
- `--localize dispatch` builds
  `LocalizeDispatchIndex(match=<the match index>, crash_localize=AtlasIndex(db),
  functional_localize=SemanticAtlasIndex(db, emb))`.
- **No embedder → degrade to atlas with a warn** (reuse the pattern already at
  `cli/__init__.py:1431–1435`); record the localize that *actually* ran in the manifest. A
  fail-safe default never fails closed.
- The run **manifest already records the localize arm** (`run/manifest.py:33`, written at
  `cli/__init__.py:1489`, `localize=localize_req`). Adding `dispatch` needs no manifest schema
  change — `localize="dispatch"` flows through.
- **Governance:** Candidate — reachable via the flag, **not** a default, until a `[proxy]` A/B
  shows lift (the "reachable ≠ default" rule from the labs-arms work, `[[provisional-core-loop-closure]]`).

### Component 3 — grade-run isolated-diagnostic faithfulness  *(`run/grade_run.py:116–143`)*

Today `grade_run` re-runs the isolated localize with a **hardcoded `AtlasIndex(index_db)`**
(`grade_run.py:132`) and calls `idx.retrieve(RepoRef(owner), query)` with **no preceding
`rank_repos`** — so a `dispatch` run would be measured on the *wrong* retriever. Changes:

- Read the run's `localize` arm from `manifest.json` (write the manifest path / arm into the
  grade pass; `grade_run` already receives `runs_dir`). Reconstruct the matching localize index:
  `atlas → AtlasIndex`; `semantic → SemanticAtlasIndex`; `dispatch → LocalizeDispatchIndex`
  (needs the gateway embedder — the isolated diagnostic is already `[production]`/live).
- For `dispatch`/`semantic`: **reconstruct a minimal Signals from the persisted `doc.signals`
  dict** (`RunDoc.signals: dict`, `record.py:46`; retains `symbols`) and call
  `idx.note_signals(sig)` before `idx.retrieve(RepoRef(owner), query)`. `query` stays
  `ticket.summary` (`grade_run.py:122`) — faithful to the frozen core.
- Everything else is free: `by_bug_kind` split (`grade_run.py:139–141`) and as-run vs isolated
  (`_localize_as_run` / `_localize_isolated`) already exist → functional `file@1`/`file@5` is
  reported per kind with no new metric code.
- As-run localize (`record.locations`) already reflects the dispatch (it ran inside `run_ticket`).

### Component 4 — measurement substrate  *(existing tooling; no new generator)*

`groundloop/synth/functional.py:build_functional_dataset` already emits **no-crash functional
cases** from mined positives — prose-only UI-text and prose+non-crash-log audio/CarPlay tickets —
each carrying `expected_files` and `bug_kind="functional"`, with code tells kept *out* of the
ticket prose (spec §10 invariant). This is a legitimate dev-box (`[proxy]`) functional-localize
substrate at n≫10 (the GEI n=10 is `[production]`-only).

## 4. Data flow

Live loop (`--localize dispatch`): `run_ticket` → `extractor.extract` → `index.rank_repos(signals)`
(stash) → `materialize` → `index.retrieve(chosen, ticket.summary)` → dispatch on stashed signals:
prose-marked → `SemanticAtlasIndex.retrieve` (embed summary prose → bge-m3 cosine over symbol
units in the chosen repo); else → `AtlasIndex.retrieve` (FTS5). Grade pass (`grade-run`):
per case, reconstruct localize index from the manifest, `note_signals(doc.signals)`, re-run
`retrieve` on the **oracle** repo → isolated `file@k`, split by `bug_kind`.

## 5. Testing

- **Type-1 (hermetic, runs every change):**
  - `LocalizeDispatchIndex` unit tests: prose-marked signals → functional retriever; non-prose →
    crash retriever; no signals → crash fallback; `note_signals` seeds correctly. Use canned
    localize doubles (a fake crash retriever + fake functional retriever returning marker files)
    and a fake match index — **no network, no embedder.**
  - Shared-discriminator test: `is_functional` agrees for `DispatchIndex` and
    `LocalizeDispatchIndex` (one source of truth; guard against drift).
  - Anti-leak invariants (`tests/test_invariants.py`): the dispatch reads no oracle; `--localize`
    default unchanged (still `atlas` in Core, `semantic` only under labs).
- **Type-2 (gated live, `tests/e2e/`):** a `skipif`-gated e2e that builds a tiny synth functional
  dataset, runs `gloop run --localize dispatch` + `gloop grade-run --index-db` against a real
  atlas + gateway embedder, and asserts the dispatch routes functional cases to the semantic path
  (mechanism check, not a score threshold).
- Ruff clean (line 110); full suite green before commit.

## 6. A/B protocol (proxy → production)

1. Build a synth functional dataset (`synth/functional.py`) from mined positives on the dev box.
2. `gloop run --localize atlas`  vs  `gloop run --localize dispatch` over the same dataset.
3. `gloop grade-run --index-db <atlas>` on each → compare **functional** `by_bug_kind` isolated
   `file@1`/`file@5`. Baseline `atlas` should reproduce the `1/10 @1` shape; treatment `dispatch`
   is the read. Crash `by_bug_kind` must be unchanged (regression guard).
4. Tag results `[proxy]` in `results-log.md`. Production confirmation on the GEI functional set
   (`[production]`), same instrument as the original 7/10.

## 7. Risks & staging trigger

- **Vector-alone has no rerank.** `SemanticAtlasIndex.retrieve` is bge-m3 cosine only, so it may
  lift `file@5` (recall) more than `file@1` (ranking). **Trigger:** if the proxy A/B shows
  functional `file@5` up but `file@1` still short, stage in (B) signal-tokens query and/or
  (C) hybrid RRF + LLM rerank — both compose into the same dispatch wrapper without re-architecting.
- **Proxy↔production gap.** Synth prose may be easier/harder than real GEI tickets; the proxy is a
  mechanism + direction check, production owns efficacy (standard split).
- **Embedder availability.** `dispatch` degrades to `atlas` (warn) without an embedder, so it is
  safe as a Candidate flag; it must not become a silent global default without a `[production]` read.

## 8. Governance & docs

- Register the capability in `docs/capabilities.md` as a **Candidate** (reachable, not default).
- Add the `dispatch` localize option to the `docs/workflows.md` per-stage feature map.
- Log the A/B in `docs/results-log.md` with `[proxy]`/`[production]` tags.

## 9. Deliverables checklist

- [ ] `adapters/index/localize_dispatch.py` (`LocalizeDispatchIndex`) + shared `is_functional`.
- [ ] `--localize dispatch` wiring + embedder-degrade in `cli/__init__.py` run path.
- [ ] `grade_run` isolated diagnostic: manifest-driven localize index + `note_signals` seed.
- [ ] Type-1 tests (dispatch routing, fallback, seed, discriminator parity, invariants).
- [ ] Gated Type-2 e2e (mechanism check on a synth functional dataset).
- [ ] Docs: `capabilities.md` (Candidate), `workflows.md` (feature map), `results-log.md` (A/B).
