# Skill → Knowledge: correcting the KB distillation direction — Design

**Date:** 2026-07-13
**Status:** design (approved forks; awaiting spec review → plan)
**Supersedes the naming of:** `docs/superpowers/specs/2026-07-07-claim-centric-distilled-kb-design.md`
(the claim-centric KB) — the *pipeline* it built is kept; only the vocabulary and one reversed lane change.

## 1. Problem — the KB reads backwards

The KB's job is to **distill Skills (raw, human-authored crash-RCA / dev-experience playbooks) into
distilled *knowledge* the fix/localize loop can inject.** Today the design says that in one place and the
*opposite* in another. Grounded audit (2026-07-13, workflow `kb-direction-audit`) found the inversion lives
in three concrete spots:

1. **The flagship doc is titled backwards.** `docs/kb-distillation.md:1` = *"How the KB distills knowledge
   into Skills"*; §1 = *"how raw crash-RCA **knowledge** becomes small, injectable **Skills**"* — knowledge
   as input, Skill as output. The `CLAUDE.md` and `docs/fix-loop.md` pointers repeat it. (Meanwhile
   `docs/capabilities.md:124` already says the right thing: *"Dev-experience KB (raw Skills + claim distill)"* —
   the docs contradict themselves.)
2. **Lane A genuinely emits Skills as output.** `kb/harvest/cluster.py:candidate_from_cluster` mints a
   `Skill` dict *from* failure cases; `kb/distill/` compresses it; `gloop kb-distill` writes the result to
   `distilled.toml` and the lifecycle promotes it. This lane literally *converts cases into Skills* — the
   reverse of the intended direction, and the source of the naming confusion (a "Skill" is both the raw
   input **and** a produced output).
3. **Live behavior is effectively wrong.** Because `claims.json` (the distilled store) was never
   materialized, the only live injection path is the raw seed Skills injected wholesale
   (`skills/base.render_skills` → `## Skill: <id>` + raw guidance). So in practice the loop eats *undistilled*
   Skills, not distilled knowledge.

The good news: the **intended pipeline already exists and points the right way** — `kb/extract.py`
(`claims_from_skill(skill, model) -> list[Claim]`) decomposes a source Skill into atomic `Claim`s, and
`Claim.provenance` records *"the source Skill id it was distilled from."* It is just (a) buried under
reversed naming, (b) shadowed by Lane A, and (c) dormant (never run). This design **corrects the names,
deletes the reversed lane, and makes the distilled unit the thing the loop and the gate both use.**

## 2. The corrected model

```
  Skill (raw authored playbook, kb/data/aaos_kb_seed.toml — SOURCE ONLY)
     │
     │  gloop kb-extract   (knowledge_from_skill: LLM decompose → ground-check → admit)
     ▼
  Knowledge (atomic, grounded, single-advice unit — was: Claim; store: knowledge.json)
     │
     │  KnowledgeRegistry.select → render_knowledge  (the ONLY thing injected as the headline KB arm)
     ▼
  fix / localize loop            gloop kb-ab gates promotion on THIS arm (was: raw Skills)

  Skill.guidance → render_skills  is retained ONLY as an explicit "--skills" undistilled-baseline/control arm.
  Lane A (cases → Skill output) is DELETED.
```

**Invariant this restores:** a `Skill` is *only ever an input*. Nothing in the KB produces a Skill. The
workflow consumes **Knowledge**. The promotion gate measures **Knowledge**.

## 3. Rename map (Claim → Knowledge)

Mechanical, repo-wide. Move files with `git mv` to preserve history; rename symbols; update every importer +
test. The atlas SQLite schema is **not** touched — `knowledge.json` is a plain JSON store.

