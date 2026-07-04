# GroundLoop — Testing Strategy (Development Tests + Evaluation Environment)

> **Status:** Draft v2 (2026-07-04). Reconciled against the **actual GroundLoop codebase** (ports +
> adapters, the landed M0/M1 test suite). Supersedes the loop-agent draft: several things the
> loop-agent *investigation* called "absent" are already built and under test here. This is the
> canonical testing strategy for GroundLoop.
>
> **Scope / naming.** "GroundLoop" is the integrated system the charter calls *KnowledgeLoop*.
> Requirements referenced as FR-*/NFR-* live in [`charter.md`](charter.md); the §-cited repo-matching
> design (spec M1–M5, matcher = spec M3) is summarized in [`roadmap.md`](roadmap.md); the original
> design lives in the loop-agent spec (cited below). **Original spec provenance** is the sibling
> `loop-agent` repo —
> [background & requirements](../../loop-agent/docs/knowledgeloop-background-and-requirements.md),
> [repo-matching integration design](../../loop-agent/docs/superpowers/specs/2026-07-04-knowledgeloop-repo-matching-integration-design.md).
> GroundLoop-local companions: [`m1-index-build.md`](m1-index-build.md), [`type2-eval-setup.md`](type2-eval-setup.md).
>
> The test suite already references this strategy by section (`tests/conftest.py`,
> `tests/test_invariants.py` cite "Type-1", "§2.3", "§3.4") — keep those anchors stable.

---

## 1. Purpose & the two test surfaces

Two surfaces, two questions, two standards — the two parts of the test design: **Type 1 = "Test 1"**
(system development testing) and **Type 2 = "Test 2"** (overall evaluation). The architecture makes the
split natural: control flow is
a **deterministic Python control plane** (`groundloop.core.workflow.run_ticket`) and every cognitive
or external dependency sits behind a **port** (`groundloop/core/ports.py`) with a swappable adapter —
so Type-1 wires canned adapters and Type-2 wires real ones over the *same* `run_ticket`.

| Axis | **Type 1 (Test 1) — Development tests** | **Type 2 (Test 2) — Evaluation environment** |
|---|---|---|
| Question | *Is the code correct?* | *Is the system effective?* |
| Verdict | Pass / fail | Graded scorecard |
| Model | `CannedModel` (canned) | Real (DeepSeek default; Qwen/Claude gated) |
| Index | `TokenIndex` / prebuilt FTS5 `atlas_fixture` | Real `AtlasIndex` over `gloop index` build |
| Estate | `MockEstate` (isolated work-tree) | Real `RepoEstate` (`@base = fix^`, scrubbed) — *pending* |
| Determinism | Deterministic | Stochastic (models); deterministic scoring |
| Network | **None** (hermetic) | Model + embed-gateway calls |
| Cadence | Every change / CI | On demand / per-model / per-arm |
| Status | **Largely landed** (§2) | **Mostly pending** (§3) |
| Authority | NFR-8 | FR-7 / charter §6 / spec §9 |

---

## 2. Type 1 (Test 1) — Development tests (largely landed)

Hermetic, deterministic, no network, no real LLM — driven by `CannedModel`
(`groundloop/adapters/mock/model.py`) over a tiny micro-fleet. Mandated by NFR-8: *"hermetic,
no-network test suite; live tests gated on credentials."* The shared substrate lives in
`tests/conftest.py` (`harness`, `atlas_harness`, `case`, `atlas_db`, `catalog_path` fixtures) +
`tests/fixtures/atlas_fixture.py` (a 4-repo FTS5 `atlas.db`, no CBM/embedder) +
`tests/fixtures/android_ivi/` (`catalog.json`, `index.json`, `gpuimage-352/{ticket.json, logs/, _oracle/oracle.json}`).

