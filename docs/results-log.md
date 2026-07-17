# GroundLoop — Results Log

Chronological GroundLoop results. Each number is tagged `[proxy]` (mechanism, dev box) or `[production]`
(efficacy, GEI) — see `environments.md`. Full detail for any entry lives in git history at the cited path.

| date | track | env | headline |
|---|---|---|---|
| 2026-07-18 | localize recall — Phase-1 mechanical fixes (vector-lane hardening + CamelCase index) | `[proxy]` | **A1 vector lane now provably fires** (was silently OFF): isolated file@k n=108, `atlas` (FTS5 floor) → `rerank_pool` (hybrid bge-m3∪FTS5): file@1 0.075→0.084, file@5 0.244→**0.267** (+0.023) — modest *standalone* lift (the judge/literal/CamelCase tiers are the real levers, deferred). + fail-fast on missing embedder, counted embed-degrade, opt-in `KLOOP_INDEX_CAMELCASE` (A3 Type-1-proven, efficacy A/B deferred). Opt-in Candidate; `core/`+schema zero-diff; suite 718 green; merged to master. Gate = `[production]` GEI localize file@k with the lane ON |
| 2026-07-16 | CodeWiki + CBM in localize & fix (new 6-repo doc atlas) | `[proxy]` | **LOCALIZE** (isolated ceiling, prose-ticket regime, n=108): CodeWiki-under-judge **narrows** rank-1 — file@1 **0.075→0.212** (+0.137 abs, 2.8×; ~60% judge / ~40% CodeWiki, and CodeWiki's share is pool+context entangled); CBM marginal (+0.038, noise). **FIX** (n=29, floor): CodeWiki-only fix-context **no measurable effect** (**CBM never fired** — 0-signal tickets); resolved ≤1/29. → `--localize rerank` a **Candidate** (gate = `[production]` crash-ticket file@1); `--fix-context` stays OFF |
| 2026-07-15 | **`--localize tokens` PROMOTED to Provisional-Core default** (was `atlas`) | governance | Core-default localize flipped `atlas`→`tokens` (`_resolve_arms`); recorded as **Provisional-Core** with an honest fail-safe-adjacent caveat (no *new* failure mode vs `atlas`: token-less ⇒ byte-identical; token-bearing ⇒ more grounded, within FTS5 envelope). No embedder ⇒ no new prod dependency. `--localize atlas` = reversible opt-out. **`[production]` GEI `file@1` read is the resolver** → confirm Core / revert |
| 2026-07-15 | **`--localize tokens`** (signal-aware FTS5) 3-arm A/B | `[proxy]` | 212 functional cases, isolated + canonical: **tokens file@1 0.166 ≈ dispatch 0.161 but with NO embedder** (pure FTS5), and ≥ dispatch per class (ui_text 0.014 vs dispatch 0.000 — tokens falls back to atlas, dispatch to worse semantic). ⇒ the semantic branch adds an embedder dep for negative file@1 value; **`tokens` → PROMOTED to the Provisional-Core default** (see the row above; `[production]` GEI read pending) |
| 2026-07-14 | localize dispatch **prod-fixes A/B** (Bugs 1/2/3) | `[proxy]` | 212 functional cases, isolated + canonical grading: fixed dispatch **file@1 0.010→0.161** (+0.151). **Entirely from Bug 2** (code-tokens-in-FTS5): carplay (log carries fault class) **0→0.494**; the semantic branch (Bug 1) is neutral-to-negative (audio/ui_text ~0 either way). ⇒ **Bug 2 is the lever; make tokens-in-query the default; demote semantic.** Re-run GEI to resolve `[production]` |
| 2026-07-14 | functional localize dispatch — **`[production]` = INERT** (+ non-representative proxy) | `[production]` | **GEI run: `file@1 = 0/10`** — dispatch's semantic branch **never engages** under `--match-arm component` (real tickets carry logcat → `AndroidSignalExtractor` fills `classes` → `is_functional_localize`=False → FTS5, always). The earlier `[proxy]` "file@5 +0.021" was on **prose-only (`logs=[]`) cases** where the discriminator fires — NOT representative of production. Also: grading path-prefix mismatch (`app/src/main/java` vs `src/java`) marks rank-1 hits as misses (score understated). Bugs confirmed in code |
| 2026-07-14 | KB rename `Claim`→`Knowledge` + Lane-A removal | governance | vocabulary + surface correction only: distilled unit renamed (`--knowledge`, `knowledge.json`), Skill is input-only, Lane A (harvest→distill) removed, `kb-ab` gates on Knowledge — **no efficacy change**, KB stays Candidate/unproven |
| 2026-07-13 | labs arms run-reachable + functional-arm A/B | `[proxy]` | experimental arms wired into `gloop run` + `KLOOP_LABS` switch (Core default unchanged); functional recall@1 **0.68** vs flood 0.32 (+0.36) on 212 functional bugs via the built `textprofile-9.db`; stays Candidate |
| 2026-07-13 | Production-Core defaults + loop closure (11-task branch) | governance | Bug Plan Mode → **Provisional-Core** default (`--fixer plan`); feedback data-plane + reporting-edge closed on dev box; dev-gate + hardened `--repos`. **No new efficacy read** — deferred `[production]` `resolved_rate` A/B (plan vs model) is the resolver |
| 2026-07-13 | KB fair-eval Phase 1 + Phase-2 scout | `[proxy]` | harness fix validated + confound **Δ−0.10** file@1, but `resolved_rate` inconclusive (0 floor); scout → only **~7–15** crash-with-fix cases fleet-wide ⇒ KB verdict **production-gated** |
| 2026-07-11 | functional 10-case e2e (GEI) | `[production]` | match recall@1 **7/10**, localize **7/10** file@5, fix ungradeable (empty worktree) |
| 2026-07-10 | functional-bug matching arm | `[proxy]` | functional/dispatch recall@1 **0.68** vs flood 0.32; dispatch **0.94** on crash (no regression) |
| 2026-07-10 | component-routing match | `[proxy→production]` | flood 0.32 → component **0.49/0.92** `[proxy]`; **0.10 → 0.50/0.90** `[production]` |
| 2026-07-09 | android log-match v2 | `[proxy]` | attribution recall@1 flood 0.48 → faultslice 0.86 → routing **0.94**; frame@1 0.88; decoy-robust |
| 2026-07-07 | plan-format fix stage (Phase 3) | `[proxy]` | plan emits grounded plan recall@1 0.48/@5 0.68; raw KB **hurts** (Δ−0.14); fabrication 0.0 |
| 2026-07-07 | claim-centric KB (Phase D) | `[proxy]` | retain-loop validated **0/60** claims; no-injection 0.51 > placebo 0.37 > raw Skills 0.22 |
| 2026-07-06 | first cross-stage evaluation | `[proxy]` | match recall@1 **0.60** synth / 0.02–0.23 real; localize 0.85@1 (oracle repo); fix/KB gated |
| 2026-07-05 | first atlas build + synth-log real testing | `[proxy]` | full 9-repo atlas built; synth-log recall@1 **0.60** (Φ₁ +0.31) vs real-mined text **0.02**; size-bias quantified |

---

## 2026-07-18 · Localize recall — Phase-1 mechanical fixes · `[proxy]`

Shipped the Phase-1 mechanical layer of the recall-first localize redesign
(`docs/superpowers/specs/2026-07-17-localize-recall-cascade-design.md`, **Option B**): make the
`--localize rerank` bge-m3 vector lane provably fire and fail **LOUD**, and split CamelCase identifiers so a
plain-word query can match a compound symbol. All opt-in Candidate, `core/` + atlas-schema **zero-diff**,
full Type-1 suite green (**718**). Commits `084252a`, `54aae79`, `5c89bfc`, `19cc853`, `5457e77` (merged to master).

- **Why the re-scope:** the prior pool-widening experiment ran with the vector lane **silently OFF**
  (`_build_embedder()` returns `None` when `KLOOP_EMBED_BASE_URL` is unset; `_gen_hits` swallowed live embed
  errors with `except: pass`) — so its "retrieval is exhausted" conclusion was measured on a mis-wired config.
  A first-principles review (5-frame panel) re-scoped the work: **Localize is necessary as a *concept*, not as a
  *hard gate* (verified: `workflow.py:35` hands fix the full worktree — the gate is a fix-adapter convention) nor
  as a *file@1 target* (the loss is recall, not mis-ranking). Its real job is recall.**
- **A1 — vector-lane hardening (the read):** isolated file@k on the ORACLE repo (match-independent), n=108
  `mine74` prose tickets, on `atlas-6-doc.db` (has vectors), live bge-m3:

  | arm | file@1 | file@3 | file@5 |
  |---|---|---|---|
  | `atlas` (FTS5 keyword floor = lane **OFF**) | 0.075 | 0.203 | 0.244 |
  | `rerank_pool` (hybrid bge-m3∪FTS5 = lane **ON**) | 0.084 | 0.202 | **0.267** |

  The lane now **provably fires** (numbers diverge from the floor — the exact bug A1 fixed), but its *standalone*
  lift is **modest** (+0.009 file@1, +0.023 file@5). Consistent with the design: the vector lane is **not** the
  lever — the grounded LLM judge (**0.212** file@1 in the 2026-07-16 read) and the deferred literal-anchor +
  CamelCase tiers are. **A1's primary value is correctness** — a rerank scorecard can no longer silently reflect a
  dead vector lane (`--localize rerank` now `return 2` / raises without an embedder; per-case embed failures
  counted into the manifest `localize_embed_failures`).
- **A3 — index-time CamelCase (`KLOOP_INDEX_CAMELCASE`, default OFF):** mechanism **Type-1-proven**
  (`screenshot`→`ScreenshotUtils` findable with the flag ON; byte-identical atlas with it OFF; the shared
  `split_identifier` also fixed a query-side match-noise regression caught in adversarial review — bare-digit /
  single-char sub-words are filtered out of the FTS query). Efficacy A/B needs a re-indexed atlas + a
  **match-regression check** (index-time expansion changes the *shared* atlas) — **deferred** to the runbook.
- **Governance:** Phase-1 is Core-*safe* hardening (the Core-default localize is unchanged; rerank + the CamelCase
  atlas stay opt-in Candidates). Promotion to Core still needs the `[production]` GEI localize file@k read with the
  lane ON. **Deferred / next:** Phase 2 (literal-anchor cascade + RRF union + abstain), Phase 3 (soft-gate fix),
  the benchmark re-point (`bug_kind` split + `localize_hit` counter), and the `[production]` read + A3
  CamelCase-atlas rebuild + match-regression.

## 2026-07-16 · CodeWiki + CBM in localize & fix — full A/B · `[proxy]`

Fully enabled CodeWiki (per-module LLM docs) + CBM (code-graph) in the localize reranker
(`--localize rerank`, grounded LLM file-judge over a CodeWiki-enriched pool) and the fix prompt
(`--fix-context {codewiki,cbm}`), then measured both. NEW substrate: a 6-repo doc atlas
(`atlas-6-doc.db` — repos 6, units 96,654 incl. **9,665 doc units**; atlas-9.db had 0) + doc→source
`entity_maps` (`gloop bridge`) + a live-`gh` mined slice `mine74` (108 cases / **96 fix-gradeable** with
real diffs+`required_apis`, 5 repos). **Read the tags:** every number below is **isolated** (retrieve
forced onto the ORACLE repo — match-independent, an upper bound, NOT end-to-end) and on **prose
GitHub-issue tickets** (~0 logs/crash signals) — a *specific* regime, the opposite of GEI crash tickets;
adversarially verified (4 lenses, all CAVEATED — numbers reproduce, no measurement bug).

- **LOCALIZE — CodeWiki *narrows* the rank-1 gap, and only via the LLM judge (isolated ceiling, n=108):**
  atlas FTS5 **file@1 0.075** → hybrid pool 0.073 → +CodeWiki-in-pool 0.074 (both ≈0 at rank-1) →
  +LLM judge / no CW **0.157** → +CodeWiki-under-judge **0.212** (+0.137 abs, 2.8×; file@5 0.235→0.384).
  The **judge is the bigger lever (+0.083)**; **CodeWiki-under-judge adds +0.056 file@1 / +0.108 file@5**
  on top — but the toggle (`entity_map`) changes *both* the candidate pool (doc→source files) *and* the
  judge's context block, so it is CodeWiki **pool+context entangled**, not context alone. +0.056 ≈ 6 net
  cases on n=108 (borderline at rank-1; the +0.108 file@5 is the more robust signal). Winning arm still
  gets rank-1 right only ~21%. Cost ~$0.0014/case. **Regime caveat:** on these 0-signal tickets
  candidate-gen falls back to `ticket.summary` and the judge ranks on prose — transfer to log-bearing
  crash tickets (where code-token candidate-gen drives the pool) is untested. `gloop grade-run --index`
  reports only the judge-*less* pool (~0.074); the 0.212 needs a live `gloop run --localize rerank`.
- **LOCALIZE — CBM marginal:** disjoint 26-case subset, +CBM file@1 **+0.038** (0 at file@5) — within noise.
  Live call-graph context adds no measurable localize benefit beyond CodeWiki+judge.
- **FIX — no measurable fix-context effect (underpowered floor substrate; n=29, CodeWiki-only):** stock
  `gloop fixeval` can't reach the fix stage here (prose tickets → match scores 0 → 100% abstain at the
  gate), so a forced-repo (`base=fix_sha^`) + forced-oracle-localization harness isolated the fix-prompt
  effect. **CBM never fired** (0/31 cases had any CBM symbol — empty signals) ⇒ the arm is CodeWiki-only,
  CBM **untested**. Baseline resolved 1/29 vs +CodeWiki 0/29; patch_apply 0.27→0.23 — one ~2-case coverage
  flip cascading through nested metrics, within LLM sampling noise (data consistent with *no* effect). The
  plan fixer rarely reproduces exact PR fixes (resolved floor ≤1/29). Consistent with the prior KB
  re-verdict ("real-crash-with-fix substrate needed"; distrust-unverified-context).
