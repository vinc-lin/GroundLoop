# How the KB distills Skills into knowledge

> **What this doc is.** A code-grounded guide to GroundLoop's dev-experience **Knowledge Base (KB)** — how raw
> crash-RCA **Skills** (authored playbooks) are distilled into small, injectable **Knowledge** items, and the
> *retain-loop* that admits one only on **measured lift**. It is the "how it works" companion to
> [`fix-loop.md`](fix-loop.md) (design provenance) and [`capabilities.md`](capabilities.md) (governance state).
>
> **The direction, stated once.** A `Skill` is *only ever an input* — raw, human-authored feedstock. Nothing in
> the KB produces a Skill. The distilled unit the fix/localize loop injects, and the promotion gate measures, is
> **Knowledge** (formerly `Claim`).
>
> **Read this caveat first.** The distillation machinery below is **fully built and structurally correct**, but
> **nothing has been validated yet** — all 12 seed Skills sit at cold-start `candidate` tier, no `Knowledge`
> item has ever been extracted or promoted, and the KB's *efficacy* verdict is **production-gated** (see §7 and
> [`kb-reverdict`](capabilities.md#candidate--dev-labs-research-blocked-on-a-first-production-read)). This guide
> documents the *mechanism*, not a proven result. The KB is a **Candidate** fix arm, never default-on.

---

## 1. The one-sentence idea

A **Skill** is a tiny, repo-agnostic crash-fixing playbook — raw dev experience captured verbatim. The KB's
job is to **distill each Skill into atomic Knowledge** that is (a) **grounded** — every code entity it names
actually exists — (b) **oracle-blind** — it never encodes which repo owns a bug — and (c) **earned** — a
Knowledge item only enters the injected set, or climbs a tier, after an A/B measurement shows it *helps*.
Everything else in this doc is how those three properties are enforced mechanically.

**Core principle (the project ethos, applied to the KB):** *distrust unverified prose.* A Skill's authored
guidance is treated as a hypothesis, not a fact — it is decomposed into checkable Knowledge, injected into the
fix loop only behind a gate, and kept only if reality (a passing fix-eval) confirms it.

---

## 2. The two primitives — Skill (raw source) and Knowledge (distilled unit)

### 2a. `Skill` — the raw authored source (input only)

`groundloop/skills/base.py:10-17` — a frozen dataclass. A Skill is the **feedstock**: what a developer wrote,
never a KB output.

```python
@dataclass(frozen=True)
class Skill:
    id: str
    applies_to: Callable[[object], bool]   # WHEN it fires — a compiled predicate over a SkillCtx
    guidance: str                          # the playbook text (the ONLY field that reaches a prompt)
    hint_apis: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()          # retrieval keys / tags
    provenance: str = ""                   # source RCA / commit — kept for traceability, never trusted
```

- **`applies_to` is data, not code.** It is compiled by `compile_predicate(spec)`
  (`skills/predicate.py:18`) from a **declarative** `[skill.match]` TOML block — closed vocabulary only (an
  unknown key raises), no `eval`/`exec`, regexes compiled eagerly. Clauses within a block are **OR'd**; the
  families are `packages / classes / methods / symbols / libraries / errors`, with literal (`any_text`),
  AND-escape-hatch (`all_text`), and regex (`any_text_regex`) forms. So a Skill "fires" on a case purely by
  matching signal/log text — it is a pattern, and stays reviewable.
- **It evaluates against a `SkillCtx`** (`skills/ctx.py`): the arm-extracted `signals`, the loop's
  **predicted** owning repo (never the oracle), and a lowercased haystack of summary + description + all log
  content. The context "NEVER reads `_oracle/`."
- **The raw Skill is injected only as an explicit undistilled baseline arm.** `render_skills(selected)`
  (`base.py:30-34`) emits `## Skill: <id>` + `s.guidance` — the `--skills` control (§5). It is *not* what the
  retain-loop promotes; that is Knowledge.

### 2b. `Knowledge` — the distilled, injectable unit (was `Claim`)

`groundloop/kb/knowledge.py:27` — the smallest checkable unit of advice, extracted **from** a source Skill.
This is the headline thing the loop injects and the gate measures.

```python
@dataclass(frozen=True)
class Knowledge:
    id: str
    applies_when: dict                 # a [skill.match]-style predicate: WHEN this Knowledge item fires
    type: str                          # "localize_hint" | "fix_step" | "api_requirement"
    content: str                       # the ONE thing it advises (this text enters the plan prompt)
    grounding_refs: tuple[str, ...]    # code entities it asserts exist (checkable in the atlas)
    provenance: str                    # the source Skill id it was distilled from — kept, never trusted
    tier: str                          # candidate | validated | canonical | retired
    evidence: dict = ...               # lifecycle bookkeeping
```

`Knowledge` carries its **own** firing predicate (`applies_when`) and records, in `provenance`, *the source
Skill id it was distilled from* — the one directional statement in the whole KB, and it is right (Skill →
Knowledge). It persists in a machine-updated JSON store (`groundloop/kb/data/knowledge.json`, keyed by id); the
retain-loop mutates only `tier` + `evidence`, while the human-authored feedstock stays the source Skills.

---

## 3. The feedstock corpora (the Skill source)

| Corpus | Count | Arm | Path |
|---|---|---|---|
| `adapters/skills/data/aaos_playbooks.toml` | 4 | `--skills mock` (the SP3 seed) | `MockSkillRegistry` `SEED_PATH` |
| **`kb/data/aaos_kb_seed.toml`** | **12** | `--skills kb` (the real feedstock) | `KB_SEED` |
| `kb/data/placebo.toml` | 12 | `--skills placebo` (the raw-Skill null control) | `PLACEBO_SEED` |

The 12 KB seed Skills cover the AAOS crash taxonomy (native SEGV/abort, foreground-service, fragment-lifecycle
NPE, ISE-after-save, binder-too-large, audio underrun, media-player state, camera/GL surface, ANR,
CME/race, native-lib load). Each `[[skill]]` carries `id`, `provenance`, `signals`, `hint_apis`, a `guidance`
string with three mandatory clauses (`Signature:` / `Localize:` / `Fix:`), and the `[skill.match]` predicate.
**These are the raw source `kb-extract` distills — never a produced artifact.**

**Every corpus passes a validator** (`kb/validate.py`, `validate_corpus`) with two hard gates:
1. **Closed-vocab conformance** — the predicate uses only the allowed keys, and it **forbids** `always` /
   `repo_in` (a repo-pinned or always-on Skill is a lookup-table row / overfit) and requires all three
   `Signature:/Localize:/Fix:` clauses.
2. **Leak red-test** — `owner_denylist()` builds the set of every fleet repo short-name / namespace / slug /
   `.so`; any such token appearing in `guidance` / `signals` / `hint_apis` / `match` is a **LEAK** and fails
   the corpus. Generic dependency tokens (`android.`, `androidx.`, sonames) are deliberately *kept* — only
   *owner-identifying* tokens are banned. This is what makes the source oracle-blind by construction.

---

## 4. Distillation — `Skill → Knowledge` (extract → ground-check → admit)

The KB distills each source Skill into **atomic Knowledge** — the smallest checkable unit of advice. Driver:
`gloop kb-extract` (`kb/extract.py`).

1. **Extract (LLM proposes)** — `knowledge_from_skill(skill, model)` (`kb/extract.py:78`) runs a model over
   each Skill's guidance, asking for `{knowledge:[{type, content, grounding_refs, applies_when}]}` and to
   "name NO product/repo/vendor identifiers." `parse_knowledge` is tolerant — returns `[]` on any malformed
   output, **never raises**. The LLM is a **proposer only**; nothing it says is trusted yet.
2. **Ground-check (deterministic gate)** — `check_knowledge_grounded` (`kb/knowledge_ground.py:89`) admits an
   item only if it has **zero** reasons to reject: (a) **well-formed** (valid `type`, non-empty content, a
   *compilable* `applies_when`); (b) **grounded** — every `grounding_ref` resolves **fleet-wide** in the atlas
   via a whole-identifier boundary match (recall by keyword, then require the full token verbatim, defeating
   hallucinated qualified/snake refs riding on a real subtoken); (c) **leak-safe** — no fleet-owner token.
   Checking existence *fleet-wide* is what keeps it oracle-blind: "reveals nothing about WHICH repo owns the
   defect." Survivors persist to `knowledge.json` at `tier=candidate` (via `extract_to_store`).
3. **Attribute / retain** — `gloop kb-attribute` (§6) runs the retain loop one Knowledge item at a time. A
   `candidate` item is gated *out* of a production run until it earns promotion.

---

## 5. Injection — how Knowledge reaches the fix, and the metric gotcha

All injection happens in `FixEvalRunner._one` (`fixeval/runner.py`), **after** Stage-1 match picks a
`predicted` repo, keyed on arm signals + predicted repo (oracle-blind). There are **two arms**, injected as a
fix-prompt preamble via `fixer.with_preamble(...)`:

- **`render_knowledge(selected_knowledge)` — the headline distilled arm (`--knowledge`).** Each Knowledge
  item's `content` is emitted as a single bullet under a fixed `# Grounded knowledge` header
  (`kb/render.py:18`). Selection is `KnowledgeRegistry.select(ctx, tier_floor)` (`kb/registry.py:38`) — fires
  only items whose `applies_when` matches and whose `tier` clears the floor. An empty selection renders `""` —
  a byte-identical no-op versus the `none` arm.
- **`render_skills(selected)` — the raw undistilled baseline (`--skills`).** Prepends the whole `guidance` of
  each matching source Skill (`## Skill: <id>`). This is a retained **control** — an explicit "what does the
  undistilled source do?" arm — **not** what the retain-loop promotes.

**The localize channel — `--skills-inject {both, fix-only}`** (raw-Skill arm only):
- `both` (default): raw Skills feed **both** the localize retrieval query (`_skill_query`) and the fix preamble.
- `fix-only`: the localize query is forced empty → `localize(...)` is **byte-identical to the `none` arm**, so
  Skills feed *only* the fix/plan prompt. **Knowledge is always preamble-only, so `--knowledge` is inherently
  localize-invariant** (it never touches the localize query).

**The gotcha (why this matters).** In `_one`, **localize runs before fix**. A fix-stage injection therefore
*cannot* change `file_recall@1` (scored off localize). For `--knowledge` this is structural; for `--skills`
under `fix-only` it is *provable* — the localize query is empty. So the KB must be graded on
**`resolved_rate` / `patch_applies` / `fabrication_rate`**, never `file_recall@1`. Grading the KB on a localize
metric is exactly the mistake that produced the discredited "KB null" (§7).

---

## 6. The retain-loop — "admit only on verified lift"

Nothing enters the injected set, or climbs a tier, on authorship alone. Two drivers gate it, both over
**Knowledge**.

### 6a. `gloop kb-attribute` — the per-item retain loop

`attribute_and_govern` (`kb/attribute.py:144`) runs the loop one Knowledge item at a time:
- **`screen_knowledge`** (`attribute.py:51`) — a cheap, oracle-blind **directional screen** over the plan
  archive's per-case `groundedness` + `patch_applies` → a shortlist (correlational; prioritizes, never
  promotes; no new spend).
