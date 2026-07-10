# Functional-Bug Matching Arm — Design Spec (2026-07-10)

## 1. Charter & situation

This is the sanctioned **"second problem"** that Android Log Match v2 explicitly deferred
(`docs/superpowers/specs/2026-07-09-android-log-match-v2-design.md:28` — *"No ticket-text-primary matching,
no JIRA-component routing, no source-code UI-string index. Deferred to a later spec."*). It is that later
spec.

**Goal (user directive, 2026-07-10):** *be capable of solving functional bugs* — **wrong UI text, audio
issues, and CarPlay / projection connection failures** — the no-crash classes the fault-based matcher is
structurally blind to. The objective is genuine attribution capability on these classes, not passing a
proxy number.

**Our situation (the framing to hold at the center of this work):**
- The real validation surface — the **10 GEI cases** and the **406-case oracle** — lives **only in the
  production environment**. We have no access to it; neither "GEI" nor "406" exists in this repo. We can
  only **develop against the feedback production returns**.
- **Production is the oracle of record.** The OSS proxy (unscrubbed fleet, `atlas-9.db`, the same pattern
  v2 used) is the **development + regression harness**. The loop is: build on the proxy → ship → production
  runs it on the real 406/GEI → feeds numbers back → we iterate.

**The failure mode, quantified by production feedback:** on the 10 GEI cases `FaultSignalExtractor`
returned `no_fault_found` on **8/10** (no crash frame to anchor on); the v2 routing table had **zero
coverage** (it keys on crash-stack namespace/SONAME tokens absent from no-crash tickets); the `flood` arm
occasionally landed the right repo in the top-3 but **large noisy repos consistently outranked it** (the
unmitigated size-bias). v2 did not regress — it hit exactly the class it deferred.

## 2. Non-goals (YAGNI)

- **No JIRA-component routing.** Confirmed with the user (2026-07-10): the JIRA `component` field is *not
  usable even in production* (empty/noise). We build **no** component→repo table and do **not** seed from
  `owner_tokens.py`. The arm is text-primary. (`Ticket.component` remains an unused frozen-schema field.)
- **No source-code UI-string index.** Matching against `strings.xml` / layout text across the fleet is a
  larger sub-project; deferred.
- **No atlas schema change and no full 12 GB atlas rebuild.** The text backend is a new *lightweight*
  per-repo profile store (§5), not a re-index of `atlas-9.db`.
- **No 406-case oracle built locally.** Production owns it. The proxy gets a *modest* labeled functional
  slice (§9); the crash half already exists (v2's 196 faultlog cases).
- **No edits to frozen or coordination-gated surfaces** (§11).

## 3. Architecture — a frozen-safe bolt-on arm

The functional arm is a new `(extractor, index)` pair plus a calibrated abstain threshold, composed at the
CLI root (`cli/__init__.py`). It rides the existing `Arm` seam (`groundloop/eval/arms.py:12`) exactly like
v2's `flood/faultslice/routing`. **Zero edits** to `core/`, `EvalRunner` (`eval/runner.py:31`), or
`AtlasIndex.rank_repos` (`adapters/index/atlas.py:17`).

Data flow, per case (unchanged runner loop):
```
ticket ─► FunctionalTextExtractor.extract(logs, ticket) ─► Signals(prose-query + optional log tokens)
       ─► FunctionalTextIndex.rank_repos(signals, catalog) ─► [RepoScore]  (text-cosine ⊕ optional-log RRF, UNION)
       ─► decide(ranked, τ_margin, τ_score) ─► predicted repo | ABSTAIN
```

The primary **capability** ("solve") path is a per-case **dispatch** composite (§8) that sends
crash-anchored tickets to v2's fault arms and no-crash tickets to the functional arm — mirroring how
production would route.

## 4. The functional signal extractor

`groundloop/domains/android_ivi/functional_signals.py` — `FunctionalTextExtractor.extract(logs, ticket)
-> Signals`.

Responsibilities:
1. **Use `ticket.summary` AND `ticket.description`.** Today `AndroidSignalExtractor`
   (`signal_extractor.py:24-25`) reads `description` only and ignores `summary` (the JIRA-title analog) —
   a primary reason functional cases fail. The functional extractor builds a normalized prose query from
   `summary + "\n" + description` (lowercased, whitespace-collapsed; light stopword trim; identifiers and
   quoted UI strings preserved verbatim).
2. **Carry the prose through the frozen `Signals` token-bag.** `Signals` (`core/types.py:23`) is frozen and
   has no free-text field, and `rank_repos` receives only `Signals` (never the `Ticket`). Convention for
   this matched extractor/index pair: **the normalized prose query is emitted as the single reserved
   element `Signals.symbols[0]`**; the `FunctionalTextIndex` reads that element directly as the embed query
   (this **preserves full phrase order**, unlike `' '.join(tokens())`). This reserved use is documented and
   red-tested (§10); no other index consumes this extractor's `Signals`.
3. **Optional log evidence.** If `logs` are present (audio underrun, connection/timeout), extract whatever
   code-ish tokens exist (reuse the `AndroidSignalExtractor` regexes) into their natural `Signals` fields
   (`libraries` for `.so`, `errors` for exception-ish, etc.). For a pure UI-text ticket this is empty and
   the arm runs on prose alone.

The extractor never reads `_oracle/` and never reads `ticket.component` (dropped, §2).

## 5. The lightweight repo-text index (the chosen backend)

Two pieces: a **profile builder** (offline, produces a small store) and the **index** (query time).

### 5.1 Profile builder — `gloop build-textprofile`
`groundloop/adapters/index/text_profile.py` (builder + store). For each repo in the fleet, assemble a
**text profile** from cheap, always-available, production-portable sources:
- `README*` (top-level + module READMEs),
- `build.gradle(.kts)` `applicationId` / `namespace` and Gradle module names, `AndroidManifest` package,
- module & package **identifiers** (directory/package path segments), CMake/`.so` target names,
- **CodeWiki `doc` units if the atlas already has them** (`Store.keyword_search`/`vector_search`
  `kinds=['doc']`) — a bonus when present; `atlas-9.db` has none, `atlas-enriched.db` has 4376, so the
  builder degrades gracefully.

Embed each profile with `GatewayEmbedder` (bge-m3, pinned per the reuse contract) into a **small per-repo
vector store** — a new standalone SQLite/JSON keyed by repo name (a handful of vectors per repo), **not**
the frozen atlas schema. The identical builder runs over the production fleet, so the mechanism ports with
zero change.

### 5.2 Query-time index — `FunctionalTextIndex.rank_repos(signals, catalog)`
`groundloop/adapters/index/functional_text.py`. Implements `CodeIndex` (`rank_repos` + `retrieve`).
- Embed the prose query (`signals.symbols[0]`) once via bge-m3.
- **Primary score** = per-repo **max cosine** over that repo's profile vectors, restricted to `catalog`
  (mirrors `SemanticAtlasIndex.rank_repos`, `atlas_semantic.py:37-48`). Empty query → all-zero → abstain.
- **Optional log channel** = if the `Signals` carry log tokens, get an FTS sub-rank from the base
  `AtlasIndex` and **RRF-fuse** (`engines/atlas/retrieve.py:rrf_fuse`) it with the cosine rank, **UNIONing**
  candidates so a log-token match can inject a repo that prose ranked low (the `FaultRoutingIndex`
  template, `adapters/index/fault_routing.py:26-34`).
- `retrieve()` delegates to the base index (for downstream localize).
- Output `RepoScore` names **must** string-match live catalog `RepoRef` names (resolve the
  `media3`/`androidx-media` naming inconsistency for the target catalog, per recon).

**Reuse contract:** bge-m3 pinned at build + query; profile store is separate & rebuildable; the atlas
schema is untouched.

## 6. Confidence / abstention (reused, not rebuilt)

Reuse `decide(ranked, τ_margin, τ_score)` (`eval/abstain.py:17`) verbatim — predict top-1 iff
`(top1 − top2) ≥ τ_margin AND top1 ≥ τ_score`, else abstain. The functional arm supplies its **own
calibrated `(τ_margin, τ_score)`** on the cosine/RRF scale (seed from `_TAU['semantic']=(0.05,0.0)`; freeze
after a calib-split pass). This is the mechanism that turns the `8/10 no_fault` silent misses into honest,
measurable refusals rather than big-repo guesses. Graded by the existing `phi_c`
(`eval/metrics.py:58`, honest-refusal-aware) + `abstention_recall_oof` + selective view.

## 7. Crash-vs-functional evaluation split

Add an **offline-only** `bug_kind ∈ {crash, functional}` label and report the two classes separately.

- **Oracle field:** `bug_kind` rides as an extra key in `_oracle/oracle.json` (like `is_answerable` /
  `negative_class`), **never read by the loop** (preserves oracle-blindness). Parse it in `EvalOracle` +
  `load_eval_oracle` (`eval/dataset.py:36-59`); surface it in `score_match` (`eval/scorecard.py:11-26`) as
  a per-record key, exactly as `negative_class` is surfaced.
- **Grouping:** add a `by_bug_kind` block in `grade_all` (`eval/scorecard.py:60`) that **recomputes the
  full forced (recall@k / mrr) + selective (coverage / phi_c / abstention_recall_oof) blocks per subset** —
  structurally like the `per_class` loop (`scorecard.py:94-104`) but emitting complete metric blocks (the
  cleanest implementation calls the existing forced/selective computation per subset). Functional recall is
  never diluted by crash cases and vice-versa.
- **Labeling pass:** a small offline stamp — `crash` = has a fault anchor / `fault_frame` present;
  `functional` = prose-only / no anchor. Writes `bug_kind` into existing `oracle.json` (offline artifact,
  not a frozen surface).
- **Renderer:** extend `eval/report.py:render_markdown` (and the `funceval` CLI print) to emit the
  per-`bug_kind` rows, or the split is computed but invisible.

## 8. The eval harness & the dispatch arm — `gloop funceval`

`groundloop/funceval/{arms,runner}.py` — a thin sibling of `faulteval`, reusing the shared `EvalRunner` +
`grade_all` (as `faulteval` does). `build_functional_arms(...)` wires:

- **`functional`** = `FunctionalTextIndex` + `FunctionalTextExtractor` (+ its calibrated τ) — the new arm.
- **`dispatch`** (the headline *capability* arm) = a `DispatchExtractor` + `DispatchIndex` composite that
  routes crash vs functional using a **`Signals`-only discriminator** (the index never sees the `Ticket`):
  - `DispatchExtractor.extract(logs, ticket)`: if `extract_fault_record(logs) is not None` → emit **fault
    `Signals`** (`signals_from_fault`, populating packages/classes/libraries; **no** prose slot); else →
    emit **prose-only `Signals`** (`symbols[0]=prose`, fault fields empty).
  - `DispatchIndex.rank_repos(signals, catalog)`: if the fault fields are populated → delegate to v2's
    `FaultRoutingIndex`; if only the prose slot is populated → delegate to `FunctionalTextIndex`. (Keeping
    prose out of the fault path avoids polluting the fault FTS query.)

  This is the true production "solve" behavior and yields one honest end-to-end number.
- **ablation arms** reused from v2 (`flood`, `faultslice`, `routing`) so the `by_bug_kind` table shows each
  matcher on its native class and the improvement is legible.

`run_funceval(dataset, profile_store, index_db, *, arms)` returns
`{"attribution": grade_all(..., by_bug_kind=True)}`. The CLI prints the per-`bug_kind` scorecard.

## 9. The proxy dataset (modest real slice)

The crash half already exists: v2's **196 faultlog** cases (label `bug_kind=crash`). Build a modest
**functional** half:
- **Label** `dataset-9`'s **261 functional cases** (mined real issues: `summary`+`description`, `logs=[]`)
  as `bug_kind=functional`.
- **Reclaim** the **9 audio-underrun** cases (v2's `no_fault=9`, oboe AAudio warning, no crash anchor) as
  `bug_kind=functional` — the audio seed.
- **`gloop synth --mode functional`** (`groundloop/synth/functional.py`): emit **UI-text** and
  **CarPlay/projection** cases — a prose ticket (real owner class/method named in the ticket text, drawn
  from the atlas, so it is *groundable* without a crash frame), no `fault_frame`, and an **optional**
  non-crash log (audio underrun; connection/timeout for CarPlay). Labeled `bug_kind=functional`,
  `dataset_kind=functional_unscrubbed`.
- **Functional honest-refusal negatives:** mint a handful of functional `not_a_defect` / `out_of_fleet`
  cases via the existing four-class emit pattern (`mine/emit.py:11` taxonomy) so abstention is validated on
  functional cases too (today `dataset-9` is 100% answerable → no functional abstain targets).

This is a regression/pre-validation slice, **not** a mirror of the 406. Production supplies the real
numbers.

## 10. Anti-leak invariants

The functional arm operates on the **unscrubbed-estate track** (v2 §3): real ticket prose ↔ real repo text,
the signal a triage engineer actually has. Invariants:
1. **The loop never reads `_oracle/`.** `bug_kind`, `owning_repo`, `expected_files` are offline-only;
   `bug_kind` enters `dataset.py`/`scorecard.py` only, never the extractor/index.
2. **The repo-text profile is built from public repo text**, global and case-independent — never from a
   case's oracle. Red-test the profile builder + `functional_text.py` module source for `_oracle`,
   `oracle.json`, `owning_repo`, `expected_files` (copy `tests/domains/test_repo_routing.py:21`), and a
   case-independence test.
3. **Synth functional tickets** name the owner's *real* class/method (groundable) but must not embed the
   owning-repo *name/slug* as a giveaway token; run the synth through the existing `_owner_still_wins` leak
   gate style check.
4. **Functional negatives** follow the four-class contract (`is_answerable=false`,
   `owning_repo='__NOT_A_DEFECT__'` / held-out) and never leak the owner.

## 11. Frozen / coordination-gated surfaces (do NOT edit; may READ)

- **Never edit:** all of `groundloop/core/`; the SQLite schema in `engines/atlas/store.py`;
  `AtlasIndex.rank_repos` (`adapters/index/atlas.py`); `owner_tokens.py` and `repo_routing.py` (may READ);
  `mine/` including `mine/emit.py` (add `bug_kind`/`component` via a NEW labeling/synth path or offline
  post-process, never by editing `mine/emit.py`).
- **New modules only** (composition-root wiring): `domains/android_ivi/functional_signals.py`,
  `adapters/index/{functional_text.py,text_profile.py}`, `funceval/{arms,runner}.py`,
  `synth/functional.py`, plus additive edits to `eval/{dataset,scorecard,report}.py` (the offline grader,
  not frozen) and `cli/__init__.py`.

## 12. What the proxy proves vs. what production measures

- **Proxy proves (real signal locally):** text-similarity attribution lift on functional cases
  (`functional`/`dispatch` vs `flood`); that abstention fires honestly (functional negatives); the
  crash/functional split reports cleanly; **no regression** on v2 crash arms.
- **Production measures (the scoreboard):** the true recall@1 per class on the real GEI/10 + 406, fed back
  to drive τ recalibration and profile-source tuning each cycle. Component-routing efficacy is *not*
  measured (dropped); abstention & text efficacy are proxy-checked and production-confirmed.

## 13. Metrics (acceptance)

Per arm, split by `bug_kind`:
- **`attribution_recall@1` / `@3`** (top-k predicted == owning repo) over the answerable subset.
- **`coverage`** (answered / n), **`selective_accuracy`**, **`phi_c`** (c ∈ {0.5, 1, 2}),
  **`abstention_recall_oof`** over functional negatives.
- **Headline capability check:** on the **functional** subset, `dispatch`/`functional` **recall@1
  materially exceeds `flood`** (the current baseline), and **`flood`'s size-bias failures convert to honest
  abstentions**, not wrong big-repo guesses. On the **crash** subset, `dispatch` **matches v2** (no
  regression).

## 14. Build order (phases → plan)

1. **Eval split scaffolding** — `bug_kind` oracle field + `by_bug_kind` in `grade_all` + renderer; the
   offline labeling pass; label `dataset-9` (functional) + faultlog (crash). *Provable before any new arm
   exists.*
2. **Functional extractor + repo-text profile builder + `FunctionalTextIndex`** (text-cosine only) +
   `gloop build-textprofile`. Hermetic tests with `StubEmbedder`.
3. **Optional-log fusion + abstention calibration** — RRF log channel, candidate UNION, calibrated τ.
4. **`gloop funceval`** — `functional` + `dispatch` + reused crash ablation arms.
5. **`gloop synth --mode functional`** (UI-text + CarPlay) + functional honest-refusal negatives.
6. **Proxy A/B + findings** — `funceval` over the labeled slice; write
   `docs/2026-07-1x-functional-bug-match-findings.md`; hand the metric shape to production for the first
   feedback cycle.

## 15. Class → signal map (capability reference)

| Class | Signals it carries | Attribution path |
|---|---|---|
| **Wrong UI text** | prose only (no logs, no crash) | title+description similarity → repo-text profile (hardest, pure text) |
| **Audio issues** | non-fatal log (AAudio underrun / `onAudioReady` / `libaaudio.so`) + prose | text-cosine ⊕ optional log-token RRF (v2's 9 oboe cases seed this) |
| **CarPlay / projection** | connection/timeout logs (no crash) + prose | text-cosine ⊕ optional connection-log RRF |

All three fall back to the **text backbone** when logs are absent, and **abstain** when the fused signal is
too weak — the design that makes the arm *capable* across the whole functional family instead of only the
log-bearing subset.
