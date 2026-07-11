# Docs Optimization + Dev↔Production Distinction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax. This is a **docs-only** plan — no code, no tests to
> run. "Verification" per task = read-back + a link/fact check, not pytest.

**Goal:** Consolidate `docs/` from 23 top-level files to 12; make the dev↔production distinction canonical
(one `environments.md` + a `[proxy]`/`[production]` tag convention); add the new `production-guide.md` SOP.

**Spec:** `docs/superpowers/specs/2026-07-11-docs-optimization-design.md` (read it — it has the full target map,
the `environments.md` content, the 18-section `production-guide.md` structure, and the acceptance checks).

**Global rules (every task):**
1. **Never restate the dev↔prod distinction** — link to `environments.md` instead.
2. **Tag every efficacy number** `[proxy]` (mechanism/regression, dev box) or `[production]` (efficacy, GEI).
3. **GroundLoop-native + preserve every unique fact** — merge/relocate, don't invent, don't drop. Trim only
   genuine redundancy.
4. **Do NOT delete any source file** — all `git rm` deletions + cross-link fixes happen in the final Task 11.
5. Keep the repo's voice (terse, technical, em-dashes). Match existing doc tone.

**Ordering:** Task 1 (`environments.md`) first — everything else links to it. Tasks 2–10 create/edit targets
(reading sources, not deleting). Task 11 deletes the 16 sources + realigns CLAUDE.md/cross-links last.

---

## Task 1: `environments.md` (NEW — the canonical dev↔production contract)

**Files:** Create `docs/environments.md`. Read for source material: `docs/workflow.md` (§ oracle-blindness,
§ evaluation workflow), `docs/groundloop-testing-strategy.md` (§1 two test surfaces), `docs/STATUS.md`
(the scattered proxy/production reminders), `docs/2026-07-11-functional-10case-e2e-findings.md` (the
production-only framing).

- [ ] **Write `docs/environments.md`** (~60–80 lines) with exactly these parts (spec §2):
  - **2a. Two-environments table** — columns *Dev box (OSS proxy)* vs *Production (real GEI)*; rows: what it is
    (`atlas-9.db`/`corpora-local` vs 19-repo GEI atlas + JIRA↔Gerrit oracle 10-case/406) · reachable? (yes vs
    **no, production-only**) · what runs (Type-1 hermetic + Type-2-on-proxy vs Type-2-on-GEI + deployed loop +
    feedback) · what numbers mean (**mechanism/regression, not efficacy** vs **efficacy — the scoreboard**) ·
    anchor doc (`evaluation.md` vs `production-guide.md`).
  - **2b. The develop-against-feedback loop** — build on proxy → ship to `master` → production runs the real
    evals → numbers + failure cases feed back → iterate. "Production is the oracle of record."
  - **2c. The labeling convention** — define `[proxy]` and `[production]`; state the rule (no bare efficacy
    number anywhere; always tagged) with the worked example "functional recall@1 **0.68 `[proxy]`** →
    **0.10 `[production]`**".
  - **2d. Standing lesson + reuse contract** — the proxy is optimistic (0.68→0.10 size bias); the reuse
    contract (pinned atlas SHAs, `bge-m3` pin, model pins, shared `atlas.db` path, unchanged schema).
- [ ] **Verify:** the doc stands alone (a newcomer learns the split from it), all four parts present, the two
  tags defined once. No source deleted.
- [ ] **Commit:** `git add docs/environments.md && git commit -m "docs(environments): canonical dev<->production contract + [proxy]/[production] tag convention"`

---

## Task 2: `production-guide.md` (NEW — the production SOP; largest doc)

**Files:** Create `docs/production-guide.md`. Read: `docs/production-migration.md` (absorb its checklist +
affinity/oracle/LOO/self-scoring content), `docs/2026-07-11-functional-10case-e2e-findings.md` (the failure-case
shape for §11), and spec §3 (the authoritative 18-section outline).

