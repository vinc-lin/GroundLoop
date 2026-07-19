# GroundLoop — Evaluation (Type-2 effectiveness + the Type-1 test surface)

> **Status:** Design v1 (2026-07-05). This is the **canonical, complete definition of the GroundLoop
> evaluation** — the Stage-1 ticket→repo matching effectiveness benchmark (the "Type-2 / Test 2"
> evaluation environment) **plus the Type-1 hermetic development-test surface it is paired with (§14)**.
> It is the single source of truth for *what the evaluation measures, over what data, with what metrics,
> how the harness is built*, and *how the two test surfaces relate*. The two surfaces map onto the
> dev-box/production split — see [`environments.md`](environments.md) (the canonical dev↔production
> statement and the mandated `[proxy]`/`[production]` result-tagging convention). The live-substrate
> **build runbook** (env, gateway gates, `gloop` commands) lives in
> [`build-setup.md`](build-setup.md); requirements (FR-*/NFR-*) live in
> [`charter.md`](charter.md); the ports & control plane in [`architecture.md`](architecture.md).
>
> **Terminology.** *Type 2* and *Test 2* are the same thing: the **evaluation environment** that
> measures system **effectiveness** (a graded scorecard), as opposed to *Type 1 / Test 1* (hermetic
> development tests that measure **correctness**, pass/fail — detailed in §14). This document realizes the repo-matching
> spec's **M4** ("the matching benchmark"); its build is sequenced in **eval-harness stages E1–E3** (§2)
> — a build order **distinct from** the `GL-M*` / `BFL-M*` / spec `M1–M5` milestone tracks (see
> [`roadmap.md`](roadmap.md) §8) and from the doc-revision "vN" of the status line above.
>
> **Build status (updated 2026-07-11).** This is the canonical *design*; most of it has since **shipped**.
> The **E1–E3 harness + all 6 arms + the miner + the 9-repo atlas** are built (`gloop {eval, mine,
> build-atlas}`, `SemanticAtlasIndex`, `LLMJudgeIndex`, the `groundloop/eval/` package). Matcher arms that
> landed **after** this design — **component-routing, functional-bug, and fault-routing** (`gloop funceval` /
> `gloop faulteval`; `gloop run --match-arm {flood, routing, component}`) — extend the Stage-1 frontier beyond
> the original 6-arm matrix. **Measured results (env-tagged) live in [`results-log.md`](results-log.md); the
> current CLI is in `CLAUDE.md`.** Read §2 / §8 / §12's staging + effort estimates below as the original build
> order, now largely complete.

---

## 1. Purpose & scope

Type-2 answers one question: **is the system effective?** Concretely — given a real defect ticket
(text + failure logs) and a fleet of many repos, **how well does GroundLoop identify the repo that OWNS
the defect** (Stage-1, the primary objective), and secondarily localize the fix within it.

Two non-negotiable principles, inherited from the charter and enforced by the architecture:

- **Grounding over narrative.** Trust only what reality verifies — real matches over a real index,
  deterministic control flow, source-verified oracles. The score is computed against a **hidden oracle**,
  never against LLM prose.
- **The loop never sees the oracle.** The owning repo is a *predicted output + hidden-oracle field*,
  **never a loop input**. Grading is a **separate offline pass**. This is enforced by the anti-leak
  invariants (`tests/test_invariants.py`) and extended here to the eval harness (§9).

Type-2 is **effectiveness measurement**, not a pass/fail gate. Its verdict is a **scorecard**: per-arm ×
per-repo × per-stage metrics + cost + provenance, in JSON with a human-readable markdown twin.

**In scope (this document):** Stage-1 ticket→repo matching (primary) and Stage-2 localization
(secondary), across a matrix of matcher/signal **arms**, with a **forced** and a **selective
(grounded-refusal)** metric view. **Out of scope / hooks only:** Stage-3 fix quality (the fix engine is
a `CannedFixEngine` stub) and Stage-4 bind correctness (`MockGerrit.bound` is deterministically true) —
these surface as reserved fields, not graded capability (§2, §7).

**Two paired test surfaces.** This effectiveness evaluation (Type-2) is one of GroundLoop's two test
surfaces; the other is the **Type-1 hermetic development-test surface** (correctness, pass/fail, runs
every change) detailed in **§14**. The two map onto the dev-box/production split
([`environments.md`](environments.md)): Type-1 and Type-2-on-proxy run on the dev box, the real efficacy
scoreboard is production. Per that doc's mandated convention every result number is tagged **`[proxy]`**
(mechanism/regression — optimistic, may not transfer) or **`[production]`** (efficacy — the real number);
a bare efficacy number is a bug in the writeup.

---

## 2. The staged plan (E1 → E3)

The full benchmark is a **6-arm matrix** (3 matcher strategies × 2 signal conditions), shipped in three
**eval-harness stages** (E1–E3 — a build order, not a milestone track; see the Terminology note) so
**E1 is cheap and independently useful**, and each later stage adds exactly the machinery its arms
require.

| Stage | Arms added | Runs where | Question it answers |
|---|---|---|---|
| **E1** | membership × {text-only, +logs} (2) | Hermetic over the committed harvest snapshot (on-demand, *not* the per-change Type-1 CI surface) | Baseline recall; **do failure logs help** the match? (NFR-2 cost) |
| **E2** | +semantic (bge-m3) × {text, +logs} (2) | Type-2 gated (live embed gateway) | **Does semantic retrieval beat FTS5 membership** — the core hypothesis |
| **E3** | +LLM-judge × {text, +logs} (2) | Type-2 gated (live model) | Does an LLM adjudicator beat retrieval, and at what $/ticket? |

**Stages of the pipeline evaluated:**
- **Stage 1 (match)** — real in every version. `index.rank_repos(signals, catalog)` top-1 = predicted
  owning repo; graded by `groundloop/grade/grader.py`.
- **Stage 2 (localize)** — real from E1. `index.retrieve(chosen, query)` file hits; scored as
  `localization_recall` over `Oracle.expected_files` on a full-fidelity `run_ticket` slice.
- **Stages 3 (fix) / 4 (bind)** — **hooks + reserved null fields only.** `CannedFixEngine` makes fix
  quality meaningless, and bind is trivially always-true (`run_ticket` hardcodes `RunRecord.bound=True`;
  `MockGerrit.bind()` just appends a ledger row and transitions the ticket), so the scorecard carries a
  trivial `bound_rate` sanity column and reserves `fix_applies`/`bound_correct` for the (separate) downstream
  fix-loop eval — now shipped as `gloop fixeval` / `gloop compare` ([`fix-loop.md`](fix-loop.md), §6.4). Fix
  quality stays out of scope for *this* Stage-1 match eval.