- **Governance:** `--localize rerank` (+CodeWiki, judge) → promotion **Candidate** — the first `[proxy]`
  file@1 lever — but the evidence is a *single, isolated, OSS, prose-ticket* read; the promotion gate is a
  `[production]` **crash-ticket** file@1 read + an e2e (match-gated) confirmation. `--localize rerank +CBM`
  and `--fix-context {codewiki,cbm}` stay **OFF** (no measurable benefit / untested). Follow-up to
  disentangle CodeWiki pool-vs-context: add a `judge + doc→source pool but no wiki-context` arm. Incidental
  tooling: fixed a CodeWiki produce crash on name-colliding module trees (commit `1277e9f`; cameraview
  0→52 md) — not in mine74, so it backs **no** efficacy number.

## 2026-07-15 · `--localize tokens` (signal-aware FTS5) 3-arm A/B · `[proxy]`

`--localize tokens` = the "keep only the winner" distillation of the prior fix: a `SignalQueryIndex`
that queries `code_query(signals)` (extracted code tokens, fallback prose summary) — NO semantic branch,
NO embedder (pure FTS5). Same 212 `functional-clean` cases, isolated + canonical grading, added as a
third arm to the 2026-07-14 A/B below.

- **Overall isolated `file@1`: atlas 0.010 · dispatch 0.161 · tokens 0.166 `[proxy]`** (`file@5`: 0.019 /
  0.209 / 0.198). tokens ≈ dispatch on `file@1` **but needs no gateway embedder.**