- [ ] **Write `docs/production-guide.md`** — the 18 requirements from spec §3, organized into 3 parts, each item
  in GroundLoop terms and tagged `[in place]` / `[to build]`:
  - **Part A — Deploy & operate:** §1 Requirements · §2 Install & configure · §3 Startup/shutdown (**honest
    note: batch/CLI, not a daemon**) · §4 Deployment verification · §5 Production usage. (Fold in the whole of
    `production-migration.md`'s checklist + build steps here.)
  - **Part B — Validate:** §6 Functional (10-case/406 via `grade-run`, `by_bug_kind`) · §7 Performance
    (latency + `$/solved`; GPU-OOM out-of-scope, gateway-side) · §8 Stability (gateway/ext4/CBM/v9fs).
  - **Part C — Feedback → development:** §9 Usage data (no PII — tie to secret-hygiene) · §10 Quality feedback
    (mapped: correct=recall@1, hallucination=fabrication_rate, retrieval=file_recall, completeness=resolved_rate,
    trust=abstention) · §11 Failure cases · §12 Knowledge gaps (`CpAccessibilityManager`/`XCUSBMediaService`) ·
    §13 User feedback · §14 Dev-feedback data (the loop back to dev) · §15 Submission format · §16 Review
    process · §17 Release tracking (atlas SHA/model/affinity pins; rollback) · §18 Success criteria.
  - **The canonical record** (a fenced block, shared by §11 + §15, `*` = auto-emitted by `grade-run`) exactly as
    in spec §3.
  - A one-line header pointer: "Production side of the two environments — see `environments.md`."
- [ ] **Verify:** all 18 covered; every item tagged `[in place]`/`[to build]`; the canonical record present;
  every `production-migration.md` fact preserved (spot-check the checklist + the affinity/LOO/self-scoring
  commands survive). No source deleted.
- [ ] **Commit:** `git add docs/production-guide.md && git commit -m "docs(production-guide): production deploy/validate/feedback SOP (18 sections, GroundLoop-native, gap-tagged)"`

---

## Task 3: `results-log.md` (NEW — the 7 findings → one env-tagged log)

**Files:** Create `docs/results-log.md`. Read all seven: `docs/2026-07-06-first-evaluation.md`,
`2026-07-07-claim-kb-preview-findings.md`, `2026-07-07-plan-format-phase3-findings.md`,
`2026-07-09-android-log-match-v2-findings.md`, `2026-07-10-component-routing-findings.md`,
`2026-07-10-functional-bug-match-findings.md`, `2026-07-11-functional-10case-e2e-findings.md`.

- [ ] **Write `docs/results-log.md`** (spec §4): a reverse-chronological log — a summary table
  (`| date | track | env | headline |`) then one compact block per result (≤ ~8 lines): date · track · env tag ·
  headline number(s) · one-line takeaway · a **git pointer** to the original findings doc path + the relevant
  commit(s). Every number carries `[proxy]` / `[production]`. Preserve each finding's headline result + its key
  caveat; deep detail is intentionally left to git history.
- [ ] **Verify:** all 7 results present in the table + as blocks; each number tagged; each block names its
  now-deleted source path so a reader can `git log` it. No source deleted (Task 11 deletes the findings).
- [ ] **Commit:** `git add docs/results-log.md && git commit -m "docs(results-log): fold 7 dated findings into one env-tagged chronological log"`

---

## Task 4: `guide.md` (NEW — merge the how-to guides)

**Files:** Create `docs/guide.md`. Read: `docs/user-guide.md` (the spine — deploy/setup/run/migrate),
`docs/workflow.md` (§ closed loop, § where each stage stands), `docs/application-guide.md` (§ application
workflow, § scenarios).

- [ ] **Write `docs/guide.md`** — the single "how to use it" doc: what you deploy → prereqs → project setup →
  build the oracle/atlas → run the pipeline (`gloop run`/`grade-run`) → adapter swap map → hermetic vs
  gated-live → migration checklist → known seams. Pull the operational content from `user-guide.md`, the
  "closed loop / stage status" narrative from `workflow.md`, and the scenarios from `application-guide.md`.
  **Link, don't restate:** dev/prod → `environments.md`; deep eval detail → `evaluation.md`; production ops →
  `production-guide.md`; atlas-build gotchas → `build-setup.md`.
- [ ] **Verify:** covers deploy+run+migrate end-to-end; no dev/prod re-explanation (links instead); every unique
  operational fact from the three sources survives. No source deleted.
- [ ] **Commit:** `git add docs/guide.md && git commit -m "docs(guide): single deploy+run+migrate how-to (merges user-guide/workflow/application-guide)"`

---

## Task 5: `charter.md` (EDIT — absorb application-guide overview; trim)

**Files:** Modify `docs/charter.md`. Read: `docs/application-guide.md` (§1 one-system-two-uses, §3 scenarios,
§7 scope).

- [ ] **Edit `charter.md`:** fold in "one system, two uses (bridged by a hidden oracle)" + the scope/non-goals
  from `application-guide.md` where charter doesn't already cover them; replace any dev/prod framing with a link
  to `environments.md`; trim restated mission/metrics prose. Keep FR/NFR, the 4 stages, metrics, glossary.
- [ ] **Verify:** charter still complete; the application-guide's unique overview points are present here or in
  `guide.md`; dev/prod is linked not restated. No source deleted.
- [ ] **Commit:** `git add docs/charter.md && git commit -m "docs(charter): absorb application-guide overview; link environments; trim"`

---

## Task 6: `architecture.md` (EDIT — absorb workflow internals; trim)

**Files:** Modify `docs/architecture.md`. Read: `docs/workflow.md` (§ stage by stage, § under the hood: atlas
index & embedding).

- [ ] **Edit `architecture.md`:** ensure the 8-stage `run_ticket` walk-through and the atlas-index/embedding
  internals from `workflow.md` are captured here (architecture already has the pipeline + ports; add any unique
  "under the hood" detail). Link dev/prod + oracle-blindness to `environments.md`. Trim redundancy.
- [ ] **Verify:** the ports + control plane + the workflow's stage/atlas internals are all here; nothing unique
  from `workflow.md`'s technical sections is lost (the rest of workflow.md goes to `guide.md`/`environments.md`).
- [ ] **Commit:** `git add docs/architecture.md && git commit -m "docs(architecture): absorb workflow stage/atlas internals; link environments; trim"`

---

## Task 7: `evaluation.md` (RENAME type2-evaluation + merge testing-strategy)

**Files:** `git mv docs/type2-evaluation.md docs/evaluation.md`, then modify. Read:
`docs/groundloop-testing-strategy.md` (all — esp. §1 two test surfaces, §2 Type-1, §3 Type-2).

- [ ] **Rename + merge:** `git mv type2-evaluation.md evaluation.md`. Fold `groundloop-testing-strategy.md` in —
  especially the **Type-1 (hermetic dev) vs Type-2 (eval)** two-surface framing (which pairs with
  `environments.md`) and the reuse-contract/substrate sections not already in type2-evaluation. Retag every
  reported number `[proxy]`/`[production]`. Link the dev↔prod contract to `environments.md`.
- [ ] **Verify:** the eval bible now also carries the two-test-surface material; numbers tagged; testing-strategy's
  unique content (Type-1 surface, reuse map, non-goals) preserved. No source deleted (Task 11 removes
  testing-strategy).
- [ ] **Commit:** `git add -A && git commit -m "docs(evaluation): rename type2-evaluation -> evaluation; merge testing-strategy; tag numbers"`

---

## Task 8: `build-setup.md` (NEW — merge the 3 build/setup docs)

**Files:** Create `docs/build-setup.md`. Read: `docs/m1-index-build.md`, `docs/type2-eval-setup.md`,
`docs/type2-atlas-build-findings.md`.

- [ ] **Write `docs/build-setup.md`:** the operational build/setup runbook — pointing GroundLoop at an atlas.db,
  building a new atlas.db (`gloop index`/`build-atlas`), env-var reference, the reuse contract, the gated-live
  setup, and the **atlas-build gotchas** (the Findings 1–10 from `type2-atlas-build-findings.md`: CBM timeout,
  one-index-at-a-time, `pgrep -fa` not `ps -C`, exclude test/3party, ext4 not v9fs, per-case materialization).
  Move the "first real eval" dated findings out to `results-log.md` if not already there (coordinate: those are
  a Task-3 candidate — reference, don't duplicate). Link dev/prod to `environments.md`.
- [ ] **Split `type2-atlas-build-findings.md` explicitly:** its **Findings 1–10** (build gotchas) → this
  `build-setup.md`; its two **dated `2026-07-05` result sections** ("First real eval — matcher & dataset
  findings", "Real testing achieved — synthesized failure-log dataset") → **append to `results-log.md`**
  (which exists from Task 3), env-tagged `[proxy]`. Do not duplicate them here.
- [ ] **Verify:** all env vars, the reuse contract, and every gotcha survive here; the two 2026-07-05 results
  now live in `results-log.md`; the gated-live steps are runnable. No source deleted.
- [ ] **Commit:** `git add docs/build-setup.md && git commit -m "docs(build-setup): merge m1-index-build + type2-eval-setup + atlas-build gotchas"`

---

## Task 9: `fix-loop.md` (RENAME downstream-fix-loop + merge skill-kb-migration)

**Files:** `git mv docs/downstream-fix-loop.md docs/fix-loop.md`, then modify. Read:
`docs/skill-kb-migration.md`.

- [ ] **Rename + merge:** `git mv downstream-fix-loop.md fix-loop.md`. Append/fold the KB Skills migration guide
  (`skill-kb-migration.md`) as a section (the KB is a measured fix-loop arm). Link dev/prod to `environments.md`;
  tag any numbers.
- [ ] **Verify:** the fix-loop design provenance + the KB migration/parity content both present. No source
  deleted (Task 11 removes skill-kb-migration).
- [ ] **Commit:** `git add -A && git commit -m "docs(fix-loop): rename downstream-fix-loop -> fix-loop; merge skill-kb-migration"`

---

## Task 10: `engines.md` + `roadmap.md` + `STATUS.md` (EDIT — trim + tag)

**Files:** Modify `docs/engines.md`, `docs/roadmap.md`, `docs/STATUS.md`.

- [ ] **`engines.md`:** trim redundancy; link dev/prod to `environments.md`; keep the produce/lore/CBM/atlas ops.
- [ ] **`roadmap.md`:** trim; retag numbers `[proxy]`/`[production]`; link `environments.md`.
- [ ] **`STATUS.md`:** trim; **retag every efficacy number** `[proxy]`/`[production]` (this is where most bare
  numbers live); replace dev/prod prose with a link to `environments.md`. Keep the Done/Next structure.
- [ ] **Verify:** the three docs are tighter, every number tagged, dev/prod linked not restated.
- [ ] **Commit:** `git add docs/engines.md docs/roadmap.md docs/STATUS.md && git commit -m "docs(status/roadmap/engines): trim, tag numbers [proxy]/[production], link environments"`

---

## Task 11: Delete sources + realign CLAUDE.md + cross-links (FINAL)

**Files:** `git rm` the 16 sources; modify `CLAUDE.md`; fix any remaining cross-links across `docs/**`.

- [ ] **Delete the 16 superseded sources:** `git rm docs/application-guide.md docs/user-guide.md
  docs/workflow.md docs/groundloop-testing-strategy.md docs/m1-index-build.md docs/type2-eval-setup.md
  docs/type2-atlas-build-findings.md docs/skill-kb-migration.md docs/production-migration.md
  docs/2026-07-06-first-evaluation.md docs/2026-07-07-claim-kb-preview-findings.md
  docs/2026-07-07-plan-format-phase3-findings.md docs/2026-07-09-android-log-match-v2-findings.md
  docs/2026-07-10-component-routing-findings.md docs/2026-07-10-functional-bug-match-findings.md
  docs/2026-07-11-functional-10case-e2e-findings.md`
- [ ] **Rewrite `CLAUDE.md`'s "Docs — single source of truth" list** to the 12-doc map (add `environments.md`,
  `production-guide.md`, `results-log.md`, `guide.md`, `build-setup.md`, `evaluation.md`, `fix-loop.md`; drop
  the deleted ones). Refresh the testing-surface + doc-pointer lines to the new names.
- [ ] **Fix cross-links:** `grep -rn "application-guide\|user-guide\|workflow\.md\|groundloop-testing-strategy\|
  m1-index-build\|type2-eval-setup\|type2-atlas-build-findings\|skill-kb-migration\|production-migration\|
  type2-evaluation\|downstream-fix-loop\|2026-07-0\|2026-07-10-\|2026-07-11-functional-10case" docs CLAUDE.md`
  and repoint every hit to the new target (or the results-log). Also update the memory index pointer at
  `/home/vinc/.claude/projects/-mnt-x-code-GroundLoop/memory/MEMORY.md` if it names a deleted doc.
- [ ] **Verify (acceptance, spec §Acceptance):** `docs/` top level = the 12 targets; the dangling-link grep is
  empty; every efficacy number in `STATUS.md`/`results-log.md` is tagged; `CLAUDE.md`'s list matches
  `ls docs/*.md`; spot-check one fact from each deleted doc appears in a target.
- [ ] **Commit:** `git add -A && git commit -m "docs: delete 16 superseded docs; realign CLAUDE.md doc list + cross-links (23 -> 12)"`

---

## Verification (end-to-end acceptance)

1. **Count:** `ls docs/*.md` = 12 files (environments, charter, architecture, guide, evaluation, build-setup,
   fix-loop, engines, production-guide, roadmap, results-log, STATUS).
2. **Canonical distinction:** `environments.md` defines `[proxy]`/`[production]` once; a grep shows other docs
   *link* to it rather than re-explaining the split.
3. **No dangling links:** the Task-11 grep over `docs` + `CLAUDE.md` returns nothing.
4. **Tagging:** no bare efficacy number in `STATUS.md` / `results-log.md`.
5. **Production SOP:** `production-guide.md` covers all 18, each `[in place]`/`[to build]`-tagged, with the
   canonical record.
6. **Nothing lost:** each deleted doc's headline facts are traceable to a target (or the results-log + git).

## Critical files

- New: `docs/{environments,production-guide,results-log,guide,build-setup}.md`.
- Renamed: `type2-evaluation.md`→`evaluation.md`, `downstream-fix-loop.md`→`fix-loop.md`.
- Edited: `docs/{charter,architecture,engines,roadmap,STATUS}.md`, `CLAUDE.md`.
- Deleted (16): listed in Task 11.
- Spec: `docs/superpowers/specs/2026-07-11-docs-optimization-design.md`.