- **`lofo_knowledge`** (`attribute.py:79`) — **leave-one-item-out** ablation Δ (the knowledge-granular LOFO):
  keep an item iff removing it *strictly lowers* the measured lift.
- **placebo-swap A/B** — the shortlisted item vs a same-firing-set knowledge placebo
  (`build_knowledge_placebo`, `kb/knowledge_placebo.py:27`: same `applies_when`+`type`, scrambled `content`),
  gated by the two-sided `accept_grounded` (`fixeval/compare.py`) → **`apply_verdict`** promotes one rung on
  pass; at the bottom rung a failing streak **retires** the item permanently.

### 6b. `gloop kb-ab` — the promotion gate (retargeted to Knowledge)

`run_ab` (`kb/ab.py`) reruns the whole fix-eval for arms `none / kb / placebo`, injecting **Knowledge** at the
fix stage (candidate floor) via `FixEvalRunner(knowledge=..., knowledge_tier_floor="candidate")` — **not** raw
Skills. The `kb` arm is the distilled Knowledge over `knowledge.json`; `placebo` is the per-item
length-matched irrelevant control that fires on the identical cases; `none` is no injection. Any lift the real
Knowledge shows **over the placebo** isolates the *content* from the mere fact that *something* fired.
`grade_fix_all` is the sole oracle read.