**Grounded-refusal is in scope from E1.** Because the evaluation fleet (§3) yields hundreds of tickets
(well past the `n≥128` threshold that makes risk-coverage metrics trustworthy, §7), the selective view
is a first-class citizen, not a deferred footnote.

---

## 3. The evaluation fleet

A real ticket→repo match needs a **diverse, confusable fleet of real repos indexed over real code**. The
pilot is a curated **Android-IVI–representative** fleet spanning four function families, chosen for
**log-richness** (real failure signals to match on) and **issue↔fix linkage** (mineable oracles), with
lexically distinct namespaces so that *cross-family* matching is easy but *within-family* matching is the
real test.

**Registry status — BUILT (updated 2026-07-11).** This 9-repo eval fleet was produced + indexed into
`atlas-9.db` (~475k units); the first real evals ran over it (see [`results-log.md`](results-log.md)). It
expanded the original GL-M1 built-corpora layer 3→9 (`ndk-samples`, `libxcam`, `android-gpuimage-plus`,
charter §6): `android-gpuimage-plus` stays; `ndk-samples` and `libxcam` are **not IVI-representative** (they
were the M1 index-build corpus) and are dropped from the eval fleet (optionally retained as cross-domain
distractors). The 9 repos below (§5) are the pinned eval fleet.

### 3.1 Locked pilot fleet (feasibility-verified 2026-07-05 via `gh`)

| Repo | Family | Namespace | Linked issue↔PR pairs | Crash/log issues | Role |
|---|---|---|---:|---:|---|
| `osmandapp/OsmAnd` | navigation | `net.osmand` | 1351 | 1816 | mine (filter to `linked:pr`) |
| `organicmaps/organicmaps` | navigation | `app.organicmaps` | 1235 | 365 | mine |
| `AntennaPod/AntennaPod` | media/audio | `de.danoeh.antennapod` | 1014 | 808 | mine (clean "Fixes #") |
| `TeamNewPipe/NewPipe` | media/audio | `org.schabi.newpipe` | 935 | 3159 | mine (built-in crash reporter) |
| `google/oboe` | media/audio (native) | — (C++) | 318 | 189 | mine (native `.so` control) |
| `natario1/CameraView` | camera/graphics | `com.otaliastudios.cameraview` | 36 | 286 | mine (frozen/legacy) |
| `COVESA/dlt-daemon` | automotive (native) | — (C) | 33 | 18 | mine (native automotive) |
| `androidx/media` (media3) | media/audio | `androidx.media3` | 15 | 508 | mine (Gerrit — commit-trailer provenance) |
| `wysaid/android-gpuimage-plus` | camera/graphics (native) | `org.wysaid` | 4 | 23 | **curated-only** + existing hermetic fixture |

**Dropped after feasibility check:** `google/ExoPlayer` (redundant — absorbed into `androidx.media3`;
support-forum issue tracker, near-zero code linkage) and `android/car-samples` (0 issue↔PR linkage).
Charter §6 / roadmap §2 describe an earlier ~11-repo "charter pilot" that included both; **this §3.1 is
the single source of truth for finalized eval-fleet membership** (9 repos) — where the counts differ,
this table wins.

**Totals across the 8 mine-sources:** ~**4,937** linked issue↔PR pairs and ~**7,149** crash/log-signal
issues — two orders of magnitude above the original 3-repo corpus (which had 18 linked pairs total). This
is what moves Type-2 from "plumbing over a single fixture" to a statistically real evaluation.

### 3.2 Design properties the fleet buys

- **Within-family hard-negatives.** `{media3, NewPipe, AntennaPod, oboe}` (media/audio),
  `{organicmaps, OsmAnd}` (navigation), `{CameraView, gpuimage}` (camera) are each other's confusable
  distractors. Cross-family separation is trivial; the benchmark's difficulty lives *within* a family,
  which is exactly where a real triage engine earns its keep.
- **A native (`.so`-keyed) stratum for free.** `oboe`, `dlt-daemon`, `gpuimage` (and the C++ core of
  `organicmaps`) have **no JVM package namespace**, so the matcher must key on **`.so` names + native
  symbols** rather than a package shortcut. `AndroidSignalExtractor` already extracts `.so` names — it is
  how the existing `gpuimage-352` fixture matches (`libffmpeg.so`, `libCGE`). The scorecard reports a
  `native` stratum so we can see whether the matcher degrades when the package shortcut is absent.
- **Namespace-distinctness is deliberately neutralized as a *shortcut*.** A raw package namespace or
  `.so` name in a ticket is a **leak** (it uniquely identifies the repo). The leak-scrubber (§4.3)
  redacts these, so a correct match must come from **behavioral/log reasoning**, not string lookup.

### 3.3 Provenance caveats encoded per repo

- **`media3` and `OsmAnd`** are Gerrit-mirror / support-forum trackers: GitHub issue↔PR linkage is thin
  relative to closed-issue volume. The miner **filters to the `linked:pr` subset**; for `media3`,
  ticket↔commit binding is reconstructed from **commit trailers**, not GitHub PR links.
- **`CameraView`** is maintenance-stalled (last commit 2023) but its historical closed+linked set is
  mineable — treated as a frozen source.
- **`NewPipe`** ships a structured crash reporter → high-quality stack traces: the goldmine for the
  `+logs` arm.
- **`gpuimage-plus`** has near-zero linkage (4 pairs) → **not a mining source**, but stays in the
  *indexed* fleet as a camera/native hard-negative and remains the hermetic Type-1 fixture.

---

## 4. The dataset

Three sources feed **one on-disk schema**. The dataset is the ticket side (the queries + hidden oracles);
the atlas.db (§5) is the corpus side.

### 4.1 Sources

1. **Mine** (`gloop mine`, online via `gh` — the local checkouts are `--depth 1` shallow, so mining
   *must* go online). Source of truth = GitHub's **formal linked-PR relation**, both directions
   (`is:issue is:closed linked:pr` and the reciprocal `is:pr is:merged linked:issue`), throttled to the
   30 req/min search limit. Per linked pair: fetch the **issue body** (`gh api .../issues/N`) as the
   ticket, and the **merged PR's changed files** (`gh api .../pulls/N/files`) as `expected_files`.
   `owning_repo` = the issue's home repo; `owning_repo_sha` = the pinned SHA the atlas indexed.
2. **Curate** — hand-authored cases (the `gpuimage-352` pattern) for repos with weak linkage; loaded via
   the migrated knowledgeLoop TOML `_iter_tables` machinery.