| Current | New |
|---|---|
| `groundloop/kb/claim.py` | `groundloop/kb/knowledge.py` |
| class `Claim` | class `Knowledge` |
| `CLAIMS_PATH` → `.../data/claims.json` | `KNOWLEDGE_PATH` → `.../data/knowledge.json` |
| `load_claims` / `save_claims` / `_to_claim` | `load_knowledge` / `save_knowledge` / `_to_knowledge` |
| `groundloop/kb/render.py::render_claims` + `# Grounded claims` header | `render_knowledge` + `# Grounded knowledge` |
| `groundloop/kb/registry.py::ClaimRegistry` (`.claims` attr) | `KnowledgeRegistry` (`.items` attr) |
| `groundloop/kb/extract.py::claims_from_skill` / `parse_claims` / `extract_to_store` | `knowledge_from_skill` / `parse_knowledge` / `extract_to_store` (return type `list[Knowledge]`) |
| `groundloop/kb/claim_ground.py` (ground-check) | `groundloop/kb/knowledge_ground.py` |
| `groundloop/kb/claim_placebo.py` (per-item placebo) | `groundloop/kb/knowledge_placebo.py` |
| `groundloop/kb/attribute.py` — `lofo_claims`, `screen`, `govern` (claim-granular retain-loop) | rename `claim`→`knowledge` throughout; `lofo_knowledge` |
| `fixeval/runner.py` — `self.claims`, `self.claims_tier_floor`, `claim_pre`, `selected_claims`, `fired_claims` | `self.knowledge`, `self.knowledge_tier_floor`, `knowledge_pre`, `selected_knowledge`, `fired_knowledge` |
| CLI `--claims {none,candidate,validated}` + `--claims-store` + `_load_claims` | `--knowledge {none,candidate,validated}` + `--knowledge-store` + `_load_knowledge` |
| CLI `gloop kb-extract` / `gloop kb-attribute` | same command names (they already read Skill→Knowledge); internals renamed |
| Field comment `provenance: "the source Skill id it was distilled from"` | unchanged wording (already correct) — now the *only* directional statement, and it is right |
| Data file `groundloop/kb/data/claims.json` (absent on disk today) | `knowledge.json` (still absent — cold-start) |

**Tests to move/rename with their code** (rename symbols + any `claims.json`/`--claims` literals): `tests/kb/test_claim.py`→`test_knowledge.py`, `test_claim_ground.py`→`test_knowledge_ground.py`, `test_claim_placebo.py`→`test_knowledge_placebo.py`, `test_render.py`, `test_registry.py`, `test_extract.py`, `test_cli_kb_extract.py`, `test_cli_kb_attribute.py`, `test_attribute_screen.py`, `test_attribute_govern.py`, `test_lofo_claims.py`→`test_lofo_knowledge.py` (this tests the claim-granular LOFO in `attribute.py`, which is **kept** — it is NOT the Lane-A `kb/distill/lofo` sibling), `tests/fixeval/test_runner_claims.py`, `tests/fixeval/test_cli_claims.py`.

**Do NOT confuse:** `groundloop/kb/attribute.py`'s comments reference `kb/distill/lofo.lofo_fragments`
(deleted in §4) — update the comment; `lofo_knowledge` is a self-contained reimplementation and keeps working.

## 4. Delete Lane A (the lane that makes a Skill an output)

Remove entirely — code, CLI surface, artifacts, and tests:

| Delete | Why |
|---|---|
| `groundloop/kb/harvest/` (dir: `__init__.py`, `cluster.py` — `candidate_from_cluster`, `cluster_by_signature`) | mints a `Skill` from cases (Skill-as-output) |
| `groundloop/kb/distill/` (dir: `__init__.py`, `extract.py::distill_guidance`, `lofo.py::lofo_fragments`, `revalidate.py::revalidate`) | compresses a harvested Skill's guidance |
| `gloop kb-distill` — `_run_kb_distill`, `_build_distill_run_fn`, the `kds` subparser + its dispatch (`cli/__init__.py`) | the driver for the reversed lane |
| `--skills distilled` choice + the `distilled.toml` load path (`cli/__init__.py:244`, choices list `:1118`) | injects the Lane-A output as a Skill |
| Tests: `tests/kb/test_harvest.py`, `test_lofo.py`, `test_distill_extract.py`, `test_distill_revalidate.py`, `test_cli_kb_distill.py`, `tests/fixeval/test_skills_distilled_arm.py` | cover only deleted surface |
| `groundloop/kb/provenance.py:10` GATING comment naming `harvest/`+`distill/`; `kb/data/README.md:54-55` "distilled/harvested Skill" | stale references to deleted lane |