**Honest cold-start.** `knowledge.json` is empty until `gloop kb-extract` runs, so on an empty store all three
arms select nothing and are **byte-identical to `none`** — the A/B is only meaningful *after* extraction
(asserted in `tests/kb/test_kb_ab_retarget.py`).

**The acceptance gate** — `strengthened_accept` (`kb/accept.py`) admits a set only if **all** hold:
- `pos_ok` — Δ`file_recall@1` > 0 **or** `newly_solved > newly_broken`;
- `honesty_ok` — Δ`fabrication_rate` ≤ 0 (never buy resolution with more fabrication);
- `phi_ok` — Δφ_c ≥ 0 at **every** risk-aversion c ∈ {0.5, 1.0, 2.0} (no regression in effective reliability);
- `wilson_lo > 0` — the Wilson-95 lower bound of `newly_solved/(newly_solved+newly_broken)` clears zero;
- `cost_ok` — advisory unless a `--cost-budget` is set.

Two verdicts are emitted: **`kb_vs_placebo`** (primary — isolates content) and `kb_vs_none`. The per-item lane
gates on `accept_grounded` (Δ`plan_target_recall@1` **or** Δ`resolved_rate_strict`, with Δ`fabrication_rate` ≤
0 and Δ`plan_groundedness` ≥ 0).

