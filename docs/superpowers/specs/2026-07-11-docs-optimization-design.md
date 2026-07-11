# Docs Optimization + Dev↔Production Distinction — Design (2026-07-11)

**Status:** design approved (brainstorming), ready for an implementation plan.

**Goal.** Consolidate GroundLoop's `docs/` from **23 top-level files (~5,600 lines, much of it redundant)** down
to **~12**, and make the **dev-box ↔ production** distinction *canonical* (owned by one doc) instead of smeared
across ~12 docs. Add the missing **production-side operational + validation + feedback SOP** the project needs.

**Why.** Two problems compound: (1) the doc set has accreted overlapping "what/how" guides (five of them) plus
seven dated findings docs; (2) the single most important operating fact — that the **OSS proxy is a
mechanism/regression harness and only production is the efficacy scoreboard** — is restated ad hoc in 12 docs
and stated authoritatively in none. This caused real confusion (e.g. the functional-text `[proxy]` 0.68 vs
`[production]` 0.10 surprise). A canonical `environments.md` + a two-tag convention fixes it.

## Decisions (locked during brainstorming)

- **Ambition:** full restructure + consolidate (merge overlapping guides; fold the 7 findings into one log; cut
  the doc count materially).
- **Superseded originals:** **delete** (git preserves history verbatim); update `CLAUDE.md` + cross-links.
- **New `production-guide.md`:** target-SOP written with `[in place]` / `[to build]` status tags (doubles as a
  gap list); **GroundLoop-native** (keep every requirement's intent, drop inapplicable fields); **absorbs**
  `production-migration.md`; one canonical machine-collectable record template; explicit PII/secret-hygiene tie-in.

## Non-goals

- No code changes. This is docs-only (`docs/**`, `CLAUDE.md`, `docs/STATUS.md`, and the memory index pointer).
- Not touching `docs/superpowers/specs/**` or `plans/**` — those are point-in-time provenance; leave as-is.
- No new facts invented. Every unique fact in a deleted doc must survive in a target doc (relocated + deduped),
  or in the results-log with a git pointer. Consolidation, not rewriting-from-scratch.

---

## 1. Target doc map (23 → 12)

`⭐` = new. Each "source" file is **deleted** after its content lands in the target.

| Target (top-level `docs/`) | Sources merged in (then deleted) | Role |
|---|---|---|
| **`environments.md`** ⭐ | the dev/prod distinction extracted from ~12 docs; `workflow.md` (oracle-blindness, eval workflow) | canonical dev↔production contract + labeling convention |
| `charter.md` (edit) | `application-guide.md` (one-system-two-uses, scenarios, scope) | mission, FR/NFR, 4 stages, metrics, glossary, non-goals |
| `architecture.md` (edit) | `workflow.md` (stage-by-stage, under-the-hood atlas) | 7 ports, 8-stage control plane, composition root, migration |
| **`guide.md`** ⭐ (rename/merge) | `user-guide.md` + `workflow.md` (closed loop, stage status) + `application-guide.md` (workflow) | the single deploy + run + migrate how-to |
| `evaluation.md` (rename `type2-evaluation.md`) | `groundloop-testing-strategy.md` | eval bible: two test surfaces, fleet, dataset, arms, metrics, harness, integrity |
| **`build-setup.md`** ⭐ (merge) | `m1-index-build.md` + `type2-eval-setup.md` + `type2-atlas-build-findings.md` | atlas build + env vars + gotchas + gated-live setup |
| `fix-loop.md` (rename `downstream-fix-loop.md`) | `skill-kb-migration.md` | fix-loop design + KB arm |
| `engines.md` (edit, trim) | — | produce/lore/CBM/atlas ops |
| **`production-guide.md`** ⭐ | `production-migration.md` | production deploy + validate + feedback SOP (§ below) |
| `roadmap.md` (edit, trim) | — | forward plan |
| **`results-log.md`** ⭐ | the 7 dated `2026-07-*-*findings.md` (+ `2026-07-06-first-evaluation.md`) | one chronological, env-tagged results log |
| `STATUS.md` (edit, trim) | — | living state |

**Deleted (16):** `application-guide.md`, `user-guide.md`, `workflow.md`, `groundloop-testing-strategy.md`,
`m1-index-build.md`, `type2-eval-setup.md`, `type2-atlas-build-findings.md`, `skill-kb-migration.md`,
`production-migration.md`, and the 7 findings docs (`2026-07-06-first-evaluation`,
`2026-07-07-claim-kb-preview-findings`, `2026-07-07-plan-format-phase3-findings`,
`2026-07-09-android-log-match-v2-findings`, `2026-07-10-component-routing-findings`,
`2026-07-10-functional-bug-match-findings`, `2026-07-11-functional-10case-e2e-findings`).

**Renamed:** `type2-evaluation.md`→`evaluation.md`, `downstream-fix-loop.md`→`fix-loop.md` (use `git mv` to
keep history; a rename is fine since the content stays).

Result: **12 top-level docs** (the table's 12 rows, `STATUS.md` included), down from 23. Accounting: 5 kept
& edited (charter, architecture, engines, roadmap, STATUS) + 2 renamed via `git mv` (evaluation, fix-loop) + 5
new (environments, guide, build-setup, production-guide, results-log) = 12; 16 sources deleted. (Rejected
aggressive variant: additionally folding `roadmap`→STATUS, `engines`→build-setup, `fix-loop`→evaluation —
those have distinct audiences.)

## 2. `environments.md` (the centerpiece, ~60–80 lines)

**2a. Two-environments table** — dev box (OSS proxy: `atlas-9.db`, `corpora-local`; Type-1 hermetic + Type-2
on proxy; numbers = **mechanism/regression, not efficacy**; anchor `evaluation.md`) vs production (real 19-repo
GEI atlas + JIRA↔Gerrit oracle 10-case/406; **efficacy scoreboard + feedback source**; production-only;
anchor `production-guide.md`).

**2b. The develop-against-feedback loop** — build on proxy → ship to `master` → production runs the real evals
→ numbers + failure cases feed back → iterate. **Production is the oracle of record.**

**2c. The labeling convention (mandated repo-wide):**
- **`[proxy]`** = mechanism/regression, built on the dev box (optimistic; may not transfer).
- **`[production]`** = efficacy, measured on GEI (the real number).
- Rule: no bare efficacy number in `STATUS.md` / `results-log.md` / future findings — always tagged, e.g.
  "functional recall@1 **0.68 `[proxy]`** → **0.10 `[production]`**".

**2d. Standing lesson + reuse contract** — the proxy is optimistic (the 0.68→0.10 size-bias example); the
reuse contract (pinned atlas SHAs, `bge-m3` pin, model pins, shared `atlas.db` path, unchanged schema) that
keeps `atlas.db` shareable across both environments.

## 3. `production-guide.md` (your 18 sections, GroundLoop-native, gap-tagged)

Three arcs; every item in pipeline terms; each `[in place]` / `[to build]`; one canonical record shared by
§11/§15.

**Part A — Deploy & operate.** §1 Requirements (gateway deepseek/qwen/bge-m3 + creds; 19-repo `atlas.db` on
**ext4**; `component_affinity.json`; JIRA↔Gerrit oracle; `KLOOP_*`; disk; git/`gh`). §2 Install & configure
(`uv sync`; `.env`; `gloop build-atlas`; `mine-affinity`; `combine-oracle`; record atlas SHA / model pins /
affinity version). §3 Startup/shutdown (**honest note: batch/CLI, not a daemon** — invoked per run; standing
deps = gateway + atlas). §4 Deployment verification (`gloop doctor` READY + gateway `200` + a 1–2-case smoke →
`grade-run`; record versions/operator/date). §5 Production usage (ticket → 8-stage `run_ticket` → `grade-run`;
inputs = JIRA ticket+logs; outputs = predicted repo / localize / patch / JIRA↔commit bind; limits).

**Part B — Validate.** §6 Functional (10-case/406 oracle via `grade-run`; per-stage; `by_bug_kind`;
`[production]`). §7 Performance (per-stage latency + token **`$/solved`** from fixeval; atlas CPU/mem; GPU-OOM
noted **out of scope** — inference is gateway-side). §8 Stability (gateway timeouts/5xx, atlas/ext4 I/O, CBM
restart-loops, v9fs traps; incident record).

**Part C — Feedback → development.** §9 Usage data (tickets processed, per-arm completion/abstention via Φ_c;
**no PII** — secret-hygiene tie-in). §10 Quality feedback (correct=recall@1 · hallucination=**fabrication_rate**
· retrieval=file_recall · completeness=resolved_rate · trust=honest-abstention · + human accept/correct/reject).
§11 Failure cases (the 10-case findings formalized → the canonical record; regression seeds). §12 Knowledge
gaps (unindexed files/repos e.g. `CpAccessibilityManager`/`XCUSBMediaService`; component→owner disagreements →
atlas rebuild / affinity / KB). §13 User feedback (engineer trust/time-saved; frequently-edited patches). §14
Dev-feedback data (the standing process: representative success/fail/hard/low-confidence/high-cost cases → eval
datasets / regression tests / KB / prompt & retrieval improvements / roadmap items — the loop back to dev). §15
Submission format (the canonical record). §16 Review process (cadence + taxonomy:
deploy/config/perf/stability/model/retrieval/knowledge/workflow/UX/feature; severity × frequency ÷ cost). §17
Release tracking (per deploy: date, atlas SHA, model pins, affinity version, change summary, known issues,
rollback = revert to prior atlas/affinity, validation result; link feedback/failures to the release). §18
Success criteria (gateway+atlas READY · smoke+`grade-run` pass · match/localize within agreed thresholds vs
last release · no unresolved critical · feedback collectable · rollback possible).

**Canonical record** (shared by §11 + §15; `*` = auto-emitted by `grade-run`):
```
record_id · date · env=[production] · reporter · stage(match|localize|fix)
ticket_id* · predicted_repo* · oracle_repo* · signals* · expected_vs_actual*
category · severity · frequency · impact · logs · root_cause · workaround
suggested_improvement · owner · target_version · status
```

`production-guide.md` is the largest doc in the set (~2× a normal doc); the status tags make its gaps explicit.

## 4. `results-log.md` format

Reverse-chronological. A summary table (`date | track | env | headline`) then a compact block per result
(≤ ~8 lines): date · track · env tag · headline number(s) · one-line takeaway · a git pointer to the deleted
findings doc + the relevant commit(s) for full detail. ~950 lines of findings → ~130. Every number carries
`[proxy]` / `[production]`.

## 5. Merge / dedup mechanics (one plan task per target doc)

For each target doc: pull the unique content from its sources; **replace every dev/prod restatement with a link
to `environments.md`**; trim redundancy; keep every unique fact. Then delete the sources (`git rm`), re-point all
cross-links ("See also" blocks, `CLAUDE.md`, `STATUS.md`, the memory index), and **grep-check for dangling links**
to deleted files. `CLAUDE.md`'s "Docs — single source of truth" list is rewritten to the 12-doc map, and its
testing-surface / doc-pointer lines refreshed.

## Acceptance

1. `docs/` top level = the 12 targets + `STATUS.md`; all 15 superseded files deleted.
2. Zero dangling internal links (`grep -rn "docs/<deleted>" docs CLAUDE.md` is empty).
3. The dev↔production distinction is stated **once** canonically (`environments.md`) and linked, not restated,
   elsewhere; every efficacy number in `STATUS.md` / `results-log.md` is `[proxy]`/`[production]`-tagged.
4. No unique fact dropped — spot-check each deleted doc's key content appears in a target (or the results-log).
5. `production-guide.md` covers all 18 requirements, GroundLoop-native, each `[in place]`/`[to build]`-tagged.
6. `CLAUDE.md`'s doc list matches the actual tree.