### 2.1 Existing coverage (grounded inventory)
| Stage / concern | Test | Under test |
|---|---|---|
| **Full loop (hermetic)** | `test_e2e_vertical_slice.py` | `run_ticket` → match→materialize→localize→fix→submit→bind, then offline `grade` |
| A — Intake | `test_mock_jira.py` | `MockJira.fetch/post_comment/transition` |
| A — Extract (FR-2) | `test_signal_extractor.py` | `AndroidSignalExtractor` → packages/classes/methods/symbols/`.so`/errors |
| B — Match | `test_atlas_index.py`, `test_index.py` | `AtlasIndex` (FTS5 membership `rank_repos`) + `TokenIndex` |
| B — Estate/fleet | `test_fleet_estate.py`, `test_atlas_fixture.py` | `MockEstate.catalog/materialize`, fixture builder |
| C — Fix | `test_fix.py` | `CannedFixEngine.propose` → `Patch` |
| D — Bind | `test_mock_gerrit.py` | `MockGerrit.submit` (Change-Id `I`+40hex, JIRA key in subject, content-hashed → deterministic) + `bind` (ledger + `Resolved` transition) |
| grade | `test_grader.py` | `grade(record, oracle)` → `Scores` |
| infra | `test_ports.py`, `test_types.py`, `test_workflow.py`, `test_cli.py`, `test_settings.py` | ports/protocols, dataclasses, `gloop` CLI, `Settings` (embed-model pin) |
| engines | `tests/engines/test_{store_smoke,retrieve,build_units,repo_head,deploy,helpers,produce_smoke}.py` | atlas store/retrieve internals, produce |

### 2.2 Anti-leak invariants — green regression guards (`test_invariants.py`)
These encode constraints that, if violated, silently corrupt the eval. **They are green today** — a
failure means a real leak was reintroduced. Numbering matches the code:

1. **Ticket never names the owning repo** — `component`, summary, description, logs, comments all
   scanned; owner absent (`test_ticket_does_not_name_owning_repo`).
2. **`owning_repo` only in the oracle** — absent from `ticket.json`/`logs/`, present in `oracle.json`.
3. **`@base` isolation** — *weak form green* (`materialize` yields an isolated throwaway work-tree);
   the **full form** (`@base = fix^` with the fix + all later history scrubbed, fix-added tests
   excluded) is **`@pytest.mark.skip` pending the real `RepoEstate`** — a Type-2 substrate item.
4. **Loop never reads the oracle or bind-output** — enforced by a `Path.read_text` spy over a full
   run (`_oracle/*`, `oracle.json`, `binding.jsonl`, `changes.jsonl`, `ledger.jsonl`).
5. **Signals don't encode the answer** — the matcher's input tokens exclude the owner, and the
   catalog is a real N-way choice (≥3 candidates) with the owner as one of them (FR-3).
6. **Deterministic control flow** — same inputs → identical event sequence, choice, ranked order,
   and `Change-Id`.
   *Bridge to Type-2:* `test_atlas_matcher_honors_invariants` asserts the **real** `AtlasIndex` picks
   the owner from log signals alone and beats the `1/N` guess (fleet-integrity backstop, §3.4).

### 2.3 Remaining Type-1 gaps
- **(a)** Un-skip invariant #3 (full `@base = fix^` scrub) once the real `RepoEstate` lands.
- **(b)** **Embedder-match guard (NEW)** — the hermetic `atlas_fixture` is FTS5-only (no embedder), so
  the bge-m3 pin (§4) isn't exercised hermetically. When the semantic-rerank arm lands, add an
  invariant that the vector path **refuses a query embedder ≠ the index embedder** (silent-corruption
  guard; today enforced only by the `KLOOP_EMBED_MODEL` reuse contract, not a test).
- **(c)** Extend the hermetic suite + keep invariants green as new stages land (mining, real fix
  engine, semantic rerank).

### 2.4 Cadence
Every change; hermetic/no-network by default. The two `tests/e2e/` cases run live on **DeepSeek** (the
only live model here — charter §9 / NFR-2): `test_index_build_live.py` is **gated** on
`KLOOP_EMBED_API_KEY + KLOOP_CBM_READY + KLOOP_PRODUCE_READY`, while `test_produce_live.py` is **gated**
on `KLOOP_PRODUCE_READY` (+ `KLOOP_PRODUCE_TEST_REPO` for the repo path).

---

## 3. Type 2 (Test 2) — Evaluation environment (mostly pending)

Measure effectiveness against grounded-but-hidden ground truth and **report** it. The spec §9 harness,
extended downstream for full end-to-end.

### 3.1 What exists today
- **Scoring seed:** `grade()` computes **single-ticket** `repo_recall@1`, `repo_rank`,
  `localization_recall`, `bound` (`groundloop/grade/grader.py` → `Scores`).
- **Live substrate:** `gloop index` builds a real `atlas.db` (wiki doc units + CBM symbol units +
  bge-m3 vectors); `gloop doctor` checks readiness (see [`type2-eval-setup.md`](type2-eval-setup.md)).

