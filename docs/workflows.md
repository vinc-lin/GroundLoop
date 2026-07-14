# Workflows — Production & Dev checklists

> Two tickable checklists, one per environment, reflecting the **current honest state** (Core + the one
> Provisional-Core default; `[to build]` = not yet automated). The dev-box ↔ production split + the `[proxy]`/`[production]` tag convention live in
> [`environments.md`](environments.md); which capability is Core vs scaffolding lives in
> [`capabilities.md`](capabilities.md); the authoritative 18-section production SOP is
> [`production-guide.md`](production-guide.md). This doc is the top-level checklist over those.

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
  stack (routing match + semantic localize) and earn its `[production]` read; the manifest records `profile=labs`
  so the two are never confused. Individual arms are also runnable explicitly (`--match-arm {semantic,judge,
  functional,dispatch}`, `--localize semantic`) — each fail-closes without its creds/artifact.
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

- [ ] Setup (once): `uv sync --extra dev`
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
**`[to build]`** = not implemented. (Wide table — scroll right; states/evidence trace to
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
| | `LLMJudgeIndex` (LLM rerank) | Candidate | `gloop run --match-arm judge` (needs creds) / `gloop eval --judge` | none logged | a `[production]` read (now run-reachable) | `adapters/index/atlas_judge.py` |
| | `TokenIndex` (M0 stub) | Fixture | `--index <json>` | none (returns `[]` on retrieve) | (never) | `adapters/index/simple.py` |
| **4 materialize** (RepoEstate) | `CheckoutEstate` (real owner checkout) | Core\* | `--repos` | `[production]`-intended (prod run passed none) | default it / require `--repos` | `adapters/estate.py:87` |
| | `RecordingEstate` (outcome decorator) | Core | batch `--out` (default) | `[production]` (batch path) | — | `adapters/estate.py:57` |
| | `MockEstate` (empty worktree) | Fixture | default w/o `--repos` | `[production]` → fix ungradeable | (never) | `adapters/estate.py:13` |
| | `GitFixtureEstate` (@base snapshot) | Dev-Labs Infra | fixeval | `[proxy]` harness | — (not a loop role) | `adapters/estate.py:29` |
| **5 localize** (`retrieve`) | `AtlasIndex.retrieve` (FTS5 keyword) | Core | run + fixeval default (component/flood/routing delegate here) | `[production]` **7/10 file@5** | — | `adapters/index/atlas.py:30` |
| | `SemanticAtlasIndex.retrieve` (bge-m3 vector) | Candidate | `gloop run --localize semantic` (via `SplitIndex`; needs `KLOOP_EMBED_BASE_URL`) | none (unmeasured *for localize*) | a `[production]` read (now run-reachable) | `adapters/index/atlas_semantic.py:50` |
| **6 fix** (FixEngine) | `PlanningFixEngine` — **"Bug Plan Mode"** (plan→gate→re-plan→abstain→execute; the executed diff is re-gated to candidate scope) | **Provisional-Core (default; effectiveness production-gated)** | `--fixer plan` (**run default**) | `[proxy]` plan recall@1 0.48/@5 0.68, groundedness 0.56, **fab 0.0** (safety proven; resolution never gradeable) | a `[production]` `resolved_rate` read (grade-run promotion note) → confirm Core / revert | `adapters/fix/planning.py` |
| | `ModelPatchEngine` (single-shot) | Core\* | `--fixer model` (**opt-out**) | `[production]` ran; fix ungradeable (empty worktree) | gradeable worktrees (`--repos`) | `adapters/fix/model_patch.py` |
| | `CannedFixEngine` (hermetic stub) | Fixture | `--fixer canned` | — | (never) | `adapters/fix/canned.py` |
| | Dev-experience KB / Skill injection | Candidate | `fixeval --skills kb [--skills-inject fix-only]` | `[proxy]` **unproven**: old null discredited (confound Δ−0.10 file@1, wrong metric); `resolved_rate` re-test inconclusive (0 floor) | Phase 2 real-fix slice with resolution headroom | `adapters/skills/mock.py` |
| | Knowledge injection (distilled) | Candidate | `fixeval --knowledge {candidate,validated}` | `[proxy]` 0/60 on `plan_target_recall` (wrong metric) — unproven, not null | Phase 2 real-fix slice | `kb/knowledge.py` |
| **7 submit** (ChangeSink) | `MockGerrit.submit` (synthesized change) | Fixture | default (only) | `[production]` ran (synthetic) | replaced, not promoted | `adapters/mock/gerrit.py` |
| | live Gerrit sink | `[to build]` | — | none | push a real change + Change-Id | — |
| **8 bind** (ChangeSink) | `MockGerrit.bind` (change↔ticket) | Fixture | default (only) | `[production]` ran (no real chain) | replaced, not promoted | `adapters/mock/gerrit.py` |
| | real traceable JIRA↔commit chain | `[to build]` | — | none | live JIRA + Gerrit write-back | — |
| **run-record** (batch `--out` output) | persisted `signals` + fix `cost_usd`/`tokens` + `fixer` kind | Core | batch `--out` (default) | `[production]`-ready feedback data plane — core `RunRecord` stays frozen; captured via sidecars + `GatewayModel` self-cost | — | `run/record.py`, `run/batch.py` |
| | `manifest.json` provenance (timestamp · atlas identity · produce+embed model pins · affinity hash · `change_sink=mock` · `n_cases`) | Core | batch `--out` (default) | `[production]`-ready run attribution | — | `run/manifest.py` |
| **offline** (grade) | `grade-run` per-stage self-scoring + richer rows (predicted/oracle repo · `signals` · `cost_usd` · `fixer`) | Dev-Labs Infra | `gloop grade-run` | `[production]` feedback scorecard | — (measurement apparatus, never promoted into the loop) | `run/grade_run.py` |
| | `grade-run --compare <prev-card>` (per-stage improved/flat/regressed verdict + `.compare.json`) | Dev-Labs Infra | `gloop grade-run --compare` | `[production]`-ready regression gate | — | `run/compare.py` |
| | promotion-eligibility notes (reporting-only; never auto-enacts) | Dev-Labs Infra | `gloop grade-run` (auto-printed) | surfaces the Provisional-Core obligation (plan run w/ gradeable resolution → confirm Core / revert) | — | `run/promotion.py` |

**Model port (cross-cutting, underlies fix + any eval rerank):** `GatewayModel` = Core (`adapters/model/gateway.py`);
`CannedModel` = Fixture (`adapters/mock/model.py`) — the hermetic model, and formerly the silent-degrade the
re-point removed.

**Production-surface guards & infra (cross-cutting, 2026-07-13) — all Core:** the **dev-gate**
(`KLOOP_DEV` / hidden `--dev`) rejects the Fixture paths (`--index` / `--fixer canned` / `--case`) in a
production shell — Type-1 arms it via an autouse fixture (`cli/__init__.py`, `tests/conftest.py`); the hardened
**`--repos` guard** verifies catalog snapshots actually exist before a real fixer runs (`cli/__init__.py`); and
the plan/patch primitives were relocated to **`groundloop/fix/`** so Core no longer imports the Dev-Labs
`fixeval/` package (`groundloop/fix/{plan,patch}.py`).

**Labs switch + SplitIndex (cross-cutting, 2026-07-13) — Core:** the experimental match arms
(`--match-arm {semantic,judge,functional,dispatch}`) and `--localize semantic` are now **selectable from
`gloop run`** (opt-in Candidates — fail-closed without their creds/artifacts), so each can earn its
`[production]` read. **`KLOOP_LABS=1` / `--profile labs`** is a per-environment switch (the analogue of
`KLOOP_DEV`) that flips the run *defaults* to the experimental stack (routing match + semantic localize; fix
stays `plan`) — **explicit flags always override it**, and with it **unset the defaults are Core-identical**
(`component`/`atlas`/`plan`; asserted by `tests/run/test_core_defaults_unchanged.py`). `SplitIndex`
(`adapters/index/split.py`) lets `--localize` differ from `--match-arm` (rank from one index, retrieve from
another). The manifest records `profile`/`localize` so a labs run can never be misread as a Core production run.

---

> Eval-harness detail: [`evaluation.md`](evaluation.md) · atlas build + the ext4 gotcha: [`build-setup.md`](build-setup.md).