- **Per class `file@1`:** carplay 0.000 / 0.494 / **0.494** (tokens == dispatch — both FTS5-tokens);
  ui_text 0.014 / 0.000 / **0.014** (tokens ≥ dispatch — falls back to atlas-summary, not the worse
  semantic branch); audio 0.017 / 0.001 / 0.000 (all ~0, no fault-class token).
- **Verdict:** the bge-m3 **semantic branch adds an embedder dependency + complexity for NEGATIVE
  `file@1` value** — `tokens` equals dispatch's win, is ≥ per class, and is pure FTS5. **`--localize tokens`
  was the default candidate → **PROMOTED 2026-07-15 to the Provisional-Core default** (§ next entry above; no-embedder ⇒ a viable Core default) pending a `[production]`
  GEI read. Artifacts: `/home/vinc/gl-eval/loca-ab2/` (`run-tokens`/`grade-tokens.json`).

---

## 2026-07-14 · localize dispatch prod-fixes A/B (Bugs 1/2/3) · `[proxy]`

After the `[production]` INERT read (below), fixed all three bugs (branch `localize-dispatch-prod-fixes`):
Bug 1 = frame-evidence discriminator (`methods`/native-`symbols` ⇒ crash, else functional — fires even
when a logcat fills `classes`); Bug 2 = the crash/FTS5 branch queries the extracted code tokens
(`code_query`) not the summary; Bug 3 = grading `canonical_path` reconciles source-root prefixes.
Re-ran the A/B on the **representative** substrate — all 212 `functional-clean` cases (74 `ui_text` +
69 `audio` + 69 `carplay`; carplay/audio carry logcats), `--match-arm flood`, isolated + canonical grading.

