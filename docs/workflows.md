# Workflows — Production & Dev checklists

> Two tickable checklists, one per environment, reflecting the **current honest state** (Core + the one
> Provisional-Core default; `[to build]` = not yet automated). The dev-box ↔ production split + the `[proxy]`/`[production]` tag convention live in
> [`environments.md`](environments.md); which capability is Core vs scaffolding lives in
> [`capabilities.md`](capabilities.md); the authoritative 18-section production SOP is
> [`production-guide.md`](production-guide.md). This doc is the top-level checklist over those.

---

## The JIRA-to-commit workflow — the end-to-end concept

GroundLoop's reason to exist is a single **closed loop**: from a **JIRA Bug ticket + its failure logs** to a
**bound Gerrit change**, with a **traceable JIRA↔commit chain** — automating the manual "which of the 130+
repos owns this defect, and where is the fix" triage. Three properties define it:

1. **A deterministic control plane owns the flow.** `core/run_ticket` sequences the eight stages as ordinary
   Python; the model only supplies *content* at each step (the extracted signals, the repo ranking, the
   proposed patch) — it never decides what happens next.
2. **The loop is oracle-blind.** The owning repo is a *predicted output*, **never an input**; `run_ticket`
   has no oracle parameter, so grading is a strictly **separate offline pass** — one execution is at once a
   real fix attempt and a scored benchmark case, and the benchmark cannot contaminate the attempt.
3. **The two ends are still mocked.** JIRA intake (`IssueSource`) and Gerrit submit/bind (`ChangeSink`) are
   `MockJira`/`MockGerrit` today; the *middle* (match → localize → fix) runs on real infrastructure.

### The eight stages, end to end

```
 ┌───────────────────────── JIRA end · IssueSource  (MockJira today) ─────────────────────────┐
 │  Bug ticket = summary + description + FAILURE LOGS  (logcat / stack / native #00 pc … )     │
 │                                    the logs are the primary evidence                        │
 └────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                               │  ① intake      issues.fetch(ticket_id)
                                               ▼
                                     ② extract     → Signals (exception · stack frame · class ·
                                               │                 method · .so · error code)
                                               ▼
                            ③ MATCH   index.rank_repos → owning repo     ◄════ THE GATE
                                               │      top-1 = prediction        (a predicted output +
                                               ▼                                 hidden-oracle field,
                            ④ materialize   estate.materialize → work-tree       NEVER a loop input)
                                               │      (checkout the chosen repo)
                                               ▼
                            ⑤ localize   index.retrieve → suspicious files       (plain FTS5 keyword)
                                               │
                                               ▼
                            ⑥ fix   fixer.propose → Patch   — or ABSTAIN         (never fabricate)
                                               │
                                               ▼
 ┌───────────────────────── Gerrit end · ChangeSink  (MockGerrit today) ──────────────────────┐
 │  ⑦ submit   changes.submit → Change   (Change-Id + JIRA key in the subject)                 │
 │  ⑧ bind     changes.bind → link Change ↔ ticket  +  transition the ticket (write-back)      │
 │             ▶ the append-only, auditable chain: discovery → logs → repo → localization →     │
 │               fix → commit ↔ ticket   (the traceable JIRA↔commit chain)                     │
 └─────────────────────────────────────────────────────────────────────────────────────────────┘

 ┄┄┄ separate offline pass · ORACLE-BLIND ┄┄►  grade(RunRecord, hidden oracle) → scorecard
      the loop emits its prediction with NO ground truth in scope; the grader reads the oracle after.
```

- **JIRA end (intake + write-back).** A ticket enters via `IssueSource.fetch`; on completion the bind stage
  links the change to the ticket and transitions it (`IssueSource.transition` / `post_comment` are the
  write-back surface). Today `MockJira` reads tickets from the filesystem — **no live REST fetch or
  write-back yet**.
- **The middle (the real work, on real infra).** `extract` → **`MATCH`** the owning repo (the gate — top-1
  of `rank_repos`, via the component-affinity prior over a real cross-repo atlas) → `materialize` (real
  checkout with `--repos`) → `localize` (plain FTS5 `retrieve`) → `fix` (`PlanningFixEngine` proposes a
  grounded patch or **abstains** rather than fabricate).