3. **Unanswerable / out-of-fleet (OOF)** — SQuAD-2.0 / NIL style: either **hold the true owner out of the
   catalog** for a ticket, or inject tickets whose owning repo is genuinely outside the fleet. Marked
   `is_answerable=false` with an `__OUT_OF_FLEET__` sentinel, adversarially kept surface-similar to
   answerable tickets, balanced ~1:1. **This subset is what makes grounded refusal measurable** — on it,
   *abstaining is the correct answer* (§7).

### 4.2 Quality filters (admit a mined pair only if)

- the fix touches ≥1 **production source file** (drop doc/test/README/screenshot/config-only);
- `changed_files ≤ 5` (exclude refactors / mass-deletions — e.g. tangled 20k-line commits);
- **not** a merge or revert PR; additions+deletions above a floor;
- `num_repos_touched == 1` (multi-repo fixes are bucketed, never top-1 labeled);
- `expected_files` **exist at `owning_repo_sha`** (consistency with the indexed atlas.db);
- a **reproducible signal** (exception / stack / error / `.so` / class / method) is present or extractable
  — prioritize the crash/logcat issues; prose-only cases are bucketed separately.

*Rationale grounded in prior art:* only ~17–32% of changed lines in bug-fix commits are the actual fix
(tangled commits; Herbold et al. 2011.06244) → production-only + file-cap; automated issue↔commit link
recovery is lossy and biased, so admit only **explicit** links rather than keyword/recency heuristics
(issue-commit link recovery: 2107.01894; classic link-bias: Bird et al.); Defects4J's single-commit,
minimized-patch discipline is the gold standard for a clean oracle.

### 4.3 Leak-scrubber (the benchmark's integrity gate)

Issue text routinely names the exact fixing class/file/API/package — which would collapse ticket→repo
matching into string lookup (SWE-Bench+ found de-leaking cut apparent resolution rates to **roughly a
third** — e.g. 12.5%→4.0% for one strong agent; 2410.06992). The scrubber redacts, from the
**loop-visible** ticket + logs only:

- repo / owner names, **package namespaces & path prefixes**, fixing file / class / method names,
  `.so` names, and verbatim/near-verbatim patch fragments.

Every redaction is logged; `leakage_flags{reponame_in_text, file_in_text, class_in_text, package_in_text,
so_in_text, patch_in_text}` must **all be false** to admit a case. A Type-1 test asserts no unique repo
token survives in a sanitized ticket (§9). The **raw** (unsanitized) issue text is retained oracle-side
for provenance, never loop-visible.

### 4.4 Oracle schema (frozen-core respecting)

On-disk, one directory per case, extending the existing `gpuimage-352` layout:

```
dataset/<case_id>/
  ticket.json          # LOOP-VISIBLE: id, summary, description, component="" (never the owner), status,
                       #   logs:[{path,kind}]  — sanitized
  logs/*.txt           # LOOP-VISIBLE: sanitized logcat / stack text
  _oracle/oracle.json  # HIDDEN: owning_repo, owning_repo_sha, expected_files (production-only),
                       #   required_apis, is_answerable
  provenance.json      # HIDDEN: issue/pr refs, link_method, link_confidence, human_verified,
                       #   commit_flags{is_merge,is_revert,test_only,doc_only,tangled}, signal_class,
                       #   timestamps, split, dedup_group_id, nearest_confusable_repos
  leakage.json         # HIDDEN: leakage_flags, redactions[], scrubber_version
  raw/                 # HIDDEN immutable snapshot: issue.json, pr_files.json (reproducibility)
```

**Frozen-core discipline:** `core.types.Oracle` keeps only `owning_repo`/`expected_files`/`required_apis`.
The extra fields (`owning_repo_sha`, `is_answerable`, provenance, leakage) ride as **extra keys** that the
conftest `Case.oracle()` loader already drops (`_ORACLE_KEYS` filter) — read only by the eval layer, never
by the frozen `Oracle` dataclass. No `core/` edit, no SQLite-schema change.

**`owning_repo_sha` vs the `@base = fix^` anti-leak contract (NFR-4).** `owning_repo_sha` is the
**fix-inclusive** SHA the atlas indexed (so `expected_files` exist there) — deliberately *not*
`@base = fix^`. There is no contradiction with NFR-4 / testing-strategy invariant #3: **Stage-1 matching
does not materialize the repo**, so fix-hiding is N/A for the match metric — its only leak vector is the
ticket text, handled by the §4.3 scrubber. The `@base = fix^` scrub becomes relevant only to the
**Stage-2 localization fidelity slice**, which materializes via `run_ticket`; that slice inherits
invariant #3's status (currently `skip`-pending the real `RepoEstate`), so localization scoring stays
gated behind it.

### 4.5 Splits & volume

- **Splits:** `calib` (threshold calibration — never test), `eval`, and `holdout-postcutoff`
  (contamination control: most historical issues predate model knowledge cutoffs, so a post-cutoff slice
  is held out — a standard leakage-mitigation for issue-derived benchmarks).
- **Volume:** at a conservative 10–20% survival through quality + leak filtering, the ~4,937 linked pairs
  yield **~500–1,000 clean tickets**; a first pilot targets a few hundred, **capped per family** so the
  media/nav-heavy sources (NewPipe/OsmAnd/AntennaPod/organicmaps) don't swamp the thinner native/camera
  slots. Reproducibility: the online harvest is **snapshotted to committed JSON**, so the eval replays
  offline.

---

## 5. The substrate (atlas.db)

The corpus side: a real `atlas.db` over the pinned fleet, so `AtlasIndex` matches tickets to repos over
real code. Built once by `gloop build-atlas --registry corpora/atlas.toml` (a new one-shot orchestrator),
which runs:

1. **`produce` — parallel by repo, on DeepSeek.** One `gloop produce` **subprocess per repo**, fanned out
   with a bounded pool (`--jobs N`), each using `deepseek-chat` via the LiteLLM gateway
   (`KLOOP_PRODUCE_*`). Each subprocess *also* runs `produce`'s internal per-module concurrency
   (`--concurrency M`, wired through to the engine's `asyncio.Semaphore` — today defaulted to 1). **Total
   in-flight DeepSeek requests ≈ `jobs × M`**, kept under the gateway's rate budget by one documented
   knob-pair. Subprocess isolation (not one shared event loop) is chosen because `produce.generate()`
   owns its own `asyncio.run`; this needs **zero engine edits** (migrate-as-is), isolates per-repo
   failures, and per-repo `wiki_dir` means no shared-state contention. Re-runs skip fresh repos via
   `registry.repo_freshness` (`fresh`/`stale`/`unindexed` by `repo_head`). Output: **doc units**.
2. **`index` — bge-m3 embeddings.** `gloop index` (already async) reads each wiki (doc units) + CBM symbol
   rows (symbol units), embeds every unit through the **bge-m3** gateway, and writes `atlas.db`. Output:
   doc + symbol units + vectors, with the pinned `repo_head` recorded.
3. **`doctor` gate.** Verifies `repos > 0`, `units > 0`, embed-gateway + CBM readiness.

**Reuse contract (load-bearing):** the embed model is pinned `bge-m3` at **both index and query time**;
the query-time embedder MUST equal the index-time embedder or cosine ranking is silently corrupted.
bge-m3 is consumed as an external **OpenAI-compatible `/v1/embeddings`** endpoint (gateway / Ollama /
sentence-transformers server), selected by env (`KLOOP_EMBED_MODEL=bge-m3`, default in
`config/settings.py`) — the code never hosts it, and **changing the embed model forces a full re-index**.
A `manifest.json` stamps repo pins + embed model + atlas content-SHA into the run's provenance. See
[`environments.md`](environments.md) for the shared-`atlas.db` reuse contract across dev↔production,
[`build-setup.md`](build-setup.md) for the gateway health gates and exact commands, and
[`build-setup.md`](build-setup.md) for the reuse contract.

---

## 6. The arms

A matcher **strategy** × a **signal** condition. The matcher is a `CodeIndex` port implementation swapped
at the composition root; the signal condition is an extractor swap — both pure edge composition, `core/`
untouched.

### 6.1 Strategy axis

- **membership** — `AtlasIndex.rank_repos` (existing): FTS5 unit-membership over the extracted signal
  tokens, grouped by repo. Deterministic, hermetic-capable. The **naive baseline** the others must beat.
- **+semantic** — new `SemanticAtlasIndex(db, GatewayEmbedder)`: embeds `signals.tokens()` via bge-m3 and
  folds `store.vector_search` cosine hits into per-repo `RepoScore` (optionally RRF-fused with FTS5 via
  the existing `engines/atlas/retrieve.py` fusion). Network-bound → Type-2/live, `skipif`-gated. *(The
  benchmark measures this as a standalone arm for a clean A/B against membership; roadmap §4(b)'s
  shortlist→`repo IN (…)`-filtered two-stage rerank is the eventual production fusion — the arm isolates
  the same signal for measurement.)*
- **+LLM-judge** (E3) — new `LLMJudgeIndex(base_index, model)`: reranks/adjudicates the base index's
  top-k candidate repos via a gateway model (model-portable, temperature 0, scores snapshotted). Live,
  cost-captured.

### 6.2 Signal axis

- **+logs** — `AndroidSignalExtractor.extract(ticket.logs, ticket)` (text = logs + description).
- **text-only** — a `TextOnlyExtractor` wrapper passing `()` for logs (description only). Quantifies the
  log-signal lift (NFR-2: how much do the logs cost/help).

### 6.3 Determinism & gating

Membership arms are fully deterministic (invariant #6). Semantic/judge arms are network-bound
(non-deterministic across gateway state) → run at temperature 0, scores snapshotted for reproducibility,
and gated exactly like `tests/e2e`. A **reuse-contract guard** asserts the query embed model == index
`bge-m3` (a mismatch silently yields `cosine=-1` and garbage ranks).

### 6.4 Fix-stage arm — the dev-experience KB (SP3, LANDED 2026-07-06)

Beyond the matcher (Stage-1) arms above, the downstream **fix loop** carries its own measured arm: a
**dev-experience knowledge base** (`skills ∈ {none, mock}`). `gloop fixeval --skills mock` retrieves real
RCA/ops playbooks from a `MockSkillRegistry` (predicate-filter default; optional bge-m3 rerank, gated)
and injects them **post-match** as a `render_skills()` preamble on `ModelPatchEngine` — never a trusted
input, and the frozen `FixEngine.propose` signature is untouched. It is graded as **two runs diffed by
`gloop compare`** into a **two-sided `accept` verdict**: positive lift on `Δfile_recall@1` (or net
`newly_solved`) **and** no honesty regression on `Δfabrication_rate` (cost advisory). Because skills
inject *after* the match/abstain gates, they cannot move Stage-1 `abstention_recall_oof` — the only
honesty metric they can move is `fabrication_rate`, so "help positives without eroding negative-honesty"
is measured directly. The mock seed is small → the arm validates **plumbing + direction of effect**, not
the full lift the migrated Skills will show (directional-only). Real Skills drop in via
[`fix-loop.md`](fix-loop.md); full design in the SP3 spec §3.

---

## 7. Metrics & scorecard

Every arm reports **two views**. The **forced ceiling** (abstention off — always emit top-k) keeps arms
comparable and stops an arm hiding weak retrieval behind refusal. The **selective view** (abstention on)
measures grounded refusal. The charter is explicit: *a metric that rewards guessing over grounded refusal
is broken* — so the selective view is not optional.

### 7.1 Forced ceiling (Stage-1 match)

- `repo_recall@1` — top-1 == `owning_repo`. **The headline number.**
- `repo_recall@3/@5`, `repo_mrr`, `mean_repo_rank`.
- Note: because Stage-1 has a **single** exact-match target, file-level any-of metrics collapse
  (`recall@k == success@k`, `mrr == 1/repo_rank`). `grade/grader.py` already encodes the correct
  single-exact behavior; the migrated knowledgeLoop `recall_at_k/mrr/ndcg` are re-purposed for the
  **Stage-2 localization** path (a genuine multi-file any-of target), **not** repo-matching.

### 7.2 Selective view (grounded refusal)

- **Abstention mechanism:** gate on the **top1−top2 margin** (`ranked[0].score − ranked[1].score`),
  scale-robust vs the uncalibrated FTS5 count score; secondary floor on absolute top-1 score. Threshold
  `τ` is **calibrated on the `calib` split and frozen for test** (never tuned on test).
- **Metrics:** `coverage` (answered/N), `selective_accuracy`/`selective_risk`, the **risk-coverage
  curve**, `AURC` and `AUGRC`, and fixed operating points `accuracy@70%-coverage` and
  `coverage@5%-risk`.
- **Headline selective metric — Effective Reliability `Φ_c`** (Whitehead et al., 2204.13631):
  answered-correct `= +1`, answered-wrong `= −c`, **abstain on answerable `= 0`**, abstain on
  unanswerable `= +1`, answered on unanswerable `= −c`. A wrong guess (`−c`) is strictly worse than an
  abstain (`0`), so **guessing can never beat grounded refusal** — reported over a sweep `c ∈ {0.5, 1, 2}`
  with `c=1` the neutral default.
- **Unanswerable subset:** `abstention_recall_oof` (NoAns recall) on the OOF tickets, reported separately
  from `repo_recall@1` on the answerable subset, so a degenerate always-answer or always-abstain arm is
  immediately visible.

### 7.3 Statistics & honesty knobs

- **Wilson 95% CIs** on every proportion (stable from `n≈10`, unlike Wald).
- **`AURC`/`AUGRC` are gated on `n≥~128`** (badly biased below `n=32`; 2410.15361). The fleet's ticket
  volume clears this for the aggregate; per-stratum slices that fall below the threshold are flagged
  **directional-only**.
- **Compare arms at matched coverage** (or via `Φ_c` / the full RC curve), never at whatever coverage each
  arm happened to choose.
- **Per-stratum breakdown** (`signal_class` ∈ stack/error/prose; `family` ∈ media/nav/camera/automotive;
  `native` vs JVM) — catches abstention or error concentrating on one subgroup.
- **Baselines printed as floors:** random `1/N`, always-answer `recall@1`, always-abstain `Φ_1`.

### 7.4 Scorecard shape

`scorecard.json` (+ a markdown twin), structure = per-arm × {forced, selective, localization,
per_stratum, cost} + per-repo confusion + provenance:

```jsonc
{
  "provenance": { "atlas_db_sha": "…", "embed_model": "bge-m3", "repo_pins": {"…":"…"},
                  "harvest_snapshot_sha": "…", "n_cases": 0, "n_answerable": 0, "n_unanswerable": 0 },
  "baselines":  { "random_1_of_N": 0.0, "always_answer_recall1": 0.0, "always_abstain_phi1": 0.0 },
  "arms": {
    "membership__+logs": {
      "forced":       { "recall@1": {"v": 0.0, "wilson95": [0.0, 0.0]}, "recall@3": 0.0, "recall@5": 0.0,
                        "mrr": 0.0, "mean_repo_rank": 0.0 },
      "selective":    { "coverage": 0.0, "selective_accuracy": 0.0, "selective_risk": 0.0,
                        "aurc": 0.0, "augrc": 0.0,
                        "acc@70cov": 0.0, "cov@5risk": 0.0, "phi_c": {"0.5": 0.0, "1": 0.0, "2": 0.0},
                        "abstention_recall_oof": 0.0,
                        "operating_point": {"gate": "margin", "tau": 0.0, "calibrated_on": "calib"} },
      "localization": { "localization_recall": {"v": 0.0, "wilson95": [0.0, 0.0]} },
      "downstream":   { "bound_rate": 0.0, "fix_applies": null, "bound_correct": null },
      "per_stratum":  { "signal:stack": {}, "family:media": {}, "native:true": {} },
      "cost":         { "usd_per_ticket": 0.0, "in_tok": 0, "out_tok": 0 }
    }
    // …one block per strategy×signal arm…
  },
  "confusion": { "repos": ["…", "__ABSTAIN__"], "matrix": {} }
}
```

The primary comparison artifact is the **risk-coverage curve per arm**, with the forced `recall@k` marked
at `coverage = 1.0`.

---

## What's actually exercised vs idle (2026-07-19)

An eval-surface audit this session found the scorecard machinery above is **over-built relative to what any
read actually consumes**. Every effectiveness read to date (§10, `results-log.md`) reads only: `repo_recall@1/
@3/@5`, `repo_mrr`/`mean_repo_rank` (§7.1), `file_recall@1/@5` (localization), `patch_apply_rate`,
`resolved_rate_strict`, `required_api_pass_rate` (the `fixeval` metrics), and the `by_bug_kind` split. The rest
of §7.2/§7.3's **honesty/selective/abstention/negatives stack** — `coverage`, `selective_accuracy`/
`selective_risk`, the risk-coverage curve, `AURC`/`AUGRC`, `accuracy@70%-coverage`/`coverage@5%-risk`, `Φ_c`,
`abstention_recall_oof` — and the **KB-as-eval arm** (§6.4) are **built but not exercised by any effectiveness
read that has actually run**. This is not a defect to fix by deleting them: they encode intended future
evaluation (real honest-refusal negatives, a KB efficacy A/B) that the current dataset doesn't populate. They
are recorded here as **quarantined — "not exercised by any read"** — kept in place, not deleted, so nobody
mistakes idle machinery for a validated capability. See `docs/capabilities.md` for the governance framing.

**The substrate problem this idleness sits on top of:** every read that *has* run, ran on the **mine74 prose
regime** — real OSS GitHub issues, mostly feature/UI requests, carrying ~0 crash logs. That is a shape
**production never sends** (real AAOS tickets carry logcat/native-backtrace). The one time a `[proxy]` localize
positive was checked against `[production]` GEI (the `dispatch` arm, `capabilities.md` §"Candidate"), it came
back **0/10 INERT** — precisely because the proxy tested prose-only tickets while real tickets carry logcat.

**What this branch (`feat/e2e-eval-corpus`) shipped in response — machinery, no live read yet:**
- A **crash-log + merged-fix admission gate** in `groundloop/mine/` — `has_crash_signature(body)`
  (`mine/signal.py`) + `admit_e2e(candidate, *, require_crash_log, require_merged_fix)` (`mine/gh_miner.py`),
  reachable via `gloop mine --require-crash-log --require-merged-fix`. It selects only real, crash-log-bearing
  GitHub issues closed by a merged PR that touches production files — the representative shape.
- A **committed case manifest** (`groundloop/mine/manifest.py` + the placeholder
  `groundloop/mine/data/e2e_manifest.toml`): a git-versioned recipe+oracle per case (`repo`, `issue_number`,
  `issue_url`, `pr_number`, `pr_url`, `base_sha`, `fix_sha`, `owning_repo`, `expected_files`, `required_apis`).
  Bulky data (full logs, repo checkouts, the multi-GB atlas.db) stays off-repo and is regenerable from the
  manifest via `gh` + git at the pinned SHAs — this closes the "datasets are unversioned dev-box memory" gap.
  `base_sha` is resolved at build time as `fix_sha~1`, not stored. Public GitHub data only.
- An **honest end-to-end funnel report** — `render_e2e_funnel(scorecard, per_case)` in
  `groundloop/fixeval/report.py`: one markdown view grading match → localize → fix **on the same cases**,
  reusing `grade_fix_all`'s existing numbers (nothing recomputed). **submit/bind is always reported as the mock
  it is, never scored as `bound`.**
- **The trim:** retired genuinely-dead `eval/metrics.py::ndcg_at_k` + standalone `mrr()`/`success_at_k` (never
  called outside tests — the scorecard's `repo_mrr` is computed inline, not via this helper) and the orphaned
  `synth/functional.py::build_functional_negatives` (no caller). Nothing load-bearing was touched.

**State plainly: no live read has run.** The mining filter, manifest writer/loader, and funnel renderer are
hermetic-tested (fixtures, no network/no real LLM) — this is *machinery, ready to run*, not a result. The open
follow-up (gated Type-2, needs `gh` + gateway + a built atlas, so it cannot run hermetically) is: run `gloop
mine --require-crash-log --require-merged-fix` over a broadened Android/native repo set → commit the populated
manifest → build the atlas off ext4 → run the funnel (`[proxy]`). Expect **small n** (real crash-with-clean-fix
issues are scarce) and expect **fix to be measured, not targeted** — `resolved_rate_strict` on this corpus is a
number to observe, likely weak, not a bar this branch claims to clear. Spec/plan:
`docs/superpowers/specs/2026-07-19-e2e-eval-corpus-design.md`,
`docs/superpowers/plans/2026-07-19-e2e-eval-corpus.md`.

---

## 8. Harness architecture

Pure **ports & adapters** at the edges; **`core/` is frozen** (never edited for this feature — behavior is
swapped at the composition root, `cli/__init__.py`). Three new packages + two new adapters + one miner.

### 8.1 Packages & modules

- **`groundloop/build/`** — substrate build. `produce_fleet.py` (parallel-by-repo `produce` driver, §5),
  `atlas_build.py` (`produce_fleet` → `index` → `doctor`; `gloop build-atlas`).
- **`groundloop/mine/gh_miner.py`** — the dataset miner (`gloop mine`, §4). Build-time, online, out of the
  runtime path.
- **`groundloop/eval/`** — the measurement layer:

| Module | Responsibility | knowledgeLoop reuse |
|---|---|---|
| `dataset.py` | `load_cases(root)` globs case dirs; **never reads `_oracle/` at load** | adapt `offline/cases.py` (`_iter_tables`) |
| `extractors.py` | `TextOnlyExtractor` (the text-only arm) | new |
| `arms.py` | index-factory × extractor-factory → the 6 arms | new |
| `abstain.py` | margin/threshold policy → predict\|ABSTAIN | new |
| `runner.py` | `EvalRunner`: per (case×arm) drive matching; **oracle never enters** | adapt `offline/harness.py` loop |
| `metrics.py` | recall@k/mrr/ndcg (localization) + Wilson/`Φ_c`/AURC/AUGRC/RC | migrate `offline/metrics.py` + new |
| `cost.py` | token→USD for live arms | migrate `cost.py` (extend PRICES) |
| `scorecard.py` | **the only oracle read** — offline grade + aggregate | adapt `offline/harness.py` + `aggregate.py` |
| `report.py` | markdown twin | migrate `offline/report.py` |

- **New adapters** (under `adapters/index/`, since they are `CodeIndex` port impls, not eval logic):
  `atlas_semantic.py` (`SemanticAtlasIndex`) and `atlas_judge.py` (`LLMJudgeIndex`).

### 8.2 Data flow — the oracle-blind runner

```
load_cases(root) ─┐                          [ARM EXECUTION — oracle NOT in scope]
                  ├─ for (case × arm):
MockJira.fetch ───┤    ticket  = issues.fetch(case_id)
                  │    signals = arm.extractor.extract(ticket.logs OR (), ticket)
arm.index ────────┤    ranked  = index.rank_repos(signals, estate.catalog())   ← DIRECT, skips
                  │    decision= abstain.decide(ranked)                            materialize→…→bind
                  └─   append MatchRecord{case_id, arm, ranked, predicted, margin} → predictions.jsonl
                                            │
  ═══════════ barrier: all arms done ══════╪═══════════════════════════════════════
                                            ▼        [OFFLINE GRADE — sole oracle read]
scorecard.grade_all(predictions, cases):  Case.oracle()  →  score_match(ranked, oracle)
                                          →  aggregate per-arm × per-repo × selective → scorecard.{json,md}
```

- **Matching-only path** (`index.rank_repos` directly, not full `run_ticket`) isolates the Stage-1 metric,
  is cheap, and lets the harness own the ablation + abstain decisions. A small **`run_ticket` fidelity
  slice** exercises the real control plane and lights up `localization_recall` + `bound`.
- Because the direct path builds no `RunRecord`, `scorecard.py` adds a matching-only `score_match(ranked,
  oracle)` alongside the reused `grade/grader.grade` (used for the fidelity slice). `grade/grader.py`
  is reused **verbatim**; `core/` untouched.
- **CLI (composition root):** `gloop build-atlas`, `gloop mine`, `gloop eval` — added in `cli/__init__.py`
  alongside the existing `run`.

---

## 9. Integrity & guardrails

The evaluation is only as trustworthy as its leak-tightness. The Type-1 anti-leak invariants
(`tests/test_invariants.py`; full numbered list in §14.3) are extended to the eval harness:

- **Oracle isolation.** Arm execution produces `MatchRecord`s **without** the oracle; the oracle is read
  **only** in the offline `scorecard.grade_all` pass. A Type-1 test extends the existing `Path.read_text`
  **read-spy** to `EvalRunner`, asserting it never reads anything under `_oracle/` during arm execution
  (invariant #4).
- **No answer in the ticket.** The sanitized ticket never names the owning repo/namespace/file
  (invariants #1/#5) — a Type-1 test asserts no unique repo token survives the scrubber over the dataset.
- **Genuine N-way choice.** The catalog is a real ≥3-candidate choice with the owner as one of them
  (invariant #5); the fleet is diverse enough that a `1/N` guess scores far below a real match.
- **Determinism** of the membership arms (invariant #6).
- **Reuse-contract guard** for the semantic arm (query embed model == index bge-m3).

**Two test surfaces (§14):** membership arms + all metric math are **Type-1 hermetic** (FTS5 fixture
atlas, no network); semantic/judge arms are **Type-2 gated** (`skipif` on the live-service env flags),
exactly like the existing `tests/e2e`. The full anti-leak invariant list these extend is §14.3.

---

## 10. Methodology & prior art

Type-2's metric choices are distilled from the knowledgeLoop repo-atlas evaluation lap-log
([`../../knowledgeLoop/docs/repo-atlas-evaluation.md`](../../knowledgeLoop/docs/repo-atlas-evaluation.md),
which ran the same "grounding over narrative" discipline against a real `bge-m3` atlas and learned — the
hard way — where a retrieval metric can be trusted) and the retrieval/selective-prediction literature.
Load-bearing lessons:

- **The evaluation pyramid — measure the cheap deterministic layers directly; reserve the expensive
  agentic test for *outcome validation*, not tuning.**

  ```
    4. Agentic A/B (outcome)         expensive, noisy   → validate, don't tune
    3. Context-injection             (dozens of runs)
    2. Grounding   precision/recall  cheap, deterministic
    1. Retrieval   Success@k / MRR   (ms/case, no agent) → tune here
  ```

  Layers 1–2 are agent-free and run in seconds, so a strategy/signal arm can be tuned offline with real
  statistical power (N in the hundreds). Layer 4 is the only thing that measures the actual goal but is
  statistically weak at the N we can afford — it *validates* that offline gains translate, it is not the
  day-to-day instrument. Type-2's Stage-1 arms live on the deterministic layer.
- **Any-of vs all-of.** When several targets are equally valid, the primary retrieval metrics are
  `Success@k` (any acceptable gold in top-k) + `MRR`, with `Recall@k` demoted to a coverage stat (it
  understates by design). *In GroundLoop this bites only at Stage-2 localization* (`localization_recall` —
  several files may legitimately own a fix). **Stage-1 is different: the owning repo is a single hidden
  oracle, so `repo_recall@1`/`repo_mrr` are exact-match, not any-of** (§7.1).
- **Grounding is scored against source reality, not the store.** The "real" symbol set is
  **grep-verified from repo source**, never sampled from the index — so a real symbol the store fails to
  confirm counts *against* it. This surfaces under-indexing as a *product* risk (the tool telling an agent
  a real API "doesn't exist"), the discipline behind the grounded-use / grounded-refusal checks (§7.2).
- **Mechanism-resolved evaluation.** A binary success rate over small N is uninterpretable, so the agentic
  layer traces the causal chain per task (*surfaced the right prior art? → agent used it? → beat
  baseline?*) and classifies each task (`causal-win`/`surfaced-ignored`/`retrieval-miss`/`regression`/
  `no-effect`), attributing any non-win to an adoption gap vs a retrieval gap vs no-headroom.
- **The N≈10 / ±20pp noise floor.** At the N an agentic A/B can afford, the lap-log measured two
  *behaviourally identical* conditions scoring **20% vs 40% `[proxy]`** — pinning the N=10 noise floor at
  ≈ ±20pp. Treat any agentic arm difference below that as noise; this is exactly why the primary effort
  sits on the deterministic layers and the selective view (§7.2) is the load-bearing signal.
- **Leakage is the dominant benchmark-killer.** SWE-Bench+ (2410.06992) showed de-leaking cuts apparent
  capability to roughly a third — hence the §4.3 scrubber + admit-gate + Type-1 leak tests.
- **Oracles from issue→fix links** (SWE-bench 2310.06770; Defects4J single-commit minimized patches;
  tangled-commit hazard, 2011.06244) → explicit-link gating + production-only + file-cap.
- **Selective prediction** (2407.01032): coverage, selective risk, the RC curve, and **AUGRC** as the
  robust cross-arm summary; **`Φ_c`** (2204.13631) as the guess-vs-refuse-honest headline; SQuAD-2.0
  (1806.03822) / NIL entity-linking for the unanswerable subset.
- **Small-N honesty** (2410.15361; Wilson): lead with fixed-operating-point + `Φ_c` + Wilson CIs; treat
  `AURC` as directional below `n≈128`.

---

## 11. Risks & limitations

- **Volume/imbalance at the pilot.** Even with the richer fleet, per-family caps leave the native/camera
  slots thin; per-stratum CIs there are wide. *Mitigate:* lead with forced `recall@1` + Wilson CIs;
  grow the corpus toward the full linked set before ranking arms by `AURC`.
- **Residual leakage.** A deterministic scrubber can miss paraphrased identifiers. *Mitigate:* leak-flags
  admit-gate + Type-1 token test; an LLM leak-detector is a later upgrade.
- **Non-hermetic mining.** Ticket text lives on github.com under a 30/min search cap, and repos
  archive/edit. *Mitigate:* snapshot all harvested JSON; the built dataset replays offline.
- **Semantic-arm fragility.** `GatewayEmbedder` is network-bound (Type-2 only); `store.vector_search` is
  a full-table Python cosine scan (fine at pilot scale, an ANN caveat at 130+ repos); a bge-m3
  model/dim mismatch silently corrupts ranks. *Mitigate:* `skipif`-gate + reuse-contract guard.
- **Mining circularity.** Heuristic issue↔fix recovery would re-introduce the matching problem the
  dataset evaluates. *Mitigate:* admit **only** GitHub's formal linked-PR relation; record `link_method`.
- **Multi-repo / contested ownership.** Real fixes can span repos. *Mitigate:* `num_repos_touched == 1`
  admit-gate; multi-repo cases bucketed, never top-1 labeled.

---

## 12. Roadmap alignment, effort & deferrals

> **Since shipped (2026-07-11):** E1–E3 below are **built** (`gloop eval --semantic --judge`, the
> `groundloop/eval/` package, `SemanticAtlasIndex` / `LLMJudgeIndex`, `gloop mine` / `build-atlas`). The
> effort estimates are the original plan, kept for provenance; measured results are in
> [`results-log.md`](results-log.md).

**Staging maps to build order** (each stage independently shippable):

- **E1 (~1.5–2 wks):** `build/` (parallel produce + index + doctor) · `mine/` (miner + scrubber +
  snapshot) · `eval/` (dataset, runner, abstain, metrics, cost, scorecard, report) · membership ×
  {text, +logs} · Stage 1 + Stage 2 · full selective scorecard + per-repo confusion · Type-1 leak-spy.
  Hermetic over the committed snapshot; ships the first honest `recall@1` + `Φ_c`.
- **E2 (~3–4 d):** `SemanticAtlasIndex` + `KLOOP_EMBED_*` plumbing + reuse-contract guard + `skipif`-gated
  Type-2 test → the 2 semantic arms (the "does semantic beat membership" comparison).
- **E3 (~3–4 d):** `LLMJudgeIndex` (adapt knowledgeLoop `GatewayJudge`) + cost capture + live-arm
  snapshotting → the 2 judge arms.
- **Ongoing:** the aggregate ticket count already clears `n≥128` (§7.3); corpus growth targets
  **per-stratum** `n≥200–300` for stable per-slice rankings, toward the charter's 130+ fleet.

**Explicitly deferred (YAGNI / different research question):** Stage-3 fix-correctness grading (needs a
real `FixEngine` + a blinded judge — the downstream fix-loop eval, [`fix-loop.md`](fix-loop.md));
the knowledgeLoop agentic A/B surface (`ClaudeRunner`, `aggregate/causal/correlation`, `grounding_scorer`,
`oracle.store_exists_fn`); an ANN vector index; a trained/learned reranker; a multi-domain plugin
framework.

**Fix-stage runner arms (forward-looking, BFL provenance).** From the loop-agent fix-loop track
(BFL-M0..M9; [`fix-loop.md`](fix-loop.md)): `single_shot` is the default runner
arm, with an agentic `tool_loop` (investigate-then-submit) as a non-default measured arm; a grep
retriever ran **~25% cheaper `[proxy]`** than no-retrieval on real-sized repos with **no localization
loss** (a cost lever, not an accuracy one). Carried caveat: on a *synthetic* seed that benchmark rewards
confident guessing and penalizes honest grounded refusal, so `tool_loop`'s true value stays unprovable
until a genuinely-buggy benchmark exists — the same "grounding over narrative" concern the selective view
(§7.2) and the §6.4 KB arm's two-sided `accept` gate encode. GroundLoop's fix stage is a `CannedFixEngine`
stub today, so these arms are forward-looking here.

---

## 13. Open questions

1. **Fleet balance vs the native stratum** — are the native slots (`oboe`, `dlt-daemon`, `gpuimage`) deep
   enough, or should a fourth native/automotive repo be added to firm up that stratum's CIs?
2. **`media3` provenance** — the fleet (§3.1) *provisionally* mines `media3` via commit trailers (its
   GitHub PR links are sparse); the open question is whether trailer-reconstructed binding proves clean
   enough, or `media3` should become an indexed distractor only.
3. **Selective operating point** — the risk-coverage curve is the fixed primary *artifact* (§7.4); open
   is the primary reported *scalar* (AURC vs accuracy@fixed-coverage) and the gate mechanism (margin vs a
   calibrated confidence).
4. **`jobs × concurrency` default** for `build-atlas` — the safe steady-state against the DeepSeek gateway
   rate budget (to be measured, then pinned in `build-setup.md`).

---

## 14. The Type-1 hermetic development-test surface

The paired surface to the Type-2 effectiveness eval above. Per [`environments.md`](environments.md), Type-1
and Type-2-on-proxy run on the **dev box**; the real efficacy eval runs on **production**. Type-1 measures
**correctness** (pass/fail, runs every change); Type-2 measures **effectiveness** (a graded scorecard).

**Substrate** — hermetic, deterministic, no network / no real LLM (NFR-8): `CannedModel`
(`adapters/mock/model.py`) over a micro-fleet; shared fixtures in `tests/conftest.py` (`harness`,
`atlas_harness`, `case`, `atlas_db`, `catalog_path`) + `tests/fixtures/atlas_fixture.py` (a 4-repo FTS5
`atlas.db`, no CBM/embedder) + `tests/fixtures/android_ivi/` (`catalog.json`, `index.json`, the `gpuimage-352`
case with `ticket.json` / `logs/` / `_oracle/oracle.json`).

**Coverage** — the full hermetic vertical slice (`test_e2e_vertical_slice.py`: `run_ticket` → match→…→bind →
offline `grade`) plus per-stage tests (intake / extract / match / estate / fix / bind / grade), the engines,
the ports/types/CLI/settings, and the `run/` self-scoring layer (record IO, batch, grader, CLI). Runs every
change.

**Anti-leak invariants** (`tests/test_invariants.py`) — green regression guards; a failure means a real leak
was reintroduced:
1. the ticket never names the owning repo (component/summary/description/logs/comments scanned);
2. `owning_repo` only in the oracle (absent from `ticket.json` / `logs/`);
3. `@base` isolation — weak form green; the full `@base = fix^` history-scrub is `skip` pending the real
   `RepoEstate` (a Type-2 substrate item);
4. the loop never reads the oracle / bind-output (a `Path.read_text` spy over a full run);
5. signals don't encode the answer (owner absent from matcher tokens; catalog is a real ≥3-way choice, FR-3);
6. deterministic control flow (same inputs → identical events, choice, ranked order, `Change-Id`);
7–8. **self-scoring** — the persisted run-record is oracle-free; `grade_run` is the sole oracle reader.
   *Bridge to Type-2:* `test_atlas_matcher_honors_invariants` asserts the real `AtlasIndex` picks the owner
   from log signals alone and beats the `1/N` guess (fleet-integrity backstop, §9).

**Cadence + gaps** — every change, hermetic by default; the two `tests/e2e/` live cases are `skipif`-gated on
`KLOOP_*` creds (DeepSeek is the only live model). Open Type-1 gaps: un-skip invariant #3 when the real
`RepoEstate` lands; add an embedder-mismatch guard once the semantic-rerank arm lands (today the `bge-m3` pin
is enforced only by the reuse contract, not a hermetic test).

**Non-goals** — Type-1 does not measure effectiveness/ranking quality (that is Type-2), does not run real
models or network, and does not exercise the real atlas (a 4-repo FTS5 fixture stands in).

## Appendix — knowledgeLoop reuse map

Migrated from `/mnt/x/code/knowledgeLoop/knowledgeloop/eval/` (import rewire `knowledgeloop.*` →
`groundloop.*`, logic preserved):

- **MIGRATE-AS-IS:** `offline/metrics.py` (pure `recall_at_k/success_at_k/mrr/ndcg_at_k` — re-purposed for
  Stage-2 localization) · `cost.py` (`PRICES/cost_of/cost_from_raw`; extend PRICES for model-portability).
- **ADAPT:** `offline/cases.py` (`_iter_tables/_require`/dedup verbatim; **move `repo` from an input field
  to the hidden oracle field** — a verbatim migration would leak the oracle) · `offline/harness.py`
  (aggregation + per-repo pattern; rewrite the per-case loop to call `rank_repos`/`retrieve` + grade) ·
  `offline/report.py` (relabel columns) · `extract.py` (`+++ b/` touched-files parse, for
  patch→locations when the fidelity slice needs it).
- **SKIP (defer to the downstream fix-loop eval):** `runner.py` (`ClaudeRunner`), `judge.py`
  (`GatewayJudge` — later reused for the E3 judge arm), `aggregate.py`/`causal.py`/`correlation.py`,
  `oracle.py` (`store_exists_fn`), top-level `metrics.py`, `grounding_scorer.py`, `offline/doc_verify/`.

**Key axis caveat:** knowledgeLoop retrieval metrics are **file-level any-of**; GroundLoop Stage-1 is a
**single exact-match repo** target, where those metrics collapse and `grade/grader.py` already encodes the
correct behavior — so they are wired to the **localization** path, never to repo-matching.