> **Not deleted:** `tests/kb/test_lofo_claims.py` tests the *claim-granular* LOFO in `attribute.py` (kept →
> renamed in §3), not the Lane-A `kb/distill/lofo` module. `test_lofo.py` (no `_claims`) tests the deleted
> `kb/distill/lofo.lofo_fragments` → delete.

**Landmine — do not touch:** `groundloop/mine/harvest.py` (`harvest_repo`, `harvest_nondefects`,
`Candidate`) and `tests/mine/test_harvest.py` are the **GitHub issue→PR miner**, a different subsystem that
merely shares the word "harvest." Deleting "harvest" means the *KB* `kb/harvest/` only.

## 5. Retarget the promotion gate (`gloop kb-ab`) to Knowledge

Today `kb-ab` (arms `none/kb/placebo`, `kb/ab.py`) injects **raw seed Skills** wholesale via
`MockSkillRegistry` — it gates on undistilled *source*. Corrected so the gate measures the **same distilled
artifact the loop injects**:

- `kb/ab.py::_make_arm` builds a **`KnowledgeRegistry`** over `knowledge.json` (candidate tier floor for
  eval) for the `kb` arm, and a **knowledge-granular placebo** (from `knowledge_placebo.py`: same
  `applies_when`+`type`, scrambled `content`) for the `placebo` arm; `none` = no injection. `run_ab` threads
  the registry into `FixEvalRunner(knowledge=..., knowledge_tier_floor="candidate")` (the `--knowledge` path),
  not `skills=`.
- **Honest cold-start:** `knowledge.json` is empty until `gloop kb-extract` runs, so on an empty store all
  three arms are byte-identical (no knowledge selected) — the A/B is only meaningful *after* extraction. This
  is stated in the doc and asserted in a test, mirroring the existing "empty `validated` set selects nothing"
  honesty.
- `PLACEBO_SEED`/`placebo.toml` (a *Skills* placebo) is retained **only** for the raw `--skills placebo`
  baseline arm; the Knowledge A/B uses the knowledge-granular placebo.

**Retained as the undistilled baseline (renamed nowhere, pointed right):** `--skills {none,mock,kb,placebo}`
(minus `distilled`) still injects raw source Skills via `render_skills` — an explicit control you can run, but
**not** what the retain-loop promotes. `render_skills`, `skills/base.py`, `MockSkillRegistry` stay.

## 6. Docs to rewrite (the naming lives here)

- **`docs/kb-distillation.md`** — retitle **"How the KB distills Skills into knowledge"**; rewrite §1/§2 so
  `Skill` = raw source and `Knowledge` (was Claim) = the distilled, injectable unit; drop all Lane-A
  (harvest/distill/kb-distill/distilled.toml) sections; update the injection/§6 and status/§8 sections to the
  Knowledge names and the "kb-ab gates on Knowledge" flow.