- **Gerrit end (submit + bind).** The patch becomes a `Change` and is bound to the ticket. Today
  `MockGerrit` synthesizes a content-hashed Change-Id + a local ledger — **no live Gerrit push yet**.

### What this means for the current state

On the single `[production]` run to date the loop executed **all 8 stages to a *mock* bound change** (the
manifest records `change_sink=mock`): the JIRA↔commit chain is demonstrated *mechanically* end-to-end, but
because the two ends are mocked it is **not yet a real, live traceable link**. Closing that gap is the
remaining net-new build to a fully real Core — a live JIRA REST `IssueSource` (fetch + comment/transition
write-back) and a live Gerrit `ChangeSink` (a real change + a verifiable JIRA↔commit binding); both are the
`[to build]` rows in the per-stage map below. Everything *between* the ends is Core or Core-when-configured
and has run on real GEI data.

---

## Production workflow

**What Production is:** the smallest Core system run against **real GEI data** to a graded, traceable
result. Everything below uses only [`capabilities.md`](capabilities.md) **Core** components — plus, since
2026-07-13, the one **Provisional-Core** default (Bug Plan Mode / `--fixer plan`: default-on on a fail-safe
mechanism + safety argument, its *effectiveness* still production-gated).

### Layer 1 — the runtime loop (mechanism: one ticket, 8 deterministic stages)

`core/run_ticket` is oracle-blind — it never sees the answer; grading is a separate offline pass.

1. **intake** — `MockJira` reads the ticket from the filesystem. `[to build: live JIRA REST source]`
2. **extract** — `ComponentExtractor` / `AndroidSignalExtractor` pulls component + log signals.
3. **match** — component→repo **affinity prior** (RRF-fused onto `AtlasIndex`) picks the owning repo.
   *Core when an affinity artifact is configured; else an honest `flood` fallback (recorded as `flood`).*
4. **materialize** — `CheckoutEstate` checks out the chosen repo (`--repos`). *Omit `--repos` ⇒ `MockEstate`
   empty worktree ⇒ fix ungradeable.*
5. **localize** — `AtlasIndex.retrieve` = **plain FTS5 keyword search** over symbol units.
6. **fix** — `PlanningFixEngine` ("Bug Plan Mode", the `--fixer plan` **default**, Provisional-Core) plans →
   gates → re-plans → **abstains** rather than emit an out-of-scope/ungrounded patch (fail-safe). `ModelPatchEngine`
   (`--fixer model`) is the single-shot opt-out. *Effectiveness (`resolved_rate`) is production-gated — the default is a
   safety choice (0 fabrication), not yet a measured resolution win.*
7. **submit** — `MockGerrit` records a change. `[to build: live Gerrit sink]`
8. **bind** — `MockGerrit` links change↔ticket. `[to build: real traceable JIRA↔commit chain]`