- **Overall isolated `file@1` 0.010 → 0.161 (+0.151), `file@5` 0.019 → 0.209 `[proxy]`.** Routing: audio+ui_text
  (146) → semantic; carplay (66) → crash-FTS5(tokens).
- **The win is ENTIRELY Bug 2.** Per-class `file@1`: **carplay 0.000 → 0.494 `[proxy]`** (log carries the
  fault class in an `at …(` frame → `code_query` includes it → FTS5 exact-matches — the extracted-tokens
  lever), audio 0.017 → 0.001, ui_text 0.014 → 0.000 (**semantic branch neutral-to-negative** — bge-m3 on
  symptom prose retrieves the neighborhood, not rank-1).
- **Verdict:** Bug 2 (code-tokens-in-FTS5) is the file@1 lever — it fires on all real **crash** tickets
  (stacks name the fault class) and carplay-shape functional tickets. The **semantic routing (Bug 1) does
  not earn its place** at file@1. Recommend: promote tokens-in-query to the **default** localize; demote/drop
  the semantic branch. Caveat: carplay 0.494 is synth-inflated (fault class planted in the log) but realistic
  for real crash stacks. GEI re-run is the `[production]` resolver (the tested GEI cases were *functional* — the
  fix helps them only if their logcats carry fault-class frames). Artifacts: `/home/vinc/gl-eval/loca-ab2/`.

---

## 2026-07-14 · functional localize dispatch — `[production]` INERT (proxy was non-representative) · `[production]`

**⚠ Correction (production read).** A GEI `[production]` run scored `--localize dispatch` at **`file@1 = 0/10`**
and a code-verified RCA shows why: under the production default `--match-arm component`, the extractor is
`ComponentExtractor(AndroidSignalExtractor())`, which **never sets `PROSE_MARK`** and fills `signals.classes`
from the ticket's logcat — so `is_functional_localize` always returns `False` and every ticket routes to FTS5.
**The bge-m3 branch never engages in production; `--localize dispatch` ≡ `--localize atlas` there.** The
proxy A/B below is real but **non-representative**: it used prose-only (`logs=[]`) cases, the one shape where
the discriminator fires. Two more confirmed bugs: (2) the localize query is `ticket.summary` only
(`core/workflow.py:33`), so the strong log-extracted code tokens in `signals` are wasted — likely the real
file@1 lever, fixable via the stateful adapter (no `core/` edit); (3) grading `norm_path`
(`fix/patch.py:74`) + exact `recall_at_k` don't reconcile module-prefix differences (`app/src/main/java` vs
`src/java`), so rank-1 hits score as misses (production number understated). Fix order for file@1:
**(3) grading → (2) signals-in-query → (1) fault-frame-based routing.**

### (superseded) proxy A/B — prose-only, non-representative