- **`CLAUDE.md`** — the `docs/kb-distillation.md` pointer line (currently *"how the KB distills knowledge into
  Skills"*) → *"how the KB distills Skills into knowledge"*; update the Type-2 `skills/`+`kb/` description if it
  implies Skill-as-output.
- **`docs/fix-loop.md`** — the KB pointer + §5 dev-experience-KB wording; `--claims` → `--knowledge`.
- **`docs/capabilities.md`** — the KB row (already "raw Skills + claim distill") → "raw Skills + **knowledge**
  distill"; drop any `kb-distill` capability entry.
- **`docs/workflows.md`** — the per-stage feature map row `Claim-centric KB injection` → Knowledge names +
  `fixeval --knowledge {candidate,validated}`.
- **`groundloop/kb/data/README.md`** — Skill = feedstock/source, distillation produces Knowledge; drop
  distilled/harvested-Skill language.
- **`docs/STATUS.md`** / **`docs/results-log.md`** — light touch: note the rename + Lane-A removal (results
  entries are historical; do not rewrite past `[proxy]` numbers, just annotate the vocabulary change).
- **Memory** (`/home/vinc/.claude/projects/-mnt-x-code-GroundLoop/memory/`): update `claim-centric-kb.md`,
  `type2-kb-feedstock.md`, `kb-reverdict.md`, `provisional-core-loop-closure.md` to the Skill→Knowledge
  vocabulary + Lane-A removal; add MEMORY.md pointer for this correction.

## 7. Non-goals / guardrails

- **Never edit `groundloop/core/`** — the KB lives entirely in `kb/`, `adapters/skills/`, `fixeval/`, `cli/`.
- **Never alter the atlas SQLite schema** (`engines/atlas/store.py`) — untouched; `knowledge.json` is JSON.
- **No behavior/measurement change beyond the rename + Lane-A deletion + the kb-ab retarget.** We are not
  running extraction, not producing knowledge, not making claims about efficacy. The KB stays **Candidate /
  unproven** ([[kb-reverdict]]); this is a *naming + surface* correction, not an effectiveness result.
- **`mine/harvest.py` is out of scope** (see §4 landmine).
- Preserve the honest cold-start everywhere: an empty `knowledge.json` selects nothing and every arm is
  byte-identical to `none`.

## 8. Acceptance criteria

1. `rg -n '\bClaim\b|ClaimRegistry|render_claims|claims_from_skill|CLAIMS_PATH|--claims\b|claims\.json' groundloop tests`
   returns **nothing** (all renamed to Knowledge). `grep` for `Knowledge`/`knowledge.json`/`--knowledge`
   resolves in the renamed modules.
2. `groundloop/kb/harvest/`, `groundloop/kb/distill/`, `gloop kb-distill`, the `--skills distilled` choice, and
   `distilled.toml` **no longer exist**; `gloop --help`/`gloop fixeval --help` list no `kb-distill`/`distilled`.
3. `groundloop/mine/harvest.py` is **byte-identical** to pre-change (untouched).
4. `gloop kb-ab` injects Knowledge (via the `--knowledge` path) for its `kb` arm; on an empty `knowledge.json`
   all arms are byte-identical (asserted by a test); a fixture-populated store makes `kb` differ from `none`.
5. `docs/kb-distillation.md` title reads "…distills **Skills into knowledge**"; no doc or `CLAUDE.md` line
   states knowledge→Skills; `capabilities.md`/`workflows.md`/`fix-loop.md` use the Knowledge vocabulary and
   list no `kb-distill`.
6. **Full `pytest -q` green + `ruff check groundloop tests` clean** before any commit. The Type-1 hermetic
   invariants (`tests/test_invariants.py`) and the anti-leak red-tests still pass.
7. `git log --follow groundloop/kb/knowledge.py` shows continuity from `kb/claim.py` (history preserved via
   `git mv`).

## 9. Execution shape

One subagent-driven plan (docs + code together), TDD, two-stage review per task, on a feature branch. Rough
task decomposition the plan will detail:

1. **Rename the core type** — `git mv claim.py knowledge.py`; `Claim`→`Knowledge`, store fns, `KNOWLEDGE_PATH`;
   update `kb/__init__.py` exports + `test_claim.py`→`test_knowledge.py`. (Green gate.)
2. **Rename the consumers** — `render.py`, `registry.py`, `extract.py`, `knowledge_ground.py`,
   `knowledge_placebo.py`, `attribute.py` + their tests.
3. **Rename the runtime arm** — `fixeval/runner.py` (`self.knowledge`…), CLI `--knowledge`/`_load_knowledge`,
   `kb-extract`/`kb-attribute` internals + tests.
4. **Delete Lane A** — `kb/harvest/`, `kb/distill/`, `kb-distill` CLI, `--skills distilled`, `distilled.toml`,
   their tests, stale comments.
5. **Retarget kb-ab to Knowledge** — `kb/ab.py::_make_arm` + `run_ab` thread a `KnowledgeRegistry`; add the
   empty-store byte-identical test + the fixture-populated differ test.
6. **Docs + memory** — rewrite `kb-distillation.md` (retitle), fix `CLAUDE.md`/`fix-loop.md`/`capabilities.md`/
   `workflows.md`/`README.md`/`STATUS.md`/`results-log.md`; update the four KB memories + MEMORY.md pointer.
7. **Final sweep** — the acceptance-criteria greps as a guard test; full suite + ruff; final review.