Not yet built (this is the Type-2 work): the **multi-ticket harness**, the **arms**, `recall@k` for
`k>1`, **MRR**, **cost**, **per-repo confusion**, **grounded-refusal**, and the **scorecard**.

### 3.2 Metrics per stage (target)
| Stage | Metrics | Today |
|---|---|---|
| 1 — Match (PRIMARY) | `repo_recall@1/@k`, `repo_mrr`, per-repo confusion, cost/ticket-matched, triage-effort proxy (rank) | `recall@1` + `rank` only |
| 2 — Localize | file-`recall@k` | `localization_recall` (single) |
| 3 — Fix | resolved rate, $/solved (apply-check + grounded-use) | — |
| 4 — Bind | traceability pass/fail | `bound` |

### 3.3 Arms (A/B)
- **Strategy arms:** membership-only (`TokenIndex`/FTS5 `AtlasIndex`) → **+semantic rerank**
  (`GatewayEmbedder`, scaffolded) → **+LLM-judge**. Membership-only is the **naive baseline** the
  semantic matcher must beat.
- **Signal arms:** text-only vs **+logs** — quantifies how much the logs help (NFR-2 cost).
- **Fix-stage arms (downstream / BFL provenance — forward-looking).** From the loop-agent fix-loop
  track (BFL-M0..M9; [`downstream-fix-loop.md`](downstream-fix-loop.md), original roadmap
  [`../../loop-agent/docs/roadmap.md`](../../loop-agent/docs/roadmap.md)): `single_shot` is the
  **default runner arm**, with an agentic `tool_loop` (investigate-then-submit) as a non-default
  measured arm; and a **grep retriever ran ~25% cheaper** than no-retrieval on real-sized repos with
  **no localization loss** (a cost lever, not an accuracy one). Caveat carried over verbatim: on a
  *synthetic* seed the benchmark **rewards confident guessing and penalizes honest grounded refusal**,
  so the `tool_loop` arm's true value is *unprovable* until a genuinely-buggy benchmark exists — the
  same "grounding over narrative" concern §3.4 encodes. GroundLoop's fix stage is a `CannedFixEngine`
  stub today (Stage-3), so these arms are forward-looking here.
- Per-difficulty-bucket slicing is **out of scope** (YAGNI, §8) — the arms carry the ablation signal.

### 3.4 Grounded-refusal / confidence — *not just forced top-k*
Charter §6: *"a metric that rewards guessing over grounded refusal is broken."* So:
- the matcher emits a per-repo `RepoScore.score` + an **abstain** decision (top-score or
  top-vs-runner-up margin below threshold);
- the scorecard reports both the **`recall@k`** view *and* a **selective / risk–coverage** view
  (**coverage** vs **accuracy-at-coverage**), so correct abstention on ungrounded cases is not scored
  as a guess;
- **fleet-integrity backstop:** the fleet is diverse enough that `1/N` guessing scores far below a real
  match — already asserted for the current fixture by the §2.2 bridge invariant.

*(Open pick — §9: risk–coverage AUC vs accuracy@fixed-coverage, and the abstention mechanism.)*

### 3.5 Integrity & provenance
Report only on **non-leaking** entries (enforced by `test_invariants.py`); owning repo hidden. Record
per run: repo SHAs, atlas indexed HEADs, and the **embedding model version** — `KLOOP_EMBED_MODEL`
(=`bge-m3`) is a **pinned reuse contract** (§4); a change silently invalidates cross-run `recall@k`.

### 3.6 Model matrix
DeepSeek (default workhorse; only live model here) · Qwen3 (portability target, absent → gated) ·
Claude (reference, needs key → gated). Cost first-class throughout (`$/ticket-matched`, `$/solved`).

### 3.7 Scorecard format
**JSON scorecard + human summary**, structure = **per-arm × per-repo × per-stage** + cost +
provenance. Metric computation reuses knowledgeLoop's `eval/offline` `@k`/`mrr` + per-repo
aggregation (to be surfaced as a `groundloop` eval module extending `grade()`).

