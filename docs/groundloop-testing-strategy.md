# GroundLoop — Testing Strategy (Development Tests + Evaluation Environment)

> **Status:** Draft v2 (2026-07-04). Reconciled against the **actual GroundLoop codebase** (ports +
> adapters, the landed M0/M1 test suite). Supersedes the loop-agent draft: several things the
> loop-agent *investigation* called "absent" are already built and under test here. This is the
> canonical testing strategy for GroundLoop.
>
> **Scope / naming.** "GroundLoop" is the integrated system the charter calls *KnowledgeLoop*.
> Requirements referenced as FR-*/NFR-* and the §-cited repo-matching design live in the **sibling
> `loop-agent` repo**:
> [`../../loop-agent/docs/knowledgeloop-background-and-requirements.md`](../../loop-agent/docs/knowledgeloop-background-and-requirements.md),
> [`../../loop-agent/docs/superpowers/specs/2026-07-04-knowledgeloop-repo-matching-integration-design.md`](../../loop-agent/docs/superpowers/specs/2026-07-04-knowledgeloop-repo-matching-integration-design.md).
> GroundLoop-local companions: [`m1-index-build.md`](m1-index-build.md), [`type2-eval-setup.md`](type2-eval-setup.md).
>
> The test suite already references this strategy by section (`tests/conftest.py`,
> `tests/test_invariants.py` cite "Type-1", "§2.3", "§3.4") — keep those anchors stable.

---

## 1. Purpose & the two test surfaces

Two surfaces, two questions, two standards. The architecture makes the split natural: control flow is
a **deterministic Python control plane** (`groundloop.core.workflow.run_ticket`) and every cognitive
or external dependency sits behind a **port** (`groundloop/core/ports.py`) with a swappable adapter —
so Type-1 wires canned adapters and Type-2 wires real ones over the *same* `run_ticket`.

| Axis | **Type 1 — Development tests** | **Type 2 — Evaluation environment** |
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

## 2. Type 1 — Development tests (largely landed)

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
| engines | `tests/engines/test_{store,retrieve,build_units,repo_head,deploy,helpers,produce_smoke}.py` | atlas store/retrieve internals, produce |

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
   the owner from log signals alone and beats the `1/N` guess (fleet-integrity backstop, §3.5).

### 2.3 Remaining Type-1 gaps
- **(a)** Un-skip invariant #3 (full `@base = fix^` scrub) once the real `RepoEstate` lands.
- **(b)** **Embedder-match guard (NEW)** — the hermetic `atlas_fixture` is FTS5-only (no embedder), so
  the bge-m3 pin (§4) isn't exercised hermetically. When the semantic-rerank arm lands, add an
  invariant that the vector path **refuses a query embedder ≠ the index embedder** (silent-corruption
  guard; today enforced only by the `KLOOP_EMBED_MODEL` reuse contract, not a test).
- **(c)** Extend the hermetic suite + keep invariants green as new stages land (mining, real fix
  engine, semantic rerank).

### 2.4 Cadence
Every change; hermetic/no-network by default. The two `tests/e2e/` cases
(`test_index_build_live.py`, `test_produce_live.py`) are **gated** on
`KLOOP_EMBED_API_KEY + KLOOP_CBM_READY + KLOOP_PRODUCE_READY` and run live on **DeepSeek** (the only
live model here — charter §9 / NFR-2).

---

## 3. Type 2 — Evaluation environment (mostly pending)

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
DeepSeek (default workhorse; only live model here) · Qwen 3.6 (portability target, absent → gated) ·
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
| `AtlasIndex` (FTS5) + `gloop index` build | **DONE** | `adapters/index/atlas.py`; M1 landed |
| conftest + micro-fleet + invariants | **DONE** | `tests/conftest.py`, `test_invariants.py` |
| Real `RepoEstate` (`@base = fix^`, scrub) | **PENDING** | un-skips invariant #3 |
| Mining (real tickets/logs/oracle) | **PENDING** | `gloop mine` |
| Semantic vector rerank arm | **SCAFFOLDED** | `GatewayEmbedder` migrated; hermetic uses FTS5 |
| Eval-env: arms + recall@k/MRR/cost + refusal + scorecard | **PENDING** | the core Type-2 build |
| Expanded confusable fleet + fleet CodeWikis | **PENDING** | grows `1/N` denominator |

---

## 6. Roadmap alignment (which tests come online when)

- **M0 — walking skeleton** *(done)* — ports, mock adapters, hermetic vertical slice, anti-leak
  invariants.
- **M1 — index build** *(done)* — real `AtlasIndex`, `gloop index/produce/doctor`, gated live build test.
- **Next — real `RepoEstate`** — materialize `@base = fix^`; **un-skip invariant #3**.
- **Next — mining** — `gloop mine`: real GitHub-issue tickets + logs + hidden `owning_repo`.
- **Next — semantic rerank arm** — turn on the `GatewayEmbedder` path (bge-m3), with the §2.3(b) guard.
- **Then — Eval env online** — multi-ticket arms harness, `recall@k`/MRR/cost/confusion,
  grounded-refusal, JSON scorecard + summary; extend to Stage-2/3/4 downstream metrics.

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
- No full 130-repo fleet — a curated confusable pilot proves the pipeline first.

---

## 9. Open questions (for review)

1. **Selective metric + abstention mechanism** (§3.4) — risk–coverage AUC vs accuracy@fixed-coverage;
   abstain-by-threshold vs abstain-by-margin.
2. **Where the eval-env module lives** — extend `groundloop/grade/` or a new `groundloop/eval/`
   package for the multi-ticket arms harness + scorecard.
3. **Embedding-version provenance** (§3.5) — record `KLOOP_EMBED_MODEL` + vector dim in `atlas.db` so
   `recall@k` is comparable across runs.