First measured read of `--localize dispatch` (`LocalizeDispatchIndex`; merge `1493c5d`). Substrate: 74
**prose-only** (`ui_text`, empty-log) functional cases from `functional-clean` (owners span all 9 repos),
run over `atlas-9.db` with `--match-arm flood --fixer canned`; graded on the **isolated** diagnostic
(retrieve on the ORACLE repo, query = `ticket.summary`, so match error is removed). This is the exact
no-anchor population dispatch targets (`is_functional_localize=True` verified — anchorless signals route
to the bge-m3 branch); audio/carplay cases were excluded because their logs make them anchored → FTS5 in
both arms (would dilute the signal).

- **atlas (FTS5, baseline):** isolated `file@1` **0.014**, `file@3` 0.014, `file@5` **0.014** `[proxy]` — FTS5
  over symbol names is ~useless on symptom prose (pulls wiki `.md` + lexically-adjacent-but-wrong files);
  reproduces (and sharpens, on pure prose-only) the `1/10` `file@1` GEI pathology.
- **dispatch (bge-m3):** isolated `file@1` **0.000**, `file@3` 0.006, `file@5` **0.035** `[proxy]` — **+0.021
  file@5 (~2.5×), but no file@1 gain** (−1 case at rank-1). Qualitatively the semantic branch retrieves the
  right *neighborhood* (topically-relevant files, right package) but rarely the exact file at rank-1.
- **Verdict:** confirms the spec §7 prediction — **vector-alone lifts recall (@5), not rank-1 precision (@1).**
  The goal was `file@1`, so dispatch **stays Candidate, NOT promoted** to a default on this read. Mechanism
  works (routing verified, honest `isolated_arm` attribution); the missing piece is a **reranker over the
  semantic pool** (staging option **C**: hybrid RRF + LLM rerank). B (signal-tokens query) is inapplicable
  here — prose-only cases carry no log tokens. Both arms are near-zero at `file@1`, so prose-only functional
  localization remains a genuinely hard open problem. Artifacts: `/home/vinc/gl-eval/loca-ab/`.

---

## 2026-07-14 · KB rename `Claim`→`Knowledge` + Lane-A removal · governance (no efficacy read)

A naming + surface correction on branch `skill-to-knowledge-rename` (no `core/`/schema edits). The KB read
backwards in the docs (a `Skill` was both the raw input *and* a produced output); corrected so a **`Skill` is
input-only** (raw feedstock) and the distilled, injectable unit is **`Knowledge`** (renamed from `Claim`):
`kb/claim.py`→`kb/knowledge.py`, `ClaimRegistry`→`KnowledgeRegistry`, `render_claims`→`render_knowledge`,
`--claims`→`--knowledge`, `claims.json`→`knowledge.json`, `FixRecord.fired_claims`→`fired_knowledge`. **Lane A**
(the reversed lane that minted a Skill *from* cases — `kb/harvest/`, `kb/distill/`, its `gloop` CLI driver,
the `--skills distilled` arm and its `.toml` output artifact) was **deleted**; the raw-Skill baseline arm (`--skills
none|mock|kb|placebo`) is retained as an explicit undistilled control. `gloop kb-ab` was **retargeted** to gate
on distilled **Knowledge** (candidate floor) via `FixEvalRunner(knowledge=...)` — an empty `knowledge.json`
keeps every arm byte-identical to `none` (honest cold-start).

**No efficacy change.** This is a vocabulary + surface correction, not a measurement; historical `[proxy]`
numbers are unchanged. The KB remains **Candidate/unproven** ([[kb-reverdict]]) — a fair `resolved_rate`
verdict still needs a real-crash-with-fix production substrate.

---

## 2026-07-13 · labs arms run-reachable + functional-arm proxy A/B · `[proxy]`

The experimental Candidate arms were wired into `gloop run` (branch `labs-arms-profile`, merged): selectable
`--match-arm {semantic,judge,functional,dispatch}` + `--localize semantic` (via `SplitIndex`) + a
`KLOOP_LABS` / `--profile labs` per-environment switch that flips run defaults to the experimental stack **only
where enabled** — the Core default (`component`/`atlas`/`plan`) is unchanged unless labs is on (locked by
`tests/run/test_core_defaults_unchanged.py`). No `core/` / schema edits.

Then the functional arm's repo-text profile was built (`gloop build-textprofile` → `gl-eval/textprofile-9.db`,
bge-m3, 992 units across the 9 fleet repos) and the first proxy A/B run end-to-end through the run-reachable
arm — `gloop funceval --dataset functional-clean (212 functional-bug cases, `bug_kind=functional`)
--profile-db textprofile-9.db --index-db atlas-9.db --arms functional,dispatch,flood,faultslice,routing`:

| arm | recall@1 | recall@3 | coverage | acc@answered | Φ₁ |
|---|---|---|---|---|---|
| **functional** | **0.68** | 0.79 | 0.58 | 0.83 (CI 0.75–0.89) | 0.39 |
| dispatch | 0.68 | 0.79 | 0.58 | 0.83 | 0.39 |
| flood (baseline) | 0.32 | 0.58 | 0.30 | 1.00 | 0.30 |
| faultslice / routing | 0.01 | 0.18 | 0.00 | — | 0.00 |