### 6c. Lifecycle tiers + provenance

`apply_verdict` (`kb/lifecycle.py`) walks `candidate → applied → validated → canonical`: a pass promotes one
rung and resets the fail streak; a fail increments it, and only after **2 consecutive fails** (`hysteresis`)
demotes one rung (so a single noisy A/B can't knock down a canonical item). Each transition is a new frozen
`ProvenanceRecord`. **In production the selection floor is `validated`** (`runner.py`), so an unpromoted
`candidate` Knowledge item is gated *out* of a production run — that is where "admit only on verified lift"
bites.

A `ProvenanceRecord` carries `tier`, `lineage`, `validating_case_ids`, `measured_lift`, and an
`evidence_context` *designed* to pin the atlas SHA + `bge-m3` + model pin + date the lift was measured against
(so a stale entry is auto-demotable). **Caveat:** `evidence_context` is currently passed `{}` at every site —
the field exists but the staleness discipline it enables is not yet wired.

---

## 7. Current status — machinery built, efficacy production-gated

The pipeline is fully implemented and wired, but the on-disk state proves **nothing has been validated**:

- **No Knowledge exists** — `kb/data/knowledge.json` is absent; `KnowledgeRegistry` fires nothing. Extraction
  has never persisted output (with no `KLOOP_PRODUCE_API_KEY`, the canned model proposes 0 Knowledge items).
- **All 12 seed Skills are `candidate`** — `provenance.json` shows every row at `tier="candidate"`,
  `lineage="authored cold-start"`, `measured_lift={}`, `validating_case_ids=[]`. No `apply_verdict(pass)` has
  ever moved one up.
- **`evidence_context` is inert** — `{}` everywhere, despite the documented intent.

This matches the **KB re-verdict**: the earlier "Archived null" was **discredited** — it was measured on the
wrong metric (`plan_target_recall`, not `resolved_rate`) and rode a localize-query pollution confound
(reproduced Δ−0.10 file@1); the fair `fix-only` re-test was **inconclusive at a 0-resolution floor** (a
synthetic crash log is disconnected from the real fix, so nothing resolves, and the hermetic fixer abstains on
every case). The KB is therefore **Candidate (unproven, not null)** and **production-gated**: a fair
`resolved_rate` verdict needs a **real** atlas + a **real** model + a **real-crash-with-fix** substrate that
produces nonzero resolution — which the dev-box proxy provably cannot supply
([`Phase-2 spec`](superpowers/specs/2026-07-13-kb-fair-eval-phase2-design.md), a production-side task).

> **One correctness caution for anyone extending this:** the per-item retain loop's `attribute_and_govern`
> defaults `primary="plan_target_recall@1"` — the *exact* metric the re-verdict flagged as discredited (a fix
> arm cannot move a localize metric). Prefer `resolved_rate` when you wire the real production A/B.

---

## 8. Running it (the CLI drivers)

All are Dev-Labs eval commands (Type-2, gated); they need a real atlas + gateway creds to produce a non-null
read (`docs/build-setup.md`). None is on the `gloop run` production path.

- `gloop kb-extract` — distill: propose Knowledge from each source Skill → ground-check → persist to
  `knowledge.json` at `tier=candidate`.
- `gloop kb-attribute` — the per-Knowledge retain loop: screen → LOFO-confirm → placebo-swap A/B → promote/retire.
- `gloop kb-ab` — the 3-arm (`none/kb/placebo`) A/B over **Knowledge** → `scorecard-*.json` + two
  `strengthened_accept` verdicts.
- `gloop kb-promote` — fold a verdict into the per-Skill provenance tiers (`apply_verdict`).
- `gloop fixeval --skills {none,mock,kb,placebo} [--skills-inject fix-only] [--knowledge {candidate,validated}]`
  — the measured fix arm (`--knowledge` = the distilled Knowledge; `--skills` = the raw baseline control);
  grade on `resolved_rate`, never `file_recall@1`.

---

## 9. File map

- **The Skill primitive (raw source):** `groundloop/skills/{base,predicate,ctx}.py`
- **The Knowledge primitive (distilled unit) + store:** `groundloop/kb/knowledge.py` (`Knowledge`, `KNOWLEDGE_PATH`, `load_knowledge`/`save_knowledge` over `knowledge.json`)
- **Registries:** `groundloop/adapters/skills/mock.py` (`MockSkillRegistry`, raw Skills) · `groundloop/kb/registry.py` (`KnowledgeRegistry`, tier-floor gate)
- **Feedstock + validator:** `groundloop/kb/data/aaos_kb_seed.toml` (12) · `groundloop/kb/validate.py` · `groundloop/kb/data/placebo.toml`
- **Distillation (Skill → Knowledge):** `groundloop/kb/extract.py` (`knowledge_from_skill`, `extract_to_store`) · `groundloop/kb/knowledge_ground.py` (`check_knowledge_grounded`) · `groundloop/kb/knowledge_placebo.py`
- **Injection:** `groundloop/fixeval/runner.py` (`_skill_query`, `render_skills`/`render_knowledge`, `--skills-inject`)
- **Retain-loop:** `groundloop/kb/{attribute,ab,placebo,accept,lifecycle,provenance}.py` · `groundloop/fixeval/compare.py`
- **Governance state:** [`capabilities.md`](capabilities.md) (Candidate) · design provenance: [`fix-loop.md`](fix-loop.md)
</content>
</invoke>
