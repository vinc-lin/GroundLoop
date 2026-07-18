# GroundLoop — Status

**As of 2026-07-18.** Read this first when resuming; see
`CLAUDE.md` for durable project context.

**Docs are the single source of truth** (re-consolidated 2026-07-11 → 13 top-level docs, + `capabilities.md`
2026-07-12 + `data-flow.md` 2026-07-17; full map in `CLAUDE.md`). Read [`environments.md`](environments.md) first — the canonical dev-box ↔ production split +
the **`[proxy]`**/**`[production]`** result-tag convention used throughout this file. Core set:
[`charter.md`](charter.md) · [`architecture.md`](architecture.md) · [`data-flow.md`](data-flow.md) · [`guide.md`](guide.md) ·
[`evaluation.md`](evaluation.md) · [`build-setup.md`](build-setup.md) · [`fix-loop.md`](fix-loop.md) ·
[`engines.md`](engines.md) · [`production-guide.md`](production-guide.md) · [`roadmap.md`](roadmap.md) ·
[`results-log.md`](results-log.md) · [`capabilities.md`](capabilities.md) · [`workflows.md`](workflows.md).

## Done

### Localize recall — Phase-2 literal-anchor cascade shipped + [proxy] read (2026-07-18) ✅
Shipped **`--localize cascade`** (Phase 2): a recall-first RRF union of the prose FTS floor + crash code-tokens +
literal anchors + optional bge-m3 semantic tier (`CascadeLocalizeIndex` + literal-anchor extractor + atlas
rarity gate). Subagent-driven with a **4-lens adversarial Workflow** that **caught a real non-regression
merge-blocker** (the prose floor was a fallback, not a union member → recall regression below `--localize
atlas`; fixed + regression test, gate tightened `max_files` 40→10). Opt-in Candidate, `core/`+schema zero-diff,
suite **728 green**, merged to master (`d3b8a3b..ed8820e`).
- **[proxy] read** (isolated file@k, n=108 mine74, **baseline** atlas-6-doc.db): the cascade beats the floor
  (0.075/0.244 → **0.098/0.308** file@1/@5) — BUT the **literal tier is marginal/mixed** (marginal file@1
  **−0.011**, file@5 +0.009); **the SEMANTIC tier is the lever, not the literal anchor** — this **partially
  disconfirms the design's central bet**. Baseline atlas ⇒ literal tier at partial strength (no CamelCase).
  `docs/results-log.md` 2026-07-18. **NOT promoted to default** — governance holds pending the [production] read.
- **Next (gated / open):** the CamelCase-atlas cascade read (full literal strength) + [production] GEI file@k +
  the deferred A3 match-regression = the promotion gate; and the **cascade-recall → rerank-judge** integration
  (cascade wins recall@5, judge wins file@1 at 0.212 — combine them). Open: keep the literal tier in the default
  cascade given its file@1 cost, or gate it?

### Localize recall — first-principles re-scope + Phase-1 mechanical fixes shipped (2026-07-18) ✅
A first-principles review ("is the Localize stage even necessary?") re-scoped the pending pool-widening plan.
Verdict (verified against code): Localize is necessary as a **concept**, **not** as a **hard gate** (`workflow.py:35`
hands fix the full worktree — the gate is a fix-adapter convention, relaxable without touching `core/`) and **not**
as a **file@1 target** (the loss is recall, not mis-ranking). Design = **Option B** recall-first cascade
(`docs/superpowers/specs/2026-07-17-localize-recall-cascade-design.md`). Shipped **Phase 1** (mechanical layer,
subagent-driven with adversarial review, 5 commits `084252a..5457e77`, **merged to master**): the `--localize
rerank` bge-m3 vector lane now **fails LOUD** instead of silently degrading to keyword-only (`return 2`/raise on a
missing embedder; per-case embed failures counted into `manifest.localize_embed_failures`), the CamelCase splitter
is shared (`engines/atlas/tokenize.py`, applied query-side with a match-noise filter caught in review) and an
opt-in `KLOOP_INDEX_CAMELCASE` splits identifiers at index time (default OFF = byte-identical). `core/` +
atlas-schema **zero-diff**; full suite **718 green**, ruff clean.
- **A1 `[proxy]` read** (isolated file@k, n=108 `mine74`, `atlas-6-doc.db`, live bge-m3): the vector lane
  **provably fires** — `atlas` (floor) 0.075/0.244 → `rerank_pool` (lane ON) 0.084/**0.267** (file@1/file@5); a
  **modest** standalone lift — the judge/literal/CamelCase tiers are the real levers. `docs/results-log.md` 2026-07-18.
  A1's win is **correctness**: a rerank scorecard can no longer silently reflect a dead vector lane.
- **Next (deferred, gated):** Phase 2 (literal-anchor cascade + RRF union + abstain-on-no-anchor), Phase 3
  (soft-gate fix: `locations` as seeds + CBM expansion), the benchmark re-point (`bug_kind` split + `localize_hit`),
  and the `[production]` GEI localize file@k read (lane ON) + the A3 CamelCase-atlas rebuild + match-regression —
  the Candidate→Core promotion gate.

### CodeWiki + CBM in localize & fix — full enablement + live A/B (2026-07-16/17) ✅
Fully enabled the two under-used code-understanding assets in the read-stages: **CodeWiki** (per-module LLM
docs) + **CBM** (code-graph) now feed the **localize reranker** (`--localize rerank` — a grounded LLM
file-judge over a CodeWiki/CBM-enriched hybrid pool) and the **fix prompt** (`--fix-context {codewiki,cbm}`).
Subagent-driven build (reranker, live `CBMLiveGraph` facade, doc→source `entity_map` bridge + `gloop bridge`,
fix-context injection, per-case `@base=fix^` checkout, miner `fix_patch`+`required_apis`), then a live A/B on a
new 6-repo doc atlas — all opt-in **Candidates**, `core/`+atlas-schema **zero-diff**.
- **Substrate:** `atlas-6-doc.db` (6 repos, 96,654 units incl. **9,665 doc units**; `atlas-9.db` had **0**) +
  per-repo `entity_map.json` + `mine74` (108 live-`gh` cases / **96 fix-gradeable** with real diffs+`required_apis`).
  Built off ext4.
- **cameraview engine bugfix (`1277e9f`):** CodeWiki `produce` crashed (KeyError, aborting a whole repo → 0 md)
  on a **name-colliding module tree** (a `video_encoding` child under a `video_encoding` parent) — the tree
  walkers descended into `children` by name-value, not index. Fixed in all 3 walkers + a hermetic regression
  test; cameraview **0→52 md**.
- **LOCALIZE A/B `[proxy]`** (isolated ceiling on the oracle repo, **prose-ticket regime**, n=108): FTS5 floor
  **file@1 0.075 → 0.212** (+0.137, 2.8×; file@5 0.235→0.384). The **LLM judge is the bigger lever (+0.083)**;
  **CodeWiki-under-judge +0.056** (pool+context *entangled*, one `entity_map` toggle); **CBM marginal (+0.038,
  within noise**, 26-case subset). ~$0.0014/case. Hybrid pool + CodeWiki-in-pool do ≈0 at rank-1 *without* the
  judge → recall-alone doesn't move rank-1; the grounded reorder does.
- **FIX A/B `[proxy]`** (forced oracle repo + forced oracle localization so only context varies, n=29): **no
  measurable fix-context effect** (resolved 1/29 vs 0/29; **CBM never fired** — 0-signal prose tickets ⇒
  CodeWiki-only; underpowered). The plan fixer correctly **abstains, not fabricates**. Fix effectiveness is
  blocked on a **crash-with-fix substrate**, not context — consistent with the KB re-verdict below.
- **Adversarially verified** (4-lens refutation workflow, all **CAVEATED** — numbers reproduce, no measurement
  bug): caught the isolated-ceiling framing, the CodeWiki pool+context entanglement, judge-is-the-bigger-lever,
  the prose-regime confound, CBM-never-fired-in-fix, and the fix underpowering — all folded into the record.
- **Governance (`capabilities.md`):** `--localize rerank` (+CodeWiki, judge) → promotion **Candidate** (first
  `[proxy]` file@1 lever); gate = a **`[production]` crash-ticket `file@1`** read + an e2e (match-gated)
  confirmation. `--localize +CBM` and `--fix-context {codewiki,cbm}` stay **OFF** (no measurable benefit /
  untested).
- **Docs:** `results-log.md` 2026-07-16 entry (`ee6440b`) · design-logic
  `docs/superpowers/specs/2026-07-16-localize-fix-design-logic.md` (`9335421`) · module/data-flow map
  `docs/data-flow.md` + CLAUDE.md pointer (`62f6035`). Suite **704 passed / 8 skipped, ruff clean.**

### Production-Core defaults + loop closure — 11-task branch (2026-07-13) ✅
Branch `prod-core-defaults-loop-closure` (subagent-driven, 11 tasks). Promotes the fix default, closes the
feedback loop's data plane + reporting edge on the dev box, and prunes the production surface — **plumbing +
governance, NOT a new efficacy read** (no new `[proxy]`/`[production]` numbers).
- **Bug Plan Mode → Provisional-Core `gloop run` default:** `--fixer plan` (the `PlanningFixEngine`) is now the
  default (choices `canned|model|plan`, + a `--max-replan` flag; the fail-closed guard covers `model` **and**
  `plan`); it now re-gates its *executed* diff against the localize candidate set (abstains if out-of-scope) —
  end-to-end anti-leak. **Proven merit = safety** (`fabrication_rate = 0.0`, abstains not fabricates);
  **effectiveness is production-gated** — `resolved_rate` was never gradeable. A new governance state
  **Provisional-Core** is written into [`capabilities.md`](capabilities.md): default-on on a *fail-safe*
  mechanism + a charter-aligned safety argument, resolving to Core-or-revert on the next instrumented
  `[production]` run.
- **Data plane closed:** a `RecordingExtractor` sidecar captures the loop's `signals`; the run-record persists
  `signals`/`cost_usd`/`tokens`/`model_calls`/`fixer`; each batch writes a provenance `manifest.json` (atlas
  identity + model pins + affinity hash + `change_sink=mock` + timestamp). Plan/patch primitives relocated
  `fixeval/` → `groundloop/fix/` (Core decoupled from Dev-Labs).
- **Reporting edge closed:** grade-run cards carry per-case predicted/oracle repo + signals + cost + fixer;
  `grade-run --compare <prev-card>` → a per-stage improved/flat/regressed verdict + a `.compare.json` sibling;
  reporting-only promotion-eligibility notes (fire for `--fixer plan` runs with gradeable resolution).
- **Surface pruning:** a `KLOOP_DEV` dev-gate rejects `--index`/`--fixer canned`/`--case` in production (the
  Type-1 suite arms `KLOOP_DEV=1` via an autouse fixture); the `--repos` guard was hardened from presence-only
  to verifying catalog snapshots actually exist.
- **Open follow-up:** the deferred **`[production]` `resolved_rate` A/B (plan vs model)** is what resolves Bug
  Plan Mode's Provisional-Core status (grade-run emits the promotion note). Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-13-production-core-defaults-and-loop-closure*.md`. **608 passed / 7
  skipped, ruff clean, `core/` + atlas schema zero-diff.**

### KB fair-eval Phase 1 — harness fix + re-verdict (2026-07-13) ✅
The KB's "Archived null" was measured on the wrong outcome. Phase 1 (branch `kb-fair-eval-phase1`,
subagent-driven, 2-stage-reviewed): synth now plants a headroom-clean `required_api` (named in the skill
guidance) into 6 crash classes → `resolved_rate` is **gradeable for the first time** (the miner hard-coded
`required_apis=[]` and synth omitted it — it was undefined loop-wide); + `gloop fixeval --skills-inject
fix-only` (KB into the fix prompt only, not the localize query). Live A/B (34-case gradeable slice, `--fixer
direct`, ~$0.10): **harness fix validated** (`fix-only` provably localize-invariant — `none`=`kb·fix-only`
file@1 0.157); **confound confirmed** (skills in the localize query cost **Δ−0.10** file@1); but
**`resolved_rate` INCONCLUSIVE** (0 floor — the synthetic log is disconnected from the real fix, so nothing
resolves; synth is the wrong substrate for resolution). Verdict: the Archived null is **discredited** but the
KB is **unproven** → reclassified **Archived → Candidate**. **Phase-2 scout (same day)**: the OSS proxy fleet
has only **~7–15** genuine crash-with-fix cases (features/UI dominate, not AAOS crashes) — too few to test the
KB. Every dev-box substrate is exhausted (synth: 0 resolution; OSS-real: ~no crashes), so the KB verdict is
**production-gated** — it needs real AAOS crash+fix tickets; the Phase 2 spec now stands as a production-side
task. Detail: `results-log.md` 2026-07-13. **572 passed / 7 skipped, ruff clean.**

### Production-Core / Dev-Labs governance + `gloop run` default re-point (2026-07-12) ✅
Adopted the **Production Core + Dev Labs** model and applied it. New [`capabilities.md`](capabilities.md):
every capability classified **Core / Candidate / Dev-Labs-Infra / Fixture / Archived** with evidence
(seeded by an evidence-graded, adversarially-verified sweep of the whole tree). Headline: the real
Production Core is ~a dozen pieces; the alternative matchers + fix engines are `[proxy]`-only **Candidate**;
the whole KB track is **Archived** on a measured null (0/60 claims; raw Skills Δ−0.14). Biggest finding —
the default `gloop run` was a **hermetic toy end-to-end** (canned fixer + empty `MockEstate` + mock
JIRA/Gerrit + `flood`). **Re-pointed the composition-root defaults** (`cli/__init__.py`, no `core/` edit):
match `flood`→`component` (auto-affinity via `--affinity`/`KLOOP_AFFINITY`, loud flood fallback), fixer
`canned`→`model`, **fail-closed** when `--fixer model` lacks creds or `--repos` (no more silent `CannedModel`
degrade). Hermetic Type-1 runs now select `--fixer canned` explicitly. Also corrected a doc mislabel: the
`[production]` localize (7/10 file@5) ran **plain FTS5 `AtlasIndex.retrieve`**, not bge-m3+qwen (eval-only).
**566 passed / 7 skipped, ruff clean.** Remaining Core gaps (net-new builds): live JIRA `IssueSource` +
live Gerrit `ChangeSink` — the traceable JIRA↔commit chain is still mocked at the ends.

### Self-scoring pipeline — `gloop run` batch + `gloop grade-run` (2026-07-11) ✅ MERGED to master
Fixes the *measurement* failures the first e2e run exposed (localize misread as 0/10; an 8-vs-7 hand-tally).
`gloop run` now persists the `RunRecord` it used to discard (batch mode over a dataset, oracle-blind) + `--repos`
(CheckoutEstate) / `--fixer {canned,model}` knobs; `gloop grade-run` is an offline per-stage scorecard — match
`recall@1/@3/@5`, localize **as-run** (on chosen) + **isolated** (on oracle repo = the "7/10 not 0/10"
auto-correction), fix `resolved_strict`/`fabrication` **or** honest `UNGRADEABLE(no_source)`, a `by_bug_kind`
split, and a generated per-case markdown table. **Zero `core/` edits** (the frozen `RunRecord` already carried
`ranked`/`locations`/`patch`); reuses `eval`/`fixeval` machinery (`load_cases`, `load_eval_oracle`,
`recall_at_k`, `FixRecord`, `grade_fix_all`, `patch_applies`). New units: `groundloop/run/{record,batch,grade_run,
report}.py` + additive `RecordingEstate`/`CheckoutEstate`. Leak-honest (red-tested invariants 7–8: run-record
oracle-free, `grade_run` sole oracle reader). 8 tasks, **566 passed / 7 skipped, ruff clean**. Spec/plan:
`docs/superpowers/{specs,plans}/2026-07-11-self-scoring-pipeline*.md`; runbook `docs/production-guide.md` §8.
*Process note:* Tasks 1–3 ran subagent-driven with 2-stage review; Task 4's implementer subagent emitted an
anomalous (self-generated, non-injected — verified via its transcript) jailbreak-pattern output and did nothing,
so Tasks 4–8 were completed in the main context. No compromise; config/repo clean.

### First end-to-end production run — 10 functional GEI cases (2026-07-11) ✅ first efficacy read
The **first full 8-stage `gloop run`** on real production GEI data (10 functional cases, `component` match arm,
`component_affinity.json` mined from **1,169 JIRA↔Gerrit oracle pairs**, real **19-repo / 126,919-unit** atlas
built with the **bge-m3** embedder + **qwen3p6-27b** CodeWiki producer — both *index-build-time*, not query-time).
This is the production scoreboard the component-routing pivot was built for. **Match recall@1 7/10 `[production]`** by the per-case table (⚠ the run summary reported 8/10 — a
count-reconciliation flag: 2 root causes but **3** missed cases `13363`/`14905`/`8185`; confirm against the raw
scorecard). **Localize 7/10 file@5, 1/10 file@1 `[production]`** — a **measurement correction**: an earlier "localize 0/10"
was misreading the fix stage's *fabricated* file. Localize runs `AtlasIndex.retrieve` = **plain FTS5 keyword
search** over symbol units (the bge-m3 vector / qwen-rerank paths are eval-only arms, never wired into
`run_ticket`) — so *keyword localize alone* already gets 7/10 file@5 on production. **Fix 0/10 but ungraded `[production]`** — an **empty-worktree** artifact (only `XCIPadMediaService` checked out
under `$GL_DATA/repos/`), not a fix-stage failure. Root causes: match misses = label≠owner (`13363`
Bluetooth→cluster) + CarPlay Core-vs-Integration near-tie (0.005 gap < base RRF ≤0.017); localize misses =
coverage gap (`8185` `CpAccessibilityManager.kt` not indexed) + pool recall (`14905`/`4240`). **Highest-value
unblock = check out the 4 owner repos** so fix becomes gradeable (production-side). Detail:
`docs/results-log.md`. Dev-box follow-ups (gated on the 406): CarPlay semantic
tiebreak, a `component`-override text signal for label≠owner, per-file localize aggregation.

### Component-routing match arm — MERGED to master (2026-07-10); proxy mechanism check ✅
Production feedback on the real 19-repo GEI atlas redirected the functional-bug track: ticket-text matching is
size-biased (recall@1 **0.10 `[production]`**), and an empirical **JIRA component→repo affinity prior** is the dominant Stage-1
lever (**0.10 → 0.50** recall@1, 0.90 recall@3 `[production]`, zero token cost). This **reconciles the "component unusable"
call below** — that was true for *naive* skills lookup (repo-name keys vs functional-area component values,
0/10 `[production]`); an **empirically-derived** affinity map (learned from the JIRA↔Gerrit oracle) bridges the vocabulary.
Built loop-blind + frozen-safe: `ComponentAffinity` (raw counts + leave-one-out), `gloop mine-affinity`
(offline miner), `ComponentExtractor`/`ComponentPriorIndex` (carry the component through the `Signals` seam,
**strip before the base**, **RRF-rank-fused** so it's scale-invariant to the base's score magnitude),
`gloop funceval --affinity/--loo` + `gloop run --match-arm
{flood,routing,component}`. **Leak-honest:** runtime reads only `Ticket.component` (loop-blind); the eval avoids
train/test leak via **leave-one-out** (grader-side, subtract the case's own contribution). Subagent-driven,
**11 commits, 547 passed / ruff clean, `core/`+atlas-schema+`rank_repos`+`owner_tokens.py`+`repo_routing.py`+
`mine/` zero-diff**, two-stage review per batch + final holistic review (READY TO MERGE; caught 3 plan-fixture
slips). **Proxy mechanism check** (`docs/results-log.md`): the prior lifts the FTS
base to **component recall@1 0.49 / recall@3 0.92** (flood 0.32/0.58) `[proxy]` — the same SHAPE as the measured
production `comp+fusion` (~0.50/0.90) `[production]`: the prior narrows to top-3, within-component disambiguation is the gap.
LOO is unit-proven load-bearing on rare pairs and correctly-negligible on well-populated ones. **Real efficacy
= production** (run the real affinity build +
406-case LOO eval on the GEI corpus; then the gated Step-3 `XCUSBMediaService` index + Step-4 CarPlay).
- Spec/plan: `docs/superpowers/{specs,plans}/2026-07-10-component-routing-match*.md`.

### Functional-bug matching arm (the "second problem") — MERGED to master (2026-07-10); live A/B ✅
The successor to v2: attribute **no-crash functional bugs** (wrong UI text, audio, CarPlay/projection) to the
owning repo when there is no crash frame. Originally text-primary (JIRA `component` looked unusable via naive
skills lookup — **later superseded**: the empirical component-affinity prior above is the dominant signal on
real GEI data; see the component-routing entry). A frozen-safe `(extractor, index)` bolt-on: `FunctionalTextExtractor`
finally uses `ticket.summary`+description (v2 ignored summary), carrying prose through the frozen `Signals` seam as
a reserved `symbols[0]` slot; `FunctionalTextIndex` = bge-m3 max-cosine over a **lightweight per-repo text profile**
(README+manifest+module ids; `gloop build-textprofile`, no 12 GB atlas rebuild) ⊕ optional log-FTS RRF; abstain via
the reused `decide()`+`TAU_FUNC`. A per-case **`dispatch`** arm routes crash-anchor→v2 `FaultRoutingIndex`,
prose-only→functional (Signals-only discriminator; `fault_scale` bridges the two score scales). Offline `bug_kind`
(crash|functional) oracle field + `by_bug_kind` scorecard split + `gloop funceval` + `gloop synth --mode functional`
(UI-text/audio/CarPlay + honest-refusal negatives). Subagent-driven, **28 commits, 530 passed / ruff clean, `core/`
+ atlas schema + gated `rank_repos`/`owner_tokens.py`/`repo_routing.py`/`mine/` zero-diff**, per-task spec+quality
review + final holistic review — caught **6 real defects** (retrieve no-op, walk-prune, dispatch tau-scale over-abstain,
audio-`.so` false signal, and the **ticket-text owner-slug leak** that would have let `flood` cheat).
- **Live A/B (`docs/results-log.md`):** 212 functional + 196 crash over `atlas-9.db`.
  **Functional recall@1: flood 0.32 → functional/dispatch 0.68 `[proxy]`** (~2.1×; Φ₁ +0.30 → +0.39); the v2 crash arms
  (`faultslice`/`routing`) correctly **abstain** on no-crash tickets (0.01, coverage 0.00 `[proxy]`) — reproducing + fixing the
  GEI `8/10 no_fault` `[production]` failure mode. **Crash: `dispatch` 0.94 == `routing` 0.94 `[proxy]`, no regression.** One `dispatch` arm =
  **0.94 crash + 0.68 functional** `[proxy]`. Develop-against-feedback: the first run's profile-build timeout (partial 4/9 repos
  → false 0.26 `[proxy]`) was fixed by bounding profile chunks, then rebuilt 9/9 → valid 0.68 `[proxy]`.
- GEI/406 oracle is **production-only** (proxy regresses, production scores — see [environments.md](environments.md)).
- Deferred: functional honest-refusal negatives folded into the A/B dataset; per-`functional_class` breakdown.
- Spec/plan: `docs/superpowers/{specs,plans}/2026-07-10-functional-bug-match*.md`.

### Android Log Match v2 — fault-localization + attribution — MERGED to master (2026-07-09); live A/B ✅
Isolate the true fault site from a long full-system logcat and attribute it to the owning repo, with
fault-localization and attribution scored **separately**. Built toward the real ecarx/gkui estate, validated
on an **unscrubbed OSS proxy** (package namespaces are legitimate owner signal there). Deterministic pipeline
(no gateway): `logcat_parse` → `frame_norm` → `fault_extract` (anchors + pid/tid scope + confidence →
`FaultRecord`) → `fault_signals` (tight `Signals`) → Phase-1 `faultslice` (reuse `rank_repos`) / Phase-2
`FaultRoutingIndex` (production-known prefix/SONAME routing + RRF). New `gloop synth --mode faultlog`
(clean|hard decoys + fault-locus oracle) and `gloop faulteval` (3-arm A/B + `fault_localization` metric).
Subagent-driven, **18 commits, 494 passed / ruff clean, `core/` + atlas schema + gated `rank_repos`/
`owner_tokens.py`/`mine/` zero-diff**, per-task spec+quality review (caught 3 real bugs: timestamp swap,
`fault_file` basename collision, soname-boundary misclassification) + a final holistic review (READY TO MERGE).
- **Live A/B (`docs/results-log.md`):** 196-case faultlog over `atlas-9.db`.
  **Attribution recall@1: flood 0.48 → faultslice 0.86 → routing 0.94 `[proxy]`** (tight extraction ~doubles it).
  **Robustness:** under hard decoys the flood baseline **drops 0.48→0.32 `[proxy]`** while faultslice/routing are
  **unchanged** (decoy-immune). **Localization:** `frame@1=0.88` / `frame@5=0.95` `[proxy]`. Log-quality audit:
  **0/187 owner-leak** in clean noise (honest), needle at 25–75% depth, 196/196 oracle integrity.
- Deferred (sanctioned): confidence-weighted RRF, the `no_fault=9` audio-underrun class (non-fatal → the
  second-problem track), UI-string / ticket-text matching (the deferred **second problem**).
- Spec/plan: `docs/superpowers/{specs,plans}/2026-07-09-android-log-match-v2*.md`.

### GL-M0 — walking skeleton
Deterministic ticket → repo → fix → bind loop over the mock adapters + `TokenIndex` stub + offline
grader. Hermetic vertical slice green.

### GL-M1 — real index (consume + build)  ·  17 tasks, final review PASS
Migrated the full index engine from knowledgeLoop behind the ports:
- `engines/atlas` (Store — schema unchanged; chunk/symbol_source/source_probe; embed/retrieve/registry;
  index_repo/build_units), `engines/lore` (CBM graph client/nodes/forward, bridge/schema NodeRecord,
  deploy launch-spec, wiki loader; `_resolve_repo_head` extracted — `server.py` NOT migrated),
  `engines/produce` (CodeWiki generation, 86 files).
- `AtlasIndex` (CodeIndex port) = FTS5 unit-membership `rank_repos` over a real atlas.db; discriminates
  the owner from hard negatives (hermetic-tested on a hand-built fixture db).
- CLI: `gloop index` (build atlas.db from a registry), `gloop produce` (wiki), `gloop doctor`
  (readiness). `gloop run --index-db` swaps `AtlasIndex` for `TokenIndex` at the composition root —
  `core/` untouched.
- Reuse contract honored: `embed_model` pinned `bge-m3`; store schema migrated unchanged.
- CBM packaging: **Level-1 default hard dep** (`mcp` + `codebase-memory-mcp==0.8.1` + produce stack in
  base `[project.dependencies]`; launched as the installed binary, not `uvx`).
- Detail: `docs/build-setup.md`.

### Type-2 track — SP1 → SP3 (honest-refusal negatives + fix-loop eval + dev-experience KB)  ·  COMPLETE
The four-sub-project Type-2 extension (design: `docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md`),
all shipped to master, `core/` untouched, hermetic + gated surfaces:
- **SP1a/SP1b** — honest-refusal **negatives** (four classes; Φ_c + `abstention_recall_oof`; per-arm τ;
  leak-tight opaque `case_id`; closed-loop reject). Grounded refusal is now a real Stage-1 number.
- **SP2** — the downstream **fix/RCA loop + eval** (`groundloop/fixeval/`): `FixEvalRunner` drives
  localize→propose-patch directly (never the frozen `run_ticket`); `grade_fix_all` = `file_recall@k` +
  `patch_applies` + `required_api_pass_rate` + advisory `resolved_rate` + whole-loop **`fabrication_rate`**;
  `gloop fixeval` / `compare`.
- **SP3** — the dev-experience **KB as a measured arm** (`groundloop/skills/` + `MockSkillRegistry`,
  real-data seed): `gloop fixeval --skills {none,mock}` injects `render_skills()` playbooks post-match on
  `ModelPatchEngine`; graded by the two-sided `accept` gate (Δfile_recall POS + Δfabrication_rate honesty);
  declarative-compiled predicates; migration guide + non-vacuous parity self-test (`docs/fix-loop.md`).
- Detail: `docs/evaluation.md` (§6.4 fix-stage arm), `docs/fix-loop.md`.

### Plan-format fix stage — MERGED to master + pushed (2026-07-07); live A/B RUN ✅
Turns the fix stage into a grounded **plan-then-act** loop: a two-phase `PlanningFixEngine`
(plan → oracle-blind in-world gate → bounded re-plan → abstain → execute) behind
`gloop fixeval --fixer plan`. Shipped hermetically — 16 commits, full suite **366 passed / 7 skipped**,
ruff clean, `core/` + atlas schema **zero-diff**, per-phase spec+quality review + a final holistic review:
- **resolved_rate hardening** — `resolved_rate_strict` (patch's OWN `touched_files` ∩ `expected_files`;
  required APIs on non-comment code lines), reported beside the old proxy for comparability.
- **PlanningFixEngine** + `RepairPlan` + tolerant parser + the **anti-leak** in-world gate
  (scope-checked BEFORE any disk read; rejects `..`/absolute paths; never reads the oracle).
- **Grounded grader** — `plan_groundedness` (oracle-blind, recorded at run time) + `plan_target_recall@1/5`
  + `plan_api_match` (offline); plan archive (`plan.json` + `fired_skills` + outcome, capture-only).
- **KB validation surface** — `--skills distilled` arm + `accept_grounded` two-sided gate
  (POS = Δplan_target_recall@1 / Δresolved_rate_strict > 0; HONESTY = Δfabrication ≤ 0 ∧ Δgroundedness ≥ 0)
  to validate **raw + distilled** KB knowledge under `--fixer plan`.
- Spec `docs/superpowers/specs/2026-07-07-plan-format-fix-stage-design.md` · plan
  `docs/superpowers/plans/2026-07-07-plan-format-fix-stage.md`.
- **Merged + a follow-on FTS5 fix** (`_fts_query` now quotes leaf tokens so a KB Localize hint containing
  `NOT` no longer crashes matching/localize — this had crashed the earlier kb-ab live run).
- **Live A/B RUN (Phase 3, `docs/results-log.md`):** 56-case correct-match
  slice (oboe 25 + dlt-daemon 19 positives + 12 neg), ext4-staged (Finding 10), 4 arms + 2 compares.
  **Q1 engine (direct vs plan):** a *structural* tie — `file_recall@1` is fixer-invariant (0.189 both `[proxy]`,
  localize precedes fix) and the grounded axis is uncomparable (direct emits no plan → Δ=None). The plan
  arm produces the intended grounded artifact (`plan_target_recall@1` 0.48 / `@5` 0.68, groundedness 0.56,
  fabrication 0.0 `[proxy]`) that `direct` lacks, but its *executed patches* don't apply on synth (`apply_rate`
  1.0→0.0 `[proxy]`) and resolution is ungradeable (no `required_apis`) — so **plan-vs-direct on resolution stays
  open**, blocked on a `required_apis`-bearing slice, not the plan format. **Q2 KB-under-plan:** raw KB
  **hurts** — `plan_target_recall@1` **plan/none 0.48 > placebo 0.36 > kb 0.22** (Δ kb-vs-placebo −0.14) `[proxy]`,
  an independent fresh-run reproduction of the claim-KB §8 verdict (messy Skills injected wholesale
  degrade the planner). Fabrication 0.0 all arms `[proxy]`.

### Claim-centric distilled KB — MERGED to master (2026-07-07); live preview ✅, full efficacy pending
> **Vocabulary correction (2026-07-14, branch `skill-to-knowledge-rename`):** the distilled unit `Claim` was
> renamed **`Knowledge`** (`--claims`→`--knowledge`, `kb/claim.py`→`kb/knowledge.py`, `claims.json`→
> `knowledge.json`); a `Skill` is now **input-only** (raw feedstock, never a KB output); **Lane A** (the
> reversed *harvest → distill* lane that minted a Skill as output — `kb/harvest/`, `kb/distill/`, its
> `gloop` CLI driver, the `--skills distilled` arm and its `.toml` artifact) was **removed**; and `gloop
> kb-ab` was retargeted to gate on **Knowledge**. This is a naming + surface correction only — **no efficacy
> change**; the KB stays
> **Candidate/unproven**. The historical `[proxy]` numbers below are unchanged.

Inverts the KB onto atomic grounded **claims** (design/plan: `docs/superpowers/{specs,plans}/2026-07-07-
claim-centric-distilled-kb*.md`): Skills are feedstock; `kb-extract` (LLM proposes → ground-check disposes)
→ `--claims` arm injects only tier-qualifying claims into the plan → `kb-attribute` (screen → LOFO-confirm
vs placebo → per-claim promote/retire). Phases A–C shipped subagent-driven — **15 commits, 449 tests, `core/`
+ atlas schema zero-diff**, per-phase spec+quality review + final holistic review (caught + fixed: porous
grounding, redundant live-eval spend, an uncaught promotion-gate regression, the `--claims-store` gap).
- **Live preview (2026-07-07, `docs/results-log.md`):** the full path runs on real
  infra — `kb-extract` minted **60 grounded candidate claims** from the 12 Skills (ground-check correctly
  dropped ~14 templated/unindexed refs = "LLM proposes, gate disposes" validated). The fix-eval efficacy
  numbers were zero `[proxy]` on a 4–8-case slice, but for **artifacts** (match size-bias mispredicting the slice's
  repo; only 1 repo staged on ext4 → wholesale abstain; synth cases lack `required_apis`) — a plumbing
  validation, not an efficacy verdict. One honesty hint: `plan` abstained where `direct` fabricated.
- **First efficacy read (Phase D lite, ~7.5 min via the ext4 fix):** on a correct-match slice
  (oboe + dlt-daemon), the raw **candidate** claims do NOT beat placebo (`plan_target_recall@1`: none 0.625,
  claims 0.50, placebo 0.50; fabrication 0 all `[proxy]`) — consistent with the design (unvalidated claims aren't
  trusted wholesale). `kb-attribute` (the retain-loop) timed out under the 15-min cap, so no tiers promoted.
- **Full Phase D verdict (§8, ~2 h unbounded, 2 disjoint windows):** the retain-loop validated **0** of the
  60 candidates (all `lofo_delta=0`, none load-bearing; 4 retired) → the empty validated set = no-injection,
  and *no-injection (0.51) beats placebo (0.37) beats the raw 12 Skills (0.22)* on `plan_target_recall@1` `[proxy]` —
  the messy Skills injected wholesale HURT the planner. Empirical vindication of the distill-first /
  distrust-unverified design. Detail: `docs/results-log.md` §8.

### Testing environment
- **Type-1 (hermetic)** — `tests/conftest.py` (shared fixtures: `case`, `harness`, `atlas_harness`,
  prebuilt atlas.db, canned model) + `tests/test_invariants.py` (the anti-leak §2.3 red-tests — the
  design already honored them; these lock it in). **Suite: 55 passed / 3 skipped, ruff clean.**
- **Type-2 (live eval) — prepped + de-risked** (`.env` gitignored / `.env.example` /
  `/mnt/x/code/corpora/atlas.toml` / `docs/build-setup.md`):
  - ✅ **CBM validated live** on android-gpuimage-plus: 31,552 nodes / 41,191 edges, symbols in 3.3s.
  - ✅ **produce validated live** (deepseek-chat) → wiki generated; the pydantic-ai 1.x→2.x compat
    shim WORKS end-to-end (the M1 "latent risk" is now cleared). The `gloop produce` model default is
    now **`deepseek-chat`** (was `gpt-4o-mini` — unusable here: the gateway has no OpenAI backend).
  - ✅ Fixed: CBM launches the bare `codebase-memory-mcp` binary, so `.venv/bin` must be on `PATH`
    (now exported in `.env`).
  - ✅ **Test 2 (Type-2) live acceptance GREEN (2026-07-05):** both gated `tests/e2e/` tests pass live
    (`test_index_build_live` = produce→CBM→bge-m3 embed→atlas.db, 2:13; `test_produce_live` = wiki gen).
    First-ever execution surfaced + fixed two issues: a **missing `groundloop/cli/__main__.py`** (the
    tests invoke `python -m groundloop.cli`, which had no runnable entry) and the produce smoke's fragile
    asserts (retargeted to produce's real deliverable — `metadata.json` + a per-module `*.md`; `overview.md`
    / a non-empty `module_tree.json` are not reliably emitted for tiny repos).

## Current blocker — CLEARED ✅ (2026-07-05)
The pinned `bge-m3` embedding host is **back UP** — re-checked 2026-07-05: `/embeddings` → HTTP `200`,
returns a valid 1024-dim non-zero vector. The prior `000`/hung state (GPU/Ollama backend down) is
resolved. **No open blocker.** The full `gloop index` build (produce → CBM → embed → atlas.db) and the
2 gated live tests (`tests/e2e/`) are now unblocked. `deepseek-chat` (produce LLM) remains up.
Gate check (prints `200` when healthy): see `docs/build-setup.md` → "Embedding-host gate".

## Next steps
1. **Now unblocked (bge-m3 up 2026-07-05) — run the GL-M1 live acceptance:** `gloop produce` +
   `gloop index` over `/mnt/x/code/corpora/atlas.toml` → build `~/.groundloop/atlas.db`; `gloop doctor`;
   then run the gated live tests (`tests/e2e/`) with `KLOOP_EMBED_API_KEY` + `KLOOP_CBM_READY=1` +
   `KLOOP_PRODUCE_READY=1`. Runbook: `docs/build-setup.md`.
2. **Symbol filtering** before scaling the fleet — android-gpuimage-plus yields ~31k symbols because it
   vendors ffmpeg headers; drop vendored `ffmpeg/**` to cut embedding cost + noise. (Small follow-up.)
3. **Grow the eval fleet** — uncomment `libxcam` / `ndk-samples` in `corpora/atlas.toml`; a meaningful
   Stage-1 match needs several confusable repos so a `1/N` guess scores far below a real match.
4. **Resolve Bug Plan Mode's Provisional-Core status — the deferred `[production]` `resolved_rate` A/B (plan
   vs model).** The real fixer is now the `gloop run` default (2026-07-12 `--fixer model`; 2026-07-13 → the
   Provisional-Core `--fixer plan`), so the *wiring* is done; the open follow-up is the instrumented
   `[production]` run that measures `resolved_rate` (grade-run emits the promotion note) → confirm Bug Plan
   Mode into Core or revert to `--fixer model`. Still-open Core builds: an ANN vector index, live JIRA/Gerrit
   adapters, Tier-2/3 grading. *(`gloop mine` + the `gloop run` real-fixer default have since shipped — no
   longer next steps.)*
5. **Resolve `--localize rerank`'s Candidate status — the `[production]` crash-ticket localize `file@1` read.**
   The `[proxy]` win (CodeWiki-under-judge +0.056 file@1, 2.8× overall) is an *isolated ceiling on prose OSS
   tickets*; the promotion gate is a `[production]` GEI **crash-ticket** read (where code-token candidate-gen,
   not the prose fallback, drives the reranker pool) **+** an e2e (match-gated) confirmation. Sub-tasks: a
   disentangle-CodeWiki arm (`judge + doc→source pool, no wiki-context`); and a **crash-with-fix substrate** so
   the fix-context question (CBM in fix is genuinely untested — it never fired on signal-less tickets) becomes
   answerable at all. Detail: `docs/data-flow.md`, `docs/superpowers/specs/2026-07-16-localize-fix-design-logic.md`.

## Services / environment
- **LiteLLM gateway** — creds in the gitignored `/mnt/x/code/loop-agent/.env`, reused by
  `GroundLoop/.env`. Serves: `deepseek-chat`/`deepseek-reasoner` (UP), `bge-m3` (**UP** as of 2026-07-05,
  1024-dim) + `mxbai-embed-large` + `qwen3` (GPU/Ollama-backed — `qwen3` DOWN at last check).
- **Corpora** — `/mnt/x/code/corpora/` at pinned SHAs (`corpus.toml`): android-gpuimage-plus, libxcam,
  ndk-samples. Registry: `corpora/atlas.toml`. Built atlas.db target: `~/.groundloop/atlas.db`.
- **Git** — `master` @ `62f6035` (CodeWiki+CBM localize/fix A/B + docs), pushed to `origin`
  (`github.com:vinc-lin/GroundLoop.git`) and in sync. **Local branches pruned 2026-07-11:** the merged
  feature branches (`self-scoring-pipeline` + the 8 older `feat/*`: claim-centric-kb, plan-format-fix-stage,
  type2-{eval-e1c,judge-e3,miner-e1b,semantic-e2,substrate-build,symbols-index}) were deleted with `git
  branch -d` after confirming each was merged; **only `master` remains local.**