**functional 0.68 vs flood 0.32 (+0.36, 2.1×)** on functional bugs — reproduces the 2026-07-10 result via the
freshly-built profile + the run-reachable arm. `dispatch == functional` on pure-functional data (its router
only diverges when crash signals are present, which this dataset lacks). The crash arms (faultslice/routing)
collapse to ≈0.01 — they need crash signals functional/UI bugs don't carry. flood's higher acc-when-answered
(1.00) is a small-denominator artifact: it abstains on 70% of cases; functional answers on 58% at 0.83 and wins
on **both** forced recall@1 and Φ₁. Stays **Candidate** — promotion to Core needs a `[production]` read on real
GEI functional tickets. Artifact + run: `gl-eval/{textprofile-9.db, funceval-functional-ab.json}` (dev-box).

## 2026-07-13 · KB fair-eval Phase 1 — metric+injection fix · `[proxy]`

Re-test after finding the KB's "Archived null" was measured on the wrong outcome (`plan_target_recall`, not
`resolved_rate`) and confounded by localize-query pollution. Phase 1 made resolution gradeable (synth plants a
headroom-clean `required_api`, named in the skill guidance, into 6 crash classes) and added `gloop fixeval
--skills-inject fix-only` (KB into the fix prompt only). A/B: `none` / `kb·fix-only` / `kb·both`, 34-case
gradeable slice (oboe/antennapod/newpipe/dlt-daemon), `--fixer direct`, deepseek, ~$0.10.
- **Harness fix validated:** `resolved_rate` now defined (`n_gradeable=34`); `fix-only` is provably
  localize-invariant on real data — `none` and `kb·fix-only` have **identical** `file_recall@1` (0.157=0.157).
- **Confound confirmed + quantified:** injecting skills into the localize query (`both`) **degrades**
  localization by **Δ−0.10 file@1** (0.157 → 0.054) — much of what the 2026-07-07 "raw KB HURTS" was actually
  measuring (retrieval pollution, not guidance quality). `fix-only` removes it.