```jsonc
{
  "run": { "id, timestamp, model, fleet_sha_set, embedding_model": "…" },
  "arms": {
    "membership+logs": {
      "stage1": { "recall@1": .., "recall@k": {..}, "mrr": .., "cost_per_match": ..,
                  "coverage": .., "accuracy_at_coverage": {..}, "per_repo": { "<repo>": {..} } },
      "stage2": { "file_recall@k": {..} },
      "stage3": { "resolved_rate": .., "usd_per_solved": .. },
      "stage4": { "traceability_pass": true }
    }
    // …one block per strategy×signal arm…
  },
  "summary_md": "human-readable rollup"
}
```

### 3.8 Evaluation methodology (why these metrics)

Distilled from the knowledgeLoop repo-atlas evaluation lap-log
([`../../knowledgeLoop/docs/repo-atlas-evaluation.md`](../../knowledgeLoop/docs/repo-atlas-evaluation.md)),
which ran the same "grounding over narrative" discipline against a real `bge-m3` atlas and learned —
the hard way — where a retrieval metric can be trusted. Its lessons shape the choices above.

**The evaluation pyramid — measure the cheap deterministic layers directly; reserve the expensive
agentic test for *outcome validation*, not tuning.**

```
  4. Agentic A/B (outcome)         expensive, noisy   → validate, don't tune
  3. Context-injection             (dozens of runs)
  2. Grounding   precision/recall  cheap, deterministic
  1. Retrieval   Success@k / MRR   (ms/case, no agent) → tune here
```

Layers 1–2 are agent-free and run in seconds, so a strategy/signal arm can be tuned offline with real
statistical power (N in the hundreds is feasible). Layer 4 is the only thing that measures the actual
goal, but is statistically weak at the N we can afford — it *validates* that offline gains translate,
it is not the day-to-day instrument.

- **Any-of, not all-of.** Relevance is often *"find me any acceptable target"*: several files can be
  equally valid, and surfacing any one is success. So the primary retrieval metrics are **`Success@k`**
  (any acceptable gold in the top-k) + **`MRR`** (rank of the first), and **`Recall@k` is demoted to a
  coverage stat** (it understates by design when a case has several valid alternatives). Each case
  carries a **set** of acceptable golds; curation keeps that set *canonical* (anti-gaming) and the
  scorecard reports **median golds/case** so breadth is visible. *In GroundLoop this bites at Stage-2
  localization* (`file_recall@k`, §3.2) — several files may legitimately own a fix. Stage-1 is
  different: the **owning repo is a single hidden oracle**, so `repo_recall@1` / `repo_mrr` are
  exact-match, not any-of.
- **Grounding is scored against source reality, not the store.** The "real" symbol set is
  **grep-verified from repo source**, never sampled from the index — so a real symbol the store fails
  to confirm counts *against* it. This surfaces under-indexing as a *product* risk (the tool telling an
  agent a real API "doesn't exist"), not a metric artifact — the discipline behind the grounded-use /
  grounded-refusal checks (§3.4).
- **Mechanism-resolved evaluation.** A binary success rate over small N is uninterpretable, so the
  agentic layer traces the **causal chain per task** — *surfaced the right prior art? → the agent used
  it? → did the outcome beat baseline?* — and classifies each task (`causal-win` / `surfaced-ignored` /
  `retrieval-miss` / `regression` / `no-effect`). Any non-win is then *attributed* to an adoption gap
  vs a retrieval gap vs no-headroom — far more informative than a noisy aggregate rate.
- **The N≈10 / ±20pp noise floor.** At the N an agentic A/B can afford, the lap-log measured two
  *behaviourally identical* conditions scoring **20% vs 40%** — pinning the **N=10 noise floor at
  ≈ ±20pp**. Treat any agentic arm difference below that as noise. This is exactly why the primary
  effort sits on the deterministic layers, and why GroundLoop's Type-2 arms (§3.3) and the
  grounded-refusal view (§3.4) are the load-bearing signal, with agentic outcomes used only to validate.

---

## 4. BGE-M3 / embedding pin (reuse contract)

The atlas index consumes **bge-m3** as an external **OpenAI-compatible `/v1/embeddings`** endpoint
(gateway / Ollama / sentence-transformers server), selected by env — the code never hosts it. The pin:
`KLOOP_EMBED_MODEL=bge-m3` (default in `groundloop/config/settings.py`), and **the query-time embedder
MUST equal the index-time embedder** or cosine ranking is silently corrupted
([`m1-index-build.md`](m1-index-build.md) "Reuse contract"; [`type2-eval-setup.md`](type2-eval-setup.md)).

- **Type-1:** stays embedder-free (FTS5 `atlas_fixture`); add the §2.3(b) mismatch guard when the
  vector arm lands.