> Every feature available at each stage — all states, evidence, and file refs — is in the
> **[Per-stage feature map](#per-stage-feature-map-all-states)** below.

### Layer 2 — the operational SOP (each production run)

**Pre-flight**
- [ ] Load creds (NOT autoloaded): `set -a; . ./.env; set +a`
- [ ] **`KLOOP_DEV` must be UNSET** — it is the dev-gate that unlocks the hermetic fixtures (`--index`/`--fixer
  canned`/`--case`); a production run leaves it off (only hermetic/Type-1 runs set `KLOOP_DEV=1`)
- [ ] **`KLOOP_LABS`: unset for a real Core production run** (defaults stay `component`/`atlas`/`plan`). Set
  `KLOOP_LABS=1` (or `--profile labs`) ONLY in a **production-*test*** deployment to default the experimental
  stack (routing match; localize/fix stay Core) and earn its `[production]` read; the manifest records
  `profile=labs` so the two are never confused. Individual Candidate arms are also runnable explicitly
  (`--match-arm {semantic,functional,dispatch}`) — each fail-closes without its creds/artifact.
- [ ] Readiness: `gloop doctor --atlas-db $KLOOP_ATLAS_DB` → **READY** (repo/unit counts as expected)
- [ ] Hermetic gate green (no gateway needed): `.venv/bin/python -m pytest -q`
- [ ] Run **off real ext4** (`/home/vinc` directly, `/var/tmp`, `/dev/shm`) — never the v9fs mount (sqlite over the multi-GB atlas)

**Configure inputs** (offline, zero-cost)
- [ ] Mine the affinity prior over the full historical oracle: `gloop mine-affinity --dataset $FULL_ORACLE --out component_affinity.json`
- [ ] Arm the validated lever: `export KLOOP_AFFINITY=component_affinity.json` (the `component` default auto-engages the prior; **no artifact ⇒ a loud fall back to the `flood` baseline**)
- [ ] Confirm `KLOOP_PRODUCE_API_KEY` is set (else `--fixer plan`/`--fixer model` **fail-closes** — by design)

**Run** (defaults: `component` arm = Core · `plan` fixer = Provisional-Core "Bug Plan Mode")
- [ ] `gloop run --dataset <ds> --catalog <cat> --index-db $KLOOP_ATLAS_DB --repos <19-repo-mirror> --work <dir> --changes <path> --out run-N`
  - fail-closed contract: `--fixer plan`/`--fixer model` errors without creds **or** without a valid `--repos`
    (the `--repos` guard verifies catalog snapshots actually exist — no silent stub, no fabricated paths)
  - the batch writes `<out>/manifest.json` — a provenance sidecar (timestamp, atlas identity, `match_arm`,
    `fixer`, affinity hash, produce+embed model pins, `change_sink=mock`, `n_cases`)

**Grade** (offline; the oracle is read here only)
- [ ] `gloop grade-run --runs run-N --dataset <ds> --index-db $KLOOP_ATLAS_DB --out card-N.json`
  - the card now carries per-case `predicted_repo` / `oracle_repo` / `signals` / `cost_usd` / `fixer` (miss-RCA-ready)
- [ ] Read the printed **promotion-eligibility notes** — for a `--fixer plan` run with gradeable resolution,
  grade-run flags the Provisional-Core obligation (PlanningFixEngine → confirm Core / revert)
- [ ] Regression check vs the last release: `gloop grade-run … --compare <prev-card.json>` → a per-stage
  improved/flat/regressed verdict + a `.compare.json` sibling

**Accept** (gates — see [`production-guide.md`](production-guide.md) §6)
- [ ] `component` recall@3 ≫ `flood` recall@3 (else the affinity table / `Ticket.component` join is empty — a **data** problem, not a weight problem)
- [ ] functional recall@1/@3 lands near the 406 target **≈ 0.50 / 0.90 `[production]`** (honest `--loo`)
- [ ] localize file@5 as expected; fix **gradeable** (requires `--repos`)
- [ ] tag every efficacy number `[production]`

**Feedback → dev** (close the loop)
- [ ] Append the run to [`results-log.md`](results-log.md), `[production]`-tagged
- [ ] Record misses (label≠owner, near-ties, coverage gaps) as **Candidate** work items for Dev
- [ ] `[to build]`: triage store, human-quality overlay, latency/threshold monitoring (production-guide §9–18)

---

## Dev workflow

**What Dev is:** the isolated proxy space where capabilities are built and validated **before** they may
touch Production. Dev may be complex, but it must not change default production behavior — a new capability
stays an opt-in **Candidate** until a `[production]` read earns it promotion.

### Layer 1 — the inner loop (any change, every time)

- [ ] Setup (once): `uv sync --extra dev --extra produce`
- [ ] Change **adapters / the composition root only** — NEVER `groundloop/core/`, NEVER the atlas schema in `engines/atlas/store.py`
- [ ] A Candidate must **not** change default production behavior (add an opt-in flag; leave the Core defaults alone)
- [ ] Type-1 hermetic tests (no network / no real LLM): `.venv/bin/python -m pytest -q` → green
- [ ] Anti-leak invariants green: `tests/test_invariants.py` (loop stays oracle-blind)
- [ ] Lint clean: `.venv/bin/ruff check groundloop tests`
- [ ] Commit only when green + ruff clean; end with the `Co-Authored-By:` trailer; branch first if on `main`

### Layer 2 — Candidate → Core promotion (a new capability)

- [ ] Build it as a new adapter/arm, swapped in at the composition root (`cli/__init__.py`) or an existing orchestrator — `core/` stays frozen
- [ ] Register it as **Candidate** in [`capabilities.md`](capabilities.md) (state + what its promotion needs)
- [ ] Type-2-on-proxy eval: `gloop eval` / `fixeval` / `funceval` / `faulteval` over the 9-repo `atlas-9.db` + synth/mined datasets (**off ext4**) → a `[proxy]` read (mechanism only)
- [ ] **Adversarially verify** the result — never trust a single proxy number (the size-bias lesson: proxy 0.68 vs production 0.10)
- [ ] Log the `[proxy]` read in [`results-log.md`](results-log.md), tagged
- [ ] **PROMOTION GATE:** ship it via the Production checklist → a `[production]` read; promote **only if** it *consistently outperforms* the current Core on real data **and** passes stability + cost + regression
- [ ] On promotion: flip the default at the composition root, move the capability **Candidate → Core** in `capabilities.md`, log the promotion `[production]`
- [ ] If it loses: keep it **Candidate**, or move it to **Archived** — but only on a *genuinely-concluded* null (a valid metric, no confound; see the KB re-verdict for how an invalid null gets walked back)

---

## Per-stage feature map (all states)

Every feature at every stage, with the evidence behind its state and what a promotion needs. **State legend:**
**Core** = production default, `[production]`-validated · **Provisional-Core** = default-on on a fail-safe
mechanism + safety argument, *effectiveness* production-gated (resolves to Core or reverts) · **Core\*** =
Core-when-configured (needs its artifact/flag) · **Candidate** = Dev-Labs, opt-in, `[proxy]`-only · **Dev-Labs Infra** = permanent
measurement apparatus · **Fixture** = hermetic Type-1 double (never default) · **Archived** = measured null ·
**Dormant** = valuable concept, but the current implementation is weak/0-signal — blocked on a redesign, not a
concluded null · **`[to build]`** = not implemented. (Wide table — scroll right; states/evidence trace to
[`capabilities.md`](capabilities.md) + [`results-log.md`](results-log.md).)

| Stage (port) | Feature | State | Reachable via | Evidence | Blocker → Core | File |
|---|---|---|---|---|---|---|
| **1 intake** (IssueSource) | `MockJira` (filesystem tickets) | Fixture | default (only) | `[production]` read GEI tickets; no write-back | replaced, not promoted | `adapters/mock/jira.py` |
| | live JIRA REST source | `[to build]` | — | none | build fetch + comment/transition write-back | — |
| **2 extract** (SignalExtractor) | `AndroidSignalExtractor` | Core | default base | `[production]` (under component) | — | `domains/android_ivi/signal_extractor.py` |
| | `ComponentExtractor` (adds `Ticket.component`) | Core | component arm (default) | `[production]` | — | `domains/android_ivi/component_signals.py` |
| | `FaultSignalExtractor` | Candidate | routing arm / faulteval | `[proxy]` faultslice 0.86 | a `[production]` read | `domains/android_ivi/fault_signals.py` |
| | `FunctionalTextExtractor` | Candidate | `gloop run --match-arm functional` / funceval | `[proxy]` functional 0.68 | a `[production]` read (now run-reachable) | `domains/android_ivi/functional_signals.py` |
| | `DispatchExtractor` | Candidate | `gloop run --match-arm dispatch` / funceval | `[proxy]` dispatch 0.94 (crash) | a `[production]` read (now run-reachable) | `domains/android_ivi/functional_signals.py` |
| | `RecordingExtractor` (signals-capture sidecar) | Core | batch `--out` (default) | `[production]`-ready — records the loop's `signals` into the run-record (miss-RCA data); mirrors `RecordingEstate`, core frozen | — | `adapters/extractor_recording.py` |
| **3 match** (`rank_repos`) | `AtlasIndex` (flood, FTS5 membership) | Core | `--match-arm flood` / base | `[production]` recall@1 0.10 | — | `adapters/index/atlas.py` |
| | `ComponentPriorIndex` (affinity prior + RRF) | Core\* | `--match-arm component` (default) + `--affinity`/`KLOOP_AFFINITY` | `[production]` 0.10→**0.50** / @3 0.90 | supply the mined affinity artifact (else honest flood) | `adapters/index/component_prior.py` |
| | `FaultRoutingIndex` (faultslice + routing) | Candidate | `--match-arm routing` / faulteval | `[proxy]` routing 0.94, decoy-robust | a `[production]` read | `adapters/index/fault_routing.py` |
| | `FunctionalTextIndex` (bge-m3 repo-text) | Candidate | `gloop run --match-arm functional` (needs embedder + `--functional-profile`) / funceval | `[proxy]` 0.68 vs flood 0.32 | a `[production]` read (now run-reachable) | `adapters/index/functional_text.py` |
| | `DispatchIndex` (crash\|functional router) | Candidate | `gloop run --match-arm dispatch` (needs embedder + `--functional-profile`) / funceval | `[proxy]` 0.94 on crash (no regression) | a `[production]` read (now run-reachable) | `adapters/index/functional_text.py` |
| | `SemanticAtlasIndex` (bge-m3 vector) | Candidate | `gloop run --match-arm semantic` (needs `KLOOP_EMBED_BASE_URL`) / `gloop eval --semantic` | `[proxy]` recall 0.02→0.23 | a `[production]` read (now run-reachable) | `adapters/index/atlas_semantic.py` |
| | `LLMJudgeIndex` (LLM rerank) | Candidate (eval-only) | `gloop eval --judge` (removed from run `--match-arm` 2026-07-16 — zero measured recall) | none logged | a `[production]` read via eval | `adapters/index/atlas_judge.py` |
| | `TokenIndex` (M0 stub) | Fixture | `--index <json>` | none (returns `[]` on retrieve) | (never) | `adapters/index/simple.py` |
| **4 materialize** (RepoEstate) | `CheckoutEstate` (real owner checkout) | Core\* | `--repos` | `[production]`-intended (prod run passed none) | default it / require `--repos` | `adapters/estate.py:87` |
| | `RecordingEstate` (outcome decorator) | Core | batch `--out` (default) | `[production]` (batch path) | — | `adapters/estate.py:57` |
| | `MockEstate` (empty worktree) | Fixture | default w/o `--repos` | `[production]` → fix ungradeable | (never) | `adapters/estate.py:13` |
| | `GitFixtureEstate` (@base snapshot) | Dev-Labs Infra | fixeval | `[proxy]` harness | — (not a loop role) | `adapters/estate.py:29` |
| **5 localize** (`retrieve`) | `AtlasIndex.retrieve` (FTS5 keyword) | Core | **the run default** (`--localize atlas`, restored 2026-07-16); `--localize tokens` wraps it as a reachable opt-in | `[production]` **7/10 file@5** | — | `adapters/index/atlas.py:30` |
| | `SemanticAtlasIndex.retrieve` (bge-m3 vector) | Candidate (parked 2026-07-16) | removed from `--localize` (measured negative at `file@1`); `SemanticAtlasIndex` retained for `--match-arm semantic` | `[proxy]` negative for localize | a real reason + a `[production]` read | `adapters/index/atlas_semantic.py:50` |
| | `LocalizeDispatchIndex` (per-ticket FTS5⇄bge-m3 router) | **Archived 2026-07-16** | — (removed from `--localize`; module + tests deleted, recoverable from git) | `[production]` measured null `file@1 0/10` (inert under `ComponentExtractor`) | archived — the win was entirely the FTS5-tokens branch, kept as `--localize tokens` | *(git history)* |
| | `SignalQueryIndex` (signal-aware FTS5: query the extracted code tokens, fallback prose) | **Candidate** (reverted from Provisional-Core 2026-07-16) | `--localize tokens` (reachable opt-in, **no embedder** — pure FTS5; the default is `atlas`) | `[proxy]` functional isolated `file@1` 0.010→**0.166** (16×); one class regresses (`audio −0.017`); **no `[production]` read** | a `[production]` GEI `file@1` read → promote to default if it wins | `adapters/index/signal_query.py` |
| | `RerankLocalizeIndex` (hybrid/injected pool → grounded LLM file-judge over source + CodeWiki[+CBM] context; may only REORDER) | Candidate | `--localize rerank` (**fail-fasts** without `KLOOP_EMBED_BASE_URL`; judge needs `KLOOP_PRODUCE_API_KEY`; `--repos`+`KLOOP_REGISTRY` for source/CodeWiki) | `[proxy]` `rerank_cw_judge` **file@1 0.212 / file@5 0.384** (n=108, isolated, judge+CodeWiki) | a `[production]` GEI `file@1` read | `adapters/index/rerank_localize.py` |
| | `CascadeLocalizeIndex` (recall-first RRF union: prose floor ∪ crash code-tokens ∪ literal anchors ∪ bge-m3 semantic; non-regressive at graded k) | Candidate | `--localize cascade` (degrades gracefully w/o an embedder — semantic tier omitted) | `[proxy]` **file@1 0.098 / file@5 0.308** (n=108) — beats the FTS floor, but the **literal tier is marginal**; the **semantic tier is the lever** (design bet partially disconfirmed) | a `[production]` read + the CamelCase-atlas read | `adapters/index/cascade_localize.py` |
| | **`cascade_judge`** (the cascade recall pool reranked by the LLM file-judge — `pool_index` seam on `RerankLocalizeIndex`) | Candidate (**leading — best `[proxy]` to date**) | `--localize cascade_judge` (needs judge creds + **`--repos`** for source; CodeWiki needs atlas doc-units) | `[proxy]` **file@1 0.245 / file@5 0.469** (n=108, WITH `--repos`) — beats `rerank_cw_judge` at ~equal cost | a `[production]` GEI `file@1` read — runbook `docs/runbooks/cascade-judge-production-gate.md` | `rerank_localize.py` + `cascade_localize.py` |
| **6 fix** (FixEngine) | `PlanningFixEngine` — **"Bug Plan Mode"** (plan→gate→re-plan→abstain→execute; the executed diff is re-gated to candidate scope) | **Provisional-Core (default; effectiveness production-gated)** | `--fixer plan` (**run default**) | `[proxy]` plan recall@1 0.48/@5 0.68, groundedness 0.56, **fab 0.0** (safety proven; resolution never gradeable) | a `[production]` `resolved_rate` read (grade-run promotion note) → confirm Core / revert | `adapters/fix/planning.py` |
| | `ModelPatchEngine` (single-shot) | Core\* | `--fixer model` (**opt-out**) | `[production]` ran; fix ungradeable (empty worktree) | gradeable worktrees (`--repos`) | `adapters/fix/model_patch.py` |
| | `CannedFixEngine` (hermetic stub) | Fixture | `--fixer canned` | — | (never) | `adapters/fix/canned.py` |
| | Dev-experience KB / Skill injection | Dormant | `fixeval --skills kb [--skills-inject fix-only]` | `[proxy]` **0 positive signal**: old null discredited (confound Δ−0.10 file@1, wrong metric); `resolved_rate` re-test inconclusive (0 floor) | 3-axis redesign (injection mechanism, richer Knowledge, loop-outcome learning) + real-fix slice with resolution headroom | `adapters/skills/mock.py` |
| | Knowledge injection (distilled) | Dormant | `fixeval --knowledge {candidate,validated}` | `[proxy]` 0/60 on `plan_target_recall` (wrong metric) — 0 positive signal, not a valid null | 3-axis redesign + real-fix slice | `kb/knowledge.py` |
| **7 submit** (ChangeSink) | `MockGerrit.submit` (synthesized change) | Fixture | default (only) | `[production]` ran (synthetic) | replaced, not promoted | `adapters/mock/gerrit.py` |
| | live Gerrit sink | `[to build]` | — | none | push a real change + Change-Id | — |
| **8 bind** (ChangeSink) | `MockGerrit.bind` (change↔ticket) | Fixture | default (only) | `[production]` ran (no real chain) | replaced, not promoted | `adapters/mock/gerrit.py` |
| | real traceable JIRA↔commit chain | `[to build]` | — | none | live JIRA + Gerrit write-back | — |
| **run-record** (batch `--out` output) | persisted `signals` + fix `cost_usd`/`tokens` + `fixer` kind | Core | batch `--out` (default) | `[production]`-ready feedback data plane — core `RunRecord` stays frozen; captured via sidecars + `GatewayModel` self-cost | — | `run/record.py`, `run/batch.py` |
| | `manifest.json` provenance (timestamp · atlas identity · produce+embed model pins · affinity hash · `change_sink=mock` · `n_cases`) | Core | batch `--out` (default) | `[production]`-ready run attribution | — | `run/manifest.py` |
| **offline** (grade) | `grade-run` per-stage self-scoring + richer rows (predicted/oracle repo · `signals` · `cost_usd` · `fixer`) | Dev-Labs Infra | `gloop grade-run` | `[production]` feedback scorecard | — (measurement apparatus, never promoted into the loop) | `grade/grade_run.py` |
| | `grade-run --compare <prev-card>` (per-stage improved/flat/regressed verdict + `.compare.json`) | Dev-Labs Infra | `gloop grade-run --compare` | `[production]`-ready regression gate | — | `grade/compare.py` |
| | promotion-eligibility notes (reporting-only; never auto-enacts) | Dev-Labs Infra | `gloop grade-run` (auto-printed) | surfaces the Provisional-Core obligation (plan run w/ gradeable resolution → confirm Core / revert) | — | `grade/promotion.py` |

**Model port (cross-cutting, underlies fix + any eval rerank):** `GatewayModel` = Core (`adapters/model/gateway.py`);
`CannedModel` = Fixture (`adapters/mock/model.py`) — the hermetic model, and formerly the silent-degrade the
re-point removed.

**Production-surface guards & infra (cross-cutting, 2026-07-13) — all Core:** the **dev-gate**
(`KLOOP_DEV` / hidden `--dev`) rejects the Fixture paths (`--index` / `--fixer canned` / `--case`) in a
production shell — Type-1 arms it via an autouse fixture (`cli/__init__.py`, `tests/conftest.py`); the hardened
**`--repos` guard** verifies catalog snapshots actually exist before a real fixer runs (`cli/__init__.py`); and
the plan/patch primitives were relocated to **`groundloop/fix/`** so Core no longer imports the Dev-Labs
`fixeval/` package (`groundloop/fix/{plan,patch}.py`).

**Labs switch + SplitIndex (cross-cutting; updated 2026-07-16) — Core:** the experimental match arms
(`--match-arm {semantic,functional,dispatch}`) are **selectable from `gloop run`** (opt-in Candidates —
fail-closed without their creds/artifacts), so each can earn its `[production]` read. *(The 2026-07-16
workflow-simplification removed run `--match-arm judge` → eval-only and parked/archived `--localize
{semantic,dispatch}`; the 2026-07-18 localize-recall work then added the opt-in Candidates `--localize
{rerank, cascade, cascade_judge}`. Current localize menu: `{atlas, tokens, rerank, cascade, cascade_judge}`.)* **`KLOOP_LABS=1` / `--profile
labs`** is a per-environment switch (the analogue of `KLOOP_DEV`) that flips the run *defaults* to the
experimental stack (routing match; localize + fix stay the Core `atlas`/`plan`) — **explicit flags always
override it**, and with it **unset the defaults are Core-identical** (`component`/`atlas`/`plan`; asserted by
`tests/run/test_core_defaults_unchanged.py`). `SplitIndex` (`adapters/index/split.py`) lets `--localize`
differ from `--match-arm` (rank from one index, retrieve from another — used when `--match-arm semantic` runs
with `atlas` localize). The manifest records `profile`/`localize` so a labs run can never be misread as a
Core production run.

---

> Eval-harness detail: [`evaluation.md`](evaluation.md) · atlas build + the ext4 gotcha: [`build-setup.md`](build-setup.md).