- **KB fix-value INCONCLUSIVE:** `resolved_rate = 0.0` in **every** arm — the fix loop abstained on ~all 34
  cases (weak summary-localize ≈0.16; patches don't apply). No resolution headroom → the KB can't be
  discriminated. Root cause: a **synthetic** crash log is disconnected from the real PR fix, so the model
  can't reconstruct a resolving patch — synth is valid for matching/localization but the **wrong substrate
  for `resolved_rate`**.
- **Verdict:** the Archived null is **discredited** (confound + wrong metric, both reproduced) but the KB is
  **not vindicated** (zero positive signal) → **unproven**. KB reclassified **Archived → Candidate**. Branch
  `kb-fair-eval-phase1` (merge `20f6934`); spec/plan `docs/superpowers/{specs,plans}/2026-07-12-kb-fair-eval-phase1*.md`.
- **Phase-2 scout (same day, offline):** Phase 2 needed a *real* crash-with-fix substrate (issue with a
  stacktrace → KB fires; merged PR → resolution achievable). Scanned the mined fleet datasets: only **7**
  genuine crash-report+fix cases in `dataset-full` (261), **15** in `dataset-neg` (643) — the OSS proxy repos
  are features/UI/usage, not AAOS crashes (bodies un-truncated, up to 23k chars, so the count is real). Too
  few for a `resolved_rate` verdict. **Conclusion:** every dev-box substrate is exhausted (synth: 0
  resolution; OSS-real: ~no crashes), so the KB verdict is **production-gated** — it needs real AAOS crash+fix
  tickets. The Phase 2 spec now stands as a **production-side** task. (Same lesson as efficacy: the proxy
  can't measure it.)

## 2026-07-13 · Production-Core defaults + loop closure (11-task branch) · governance / plumbing (no efficacy read)

An 11-task branch (`prod-core-defaults-loop-closure`) that promotes the fix default, closes the feedback loop's
data plane + reporting edge on the dev box, and prunes the production surface. **This is plumbing + governance,
not a new efficacy read — there are NO new `[proxy]`/`[production]` numbers here.**
- **Bug Plan Mode → Provisional-Core default:** `gloop run --fixer plan` (the `PlanningFixEngine`) is the new
  default; `--fixer` is now `canned|model|plan` (+ a `--max-replan` flag); the fail-closed guard now covers
  `model` **and** `plan`. Its proven merit is **safety** — the engine re-gates its *executed* diff against the
  localize candidate set and **abstains** rather than emit an out-of-scope/ungrounded patch
  (`fabrication_rate = 0.0` `[proxy]`), a charter-aligned ("grounding over narrative") default. Its
  **effectiveness is NOT proven**: `resolved_rate` was never gradeable (`[proxy]` only). The **deferred
  `[production]` `resolved_rate` A/B (plan vs model)** is the follow-on that resolves Provisional-Core → Core or
  revert (grade-run emits the promotion-eligibility note).
- **Data plane closed:** a `RecordingExtractor` sidecar captures the loop's `signals`; the run-record now
  persists `signals`/`cost_usd`/`tokens`/`model_calls`/`fixer`; each batch writes a provenance `manifest.json`
  (timestamp, atlas identity, `match_arm`, `fixer`, affinity hash, produce+embed model pins, `change_sink=mock`,
  `n_cases`). Plan/patch primitives were relocated `fixeval/` → `groundloop/fix/` (Core decoupled from Dev-Labs).
- **Reporting edge closed:** `grade-run` cards carry per-case `predicted_repo`/`oracle_repo`/`signals`/
  `cost_usd`/`fixer`; `grade-run --compare <prev-card>` emits a per-stage improved/flat/regressed verdict + a
  `.compare.json` sibling; grade-run prints reporting-only promotion-eligibility notes.
- **Surface pruning:** a `KLOOP_DEV` dev-gate rejects `--index`/`--fixer canned`/`--case` in production
  (reachable only with `KLOOP_DEV=1` or the hidden `--dev`; the Type-1 suite arms it via an autouse fixture);
  the `--repos` guard was hardened from presence-only to verifying catalog snapshots actually exist.
- **Verification:** 608 passed / 7 skipped, ruff clean; `core/` + atlas schema zero-diff. Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-13-production-core-defaults-and-loop-closure*.md`; branch
  `prod-core-defaults-loop-closure`.

## 2026-07-11 · functional 10-case e2e (GEI) · `[production]`

First full 8-stage `gloop run` over the 10 functional GEI cases (19-repo atlas, 126,919 units; affinity from
1,169 JIRA↔Gerrit pairs). All 10 ran every stage to a bound change, 0 crashes.
- Match recall@1 **7/10 `[production]`** (per-case table; run summary read 8/10 — reconcile against raw scorecard).
- Localize **7/10 file@5 `[production]`**, **1/10 file@1 `[production]`** (measured on the oracle repo via `AtlasIndex.retrieve` = **plain FTS5 keyword search**; the bge-m3 vector / qwen-rerank paths are eval-only, not wired into `run_ticket`).
- Fix **0/10 `[production]`** — **ungraded, not a fix failure**: empty worktree (no corpus checkout for any owner), so `ModelPatchEngine` fabricates paths.
- Takeaway: the mined affinity prior generalizes to unseen tickets; misses are label≠owner (13363) + CarPlay Core-vs-Integration near-tie, both needing signal beyond the `component` field. Highest-value unblock = check out the 4 owner repos so fix is gradeable.
- detail: `docs/2026-07-11-functional-10case-e2e-findings.md`

## 2026-07-10 · functional-bug matching arm · `[proxy]`

5-arm A/B (`functional`/`dispatch` vs v2 crash arms) over a 212-case no-crash functional dataset + the 196
crash cases, on the 9-repo `atlas-9.db`.
- Functional attribution recall@1 **0.68 `[proxy]`** (Φ₁ +0.39) vs flood **0.32 `[proxy]`** — text-primary (ticket title+desc → bge-m3 repo-text profile) more than doubles it; v2 crash arms correctly abstain (0.01, coverage 0.00) on no-crash tickets.
- `dispatch` (per-case router) = **0.94 `[proxy]`** on crash == routing 0.94 — no regression — and 0.68 on functional: one arm, both classes.
- Caveat: 100% answerable, so honest-refusal negatives untested here; proxy is optimistic — real recall is production's number. Component routing dropped (JIRA `component` deemed unusable).
- detail: `docs/2026-07-10-functional-bug-match-findings.md`

## 2026-07-10 · component-routing match · `[proxy→production]`

An empirical JIRA-component→repo affinity prior as a loop-blind, scale-invariant (RRF) re-ranker with honest
leave-one-out; built + mechanism-checked on the proxy, efficacy owned by production.
- Proxy: flood 0.32 → component **recall@1 0.49 / recall@3 0.92 `[proxy]`** on the 212-case functional proxy.
- Production: ticket-text collapses to **recall@1 0.10 `[production]`** (size bias); the affinity prior lifts it to **0.50 / 0.90 `[production]`** — the dominant Stage-1 lever, at zero token cost.
- Takeaway: the RRF version lands on the production shape where the additive-raw form (0.58/0.83 `[proxy]`) would not; LOO proven load-bearing on rare pairs. Follow-up: abstention recalibration (Φ₁≈0); within-component recall@1 needs a non-size-biased base.
- detail: `docs/2026-07-10-component-routing-findings.md`

## 2026-07-09 · android log-match v2 (fault-localization + attribution) · `[proxy]`

3-arm A/B (`flood` → `faultslice` → `routing`) on a real 196-case long-logcat faultlog dataset over
`atlas-9.db`; fully deterministic (no gateway, no LLM, no cost).
- Attribution recall@1 flood **0.48 `[proxy]`** → faultslice **0.86 `[proxy]`** → routing **0.94 `[proxy]`** (clean): isolating the fault site before matching nearly doubles it.
- Decoy-robust: under hard decoys flood drops **0.48 → 0.32 `[proxy]`**; faultslice/routing unchanged (0.86/0.94) — the design removes the failure mode.
- Fault localization frame@1 **0.88 `[proxy]`** / frame@5 0.95; log-quality audit clean (0/187 owner-leak in noise → attribution earned).
- Caveat: `no_fault=9` are all the oboe audio-underrun class (a silent-behavior bug, the deferred second problem); internal validity only — real AAOS logs are the external test.
- detail: `docs/2026-07-09-android-log-match-v2-findings.md`

## 2026-07-07 · plan-format fix stage — Phase 3 A/B · `[proxy]`

Live A/B on a 56-case correct-match slice (oboe+dlt-daemon natives, ext4-staged) answering the two questions
the plan format was built to settle.
- Engine A/B (direct vs plan): a **structural tie** on the only shared gradeable metric (`file_recall@1`, fixer-invariant); the plan arm uniquely emits a grounded, zero-fabrication repair plan (**recall@1 0.48 / @5 0.68, groundedness 0.56 `[proxy]`**). Hard resolution verdict blocked on synth cases with `required_apis`.
- KB-under-plan: raw 12-Skill KB **HURTS** — `plan_target_recall@1` **0.36 → 0.22, Δ −0.14 `[proxy]`**; ordering **plan/none 0.48 > placebo 0.36 > kb 0.22 `[proxy]`**. Fabrication 0.0 across all arms.
- Takeaway: an independent reproduction of the claim-KB §8 verdict — no-injection beats placebo beats raw Skills.
- detail: `docs/2026-07-07-plan-format-phase3-findings.md`

## 2026-07-07 · claim-centric KB — live preview + Phase D · `[proxy]`

Claim-centric distilled KB run live on the real substrate (atlas-9.db, deepseek gateway): `kb-extract` →
per-claim inject → archive → score → compare.
- Extraction + ground-check work: 12 Skills → **60 grounded claims `[proxy]`**, the deterministic gate correctly drops ~14 ungrounded proposals ("LLM proposes, gate disposes").
- Phase D (unbounded, two disjoint windows, oboe+dlt-daemon): retain-loop validated **0/60 claims `[proxy]`** (all `lofo_delta=0`, none load-bearing; 4 retired). With validated set empty, **no-injection 0.51 > placebo 0.37 > raw 12 Skills 0.22 `[proxy]`** (`plan_target_recall@1`) — the messy Skills injected wholesale hurt the planner most.
- Takeaway: distill-first / distrust-unverified design empirically vindicated. Also surfaced the portable ext4 fixeval-materialization fix (stage `--repos` off ext4). Caveat: small slice, no `required_apis` → resolution ungradeable.
- detail: `docs/2026-07-07-claim-kb-preview-findings.md`

## 2026-07-06 · first end-to-end cross-stage evaluation · `[proxy]`

First grounded whole-loop eval on the 9-repo fleet (`atlas-9.db`, 475k units) over `dataset-synth` (212) +
`dataset-full` (261 real mined logs); loop runs oracle-blind, grading offline.
- Stage-1 match recall@1 **0.60 `[proxy]`** synth (Φ₁ +0.31); on real mined logs the membership matcher collapses to **0.02 `[proxy]`**, semantic recovers to **0.23 `[proxy]`**. Match is the bottleneck; size-bias (small repos lose rank-1 to giants) is the dominant error.
- Localize strong but unscored by the harness: **file_recall 0.85@1 / 0.94@5 `[proxy]`** given the oracle repo; e2e drops to **0.53@1 `[proxy]`** almost entirely from match error (cascade).
- Fix engine real + wired (loop completes, change bound) but quality **GATED** (proxy `resolved_rate`, no test exec); KB fires on 55% with valid placebo but lift **GATED**; honest-refusal built but 0 negatives in the eval sets. Submit/bind are mocks.
- detail: `docs/2026-07-06-first-evaluation.md`

## 2026-07-05 · first atlas build + synth-log real testing · `[proxy]`

First real `gloop eval` over the full 9-repo live atlas (build-substrate gotchas → `docs/build-setup.md`).
- **Synth-log real testing** (AAOS logcat/backtrace tickets naming the owner's real crash-site symbols from
  the atlas): `membership+logs` recall@1 **0.60 `[proxy]`** (Φ₁ +0.31, recall@3 0.80) vs `membership+text`
  **0.02 `[proxy]`** — **logs, not prose, are the signal.** Mined GitHub issues are signal-sparse: only
  **14% (27/187)** carry code signal, so the loop should abstain on empty signals, not force-pick.
- **Size-bias quantified:** native repos with a unique `.so` win outright; small Java repos have the answer
  but lose rank@1 to giants (the recall@1→@3 gap 0.60→0.80 IS the size tax) — the finding that motivates the
  component-routing prior.
- **A naive IDF `log(N/df)` size-fix was REFUTED and reverted** (grounding over narrative): `store._fts_query`
  OR-expands camelCase into generic sub-words → high df → idf≈0 → all repos tie (signal-bearing recall@1
  0.17→0.00). A size-fix must account for sub-word expansion; `rank_repos` is an SP1b dep — coordinate.
- detail: `docs/type2-atlas-build-findings.md` (git history)