- **Type-2:** the real `atlas.db` build is gated on a live bge-m3 host — health-check with the curl
  gate in `type2-eval-setup.md` before `gloop index`. Changing the embed model forces a full re-index.

---

## 5. Substrate readiness (reconciled)

| Dependency | Status | Notes |
|---|---|---|
| Ports + deterministic `run_ticket` | **DONE** | `core/ports.py`, `core/workflow.py` |
| Signal extractor (FR-2) | **DONE** | `domains/android_ivi/signal_extractor.py` |
| Mock JIRA / Mock Gerrit (Stage A/D) | **DONE** | `adapters/mock/{jira,gerrit}.py` |
| Catalog + oracle(`owning_repo`) + logs fixtures | **DONE** | `tests/fixtures/android_ivi/` |
| `AtlasIndex` (FTS5) + `gloop index` build | **DONE** | `adapters/index/atlas.py`; GL-M1 landed |
| conftest + micro-fleet + invariants | **DONE** | `tests/conftest.py`, `test_invariants.py` |
| Real `RepoEstate` (`@base = fix^`, scrub) | **PENDING** | un-skips invariant #3 |
| Mining (real tickets/logs/oracle) | **PENDING** | `gloop mine` *(aspirational — not built)* |
| Semantic vector rerank arm | **SCAFFOLDED** | `GatewayEmbedder` migrated; hermetic uses FTS5 |
| Eval-env: arms + recall@k/MRR/cost + refusal + scorecard | **PENDING** | the core Type-2 build |
| Expanded confusable fleet + fleet CodeWikis | **PENDING** | grows `1/N` denominator |

---

## 6. Roadmap alignment (which tests come online when)

- **GL-M0 — walking skeleton** *(done)* — ports, mock adapters, hermetic vertical slice, anti-leak
  invariants.
- **GL-M1 — index build** *(done)* — real `AtlasIndex`, `gloop index/produce/doctor`, gated live build test.
- **Next — real `RepoEstate`** — materialize `@base = fix^`; **un-skip invariant #3**.
- **Next — mining** — `gloop mine` *(aspirational — not built yet)*: real GitHub-issue tickets + logs +
  hidden `owning_repo`.
- **Next — semantic rerank arm** — turn on the `GatewayEmbedder` path (bge-m3), with the §2.3(b) guard.
- **Then — Eval env online** — multi-ticket arms harness, `recall@k`/MRR/cost/confusion,
  grounded-refusal, JSON scorecard + summary; extend to Stage-2/3/4 downstream metrics (§3.8 pyramid:
  tune on the deterministic layers, validate on the agentic).

---

## 7. Reuse map

**Type 1 reuses:** `tests/conftest.py` fixtures, `tests/fixtures/atlas_fixture.py`, `CannedModel`,
`MockEstate`/`MockJira`/`MockGerrit`, `run_ticket`.
**Type 2 reuses:** `AtlasIndex` + atlas `Store`/`retrieve`, `GatewayEmbedder`, the `grade()` seed,
knowledgeLoop `@k`/`mrr` metrics, the produce/CodeWiki engine, `gloop index`/`doctor`.

---

## 8. Non-goals / YAGNI boundary

- **No per-difficulty-bucket slicing** — the ablation **arms** carry the signal (decision, this review).
- No Tier-3 build/test-execution grading — fix grading stays grounding-based.
- No ANN yet — FTS5 first-stage filter at pilot scale.
- No real JIRA/Gerrit — file-and-index fixtures; `MockGerrit`'s simulated `Change-Id` + ledger is the
  bind surface.
- No full 130+ -repo fleet — a curated confusable pilot proves the pipeline first (fleet layers:
  target 130+ AAOS repos → charter pilot ~11 OSS → 3 built corpora at pinned SHAs → 4-repo hermetic
  fixture).

---

## 9. Open questions (for review)

1. **Selective metric + abstention mechanism** (§3.4) — risk–coverage AUC vs accuracy@fixed-coverage;
   abstain-by-threshold vs abstain-by-margin.
2. **Where the eval-env module lives** — extend `groundloop/grade/` or a new `groundloop/eval/`
   package for the multi-ticket arms harness + scorecard.
3. **Embedding-version provenance** (§3.5) — record `KLOOP_EMBED_MODEL` + vector dim in `atlas.db` so
   `recall@k` is comparable across runs.
