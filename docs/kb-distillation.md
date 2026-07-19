# How the KB distills Skills into knowledge

> **What this doc is.** A code-grounded guide to GroundLoop's dev-experience **Knowledge Base (KB)** — how raw
> crash-RCA **Skills** (authored feedstock) become injectable **crash-RCA playbooks**, and the retain-loop that
> promotes one only on **measured lift**. It is the "how it works" companion to [`fix-loop.md`](fix-loop.md)
> (design provenance) and [`capabilities.md`](capabilities.md) (governance state).
>
> **The direction, stated once.** A `Skill` is *only ever an input* — raw, human-authored feedstock. Nothing in
> the KB produces a Skill. The distilled unit the fix loop injects, and the promotion gate measures, is a
> **`KnowledgePlaybook`** — one coherent record per crash class (signature/localize/fix/APIs), not an atomic claim.
>
> **Redesigned 2026-07-19** (`docs/superpowers/plans/2026-07-19-kb-playbook-redesign.md` +
> `docs/superpowers/specs/2026-07-19-kb-playbook-redesign-design.md`). The prior cycle's atomic-claim
> representation and its LLM `kb-extract` decomposer are **retired**; §2–§9 below describe the *current*
> mechanism. Governance moved **Dormant → Candidate** (see
> [`capabilities.md`](capabilities.md#candidate--dev-labs-research-blocked-on-a-first-production-read-9)): the
> KB is now active — a deterministic feedstock parser (`gloop kb-seed`) seeds 12 grounded candidate playbooks,
> a bounded top-k=2 retriever injects `validated`-only playbooks into `gloop run`'s fixer (opt-in `--kb-store`),
> and a clean-applying fix **mints** a new candidate playbook (oracle-blind, deduped by crash-class) for the
> offline retain-loop to promote. This guide documents the *mechanism*; the KB's *efficacy* (a `resolved_rate`
> lift on real AAOS crash+fix tickets) remains **production-gated** (see §7) — this cycle's bar is unit-proven,
> wired, and hermetically testable, not a measured lift.

---

## 1. The one-sentence idea

A **Skill** is a tiny, repo-agnostic crash-fixing playbook — raw dev experience captured verbatim. The KB's
job is to **turn each Skill into one coherent `KnowledgePlaybook`** (a whole crash-RCA record — signature,
where-to-look, what-to-do, the APIs it touches — never shredded into atomic claims) that is (a) **grounded** —
every code entity it names actually exists — (b) **oracle-blind** — it never encodes which repo owns a bug —
and (c) **earned** — a playbook only enters the injected set, or climbs a tier, after an A/B measurement shows
it *helps*. Everything else in this doc is how those three properties are enforced mechanically.

**Core principle (the project ethos, applied to the KB):** *distrust unverified prose.* A Skill's authored
guidance is treated as a hypothesis, not a fact — it is parsed into a checkable playbook, injected into the
fix loop only behind a gate, and kept only if reality (a passing fix-eval) confirms it.

---

## 2. The two primitives — Skill (raw source) and KnowledgePlaybook (distilled unit)

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
  retain-loop promotes; that is a `KnowledgePlaybook`.

### 2b. `KnowledgePlaybook` — the distilled, injectable unit (was atomic `Knowledge`/`Claim`)

`groundloop/kb/knowledge.py:32` — one coherent record per crash class, built **from** a source Skill (via
`gloop kb-seed`) or **minted** from the loop's own clean-applying fix (via `mint_playbook`, §4). This is the
headline thing the loop injects and the gate measures — a whole RCA, not a single atomic claim.

```python
@dataclass(frozen=True)
class KnowledgePlaybook:
    id: str
    applies_when: dict                 # a [skill.match]-style predicate: WHEN this playbook fires
    signature: str                     # the crash fingerprint (prose; ungrounded, but names grounded symbols)
    localize: tuple[str, ...]          # where-to-look hints for the localize stage
    fix: tuple[str, ...]               # ordered fix steps
    required_apis: tuple[str, ...]     # APIs the fix is expected to touch
    grounding_refs: tuple[str, ...]    # every code entity it names — each MUST resolve in the atlas
    provenance: str                    # the source Skill id, or "minted:<ticket_id>" — kept, never trusted
    tier: str                          # candidate | validated | canonical | retired
    evidence: dict = ...               # lifecycle bookkeeping
```

*(`groundloop/kb/knowledge.py` also keeps a `Knowledge = KnowledgePlaybook` alias and the legacy
`type`/`content` fields for now, transitional scaffolding from the atomic-claim migration — not part of the
current design; new code should use `KnowledgePlaybook`/`signature`/`localize`/`fix`.)*

A `KnowledgePlaybook` carries its **own** firing predicate (`applies_when`) and records, in `provenance`,
*the source Skill id it was parsed from, or the ticket it was minted from* — the one directional statement in
the whole KB, and it is right (Skill/fix → Playbook). It persists in a machine-updated JSON store
(`groundloop/kb/data/knowledge.json`, keyed by id); the retain-loop mutates only `tier` + `evidence`, while the
human-authored feedstock stays the source Skills.

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
**These are the raw source `gloop kb-seed` parses — never a produced artifact.**

**Every corpus passes a validator** (`kb/validate.py`, `validate_corpus`) with two hard gates:
1. **Closed-vocab conformance** — the predicate uses only the allowed keys, and it **forbids** `always` /
   `repo_in` (a repo-pinned or always-on Skill is a lookup-table row / overfit) and requires all three
   `Signature:/Localize:/Fix:` clauses.
2. **Leak red-test** — `owner_denylist()` builds the set of every fleet repo short-name / namespace / slug /
   `.so`; any such token appearing in `guidance` / `signals` / `hint_apis` / `match` is a **LEAK** and fails
   the corpus. Generic dependency tokens (`android.`, `androidx.`, sonames) are deliberately *kept* — only
   *owner-identifying* tokens are banned. This is what makes the source oracle-blind by construction.

---

## 4. Two ways a playbook enters the store — seed (offline parse) and mint (in-loop)

The KB no longer decomposes Skills with an LLM. A `KnowledgePlaybook` is created one of two ways, both
deterministic and grounded:

### 4a. Seed — `gloop kb-seed` (deterministic feedstock parse, offline)

Driver: `groundloop/kb/seed.py` (`playbook_from_skill`, `seed_to_store`), called by the `kb-seed` CLI handler.

1. **Parse (no model involved)** — `playbook_from_skill(skill)` lifts the `Signature:` / `Localize:` / `Fix:`
   clauses straight out of the Skill's `guidance` text (each Skill already carries these three mandatory
   clauses, §3) and copies `hint_apis` into `required_apis`/`grounding_refs` and the Skill's own `[skill.match]`
   into `applies_when`. This is a **parser, not a shredder** — the retired LLM `kb-extract` used to ask a model
   to propose atomic `{type, content}` claims from free text; the new parser reads a fixed clause format
   verbatim, so there is nothing for a model to hallucinate.
2. **Ground-check (deterministic gate, unchanged)** — `check_knowledge_grounded` (`kb/knowledge_ground.py`)
   admits a playbook only if it has **zero** reasons to reject: (a) **well-formed** (a non-empty `signature`,
   a *compilable* `applies_when`); (b) **grounded** — every `grounding_ref` resolves **fleet-wide** in the atlas
   via a whole-identifier boundary match (recall by keyword, then require the full token verbatim, defeating
   hallucinated qualified/snake refs riding on a real subtoken); (c) **leak-safe** — no fleet-owner token.
   Checking existence *fleet-wide* is what keeps it oracle-blind: it reveals nothing about WHICH repo owns the
   defect. Survivors persist to `knowledge.json` at `tier=candidate` (`seed_to_store`, deduped by id via
   `setdefault`).
3. **Attribute / retain** — `gloop kb-attribute` (§6) runs the retain loop one playbook at a time. A
   `candidate` item is gated *out* of a production run until it earns promotion to `validated`.

### 4b. Mint — `mint_playbook` (in-loop, oracle-blind, new this cycle)

Driver: `groundloop/kb/mint.py`. The loop learns from its own outcomes: whenever a proposed patch **applies
cleanly** (`patch_applies`, computed oracle-blind against the materialized worktree), `mint_playbook` builds a
new candidate straight from the run's own artifacts — never the oracle: `signals` → `signature` +
`applies_when`; `locations` → `localize`; the identifiers the patch **diff actually touches**, filtered to the
crash-named vocabulary → `fix` / `required_apis` / `grounding_refs`. The record `id` is a hash of the sorted
crash-signal tokens (`crash_class_id`), so re-seeing the same crash class merges into the existing candidate
(`setdefault`) instead of duplicating. The same ground-check as seeding runs before admission — an ungrounded
mint is dropped, never stored. Minting is wired into the batch driver (`run/batch.py`) as an opt-in hook after
each case.

---

## 5. Injection — how a playbook reaches the fix, the bounded retriever, and the metric gotcha

**The retriever (`PlaybookRegistry.select(ctx, tier_floor)`, `kb/registry.py`)** — not a firehose: (1) filter
the store to playbooks whose `applies_when` fires *and* whose `tier` clears `tier_floor`; (2) rerank the
firing set by relevance to the ticket (an optional bge-m3 cosine rerank over each playbook's `signature`; with
no embedder, falls back to store order); (3) bound to the **top-k = 2** (`KLOOP_KB_TOPK`, default `2`) most
relevant, under a hard token budget. `tier_floor` is `validated` in production, `candidate` in eval.

Injection happens in two places that share this same registry + renderer:

- **`gloop run` (production, opt-in)** — `KnowledgeInjectingFixEngine` (`adapters/fix/knowledge_inject.py`), a
  composition-root `FixEngine` decorator composed only when `--kb-store`/`KLOOP_KB_STORE` is set: it re-derives
  `signals` from the shared `RecordingExtractor`, builds the ctx, selects at the `validated` floor, and — if
  the selection is non-empty — wraps the inner fixer via `with_preamble(...)` before calling `propose`. With no
  `--kb-store` configured, `gloop run` is **byte-identical** to a KB-blind run (fail-safe default).
- **`FixEvalRunner._one` (`fixeval/runner.py`, eval)** — the same selection + `render_playbooks(selected)`
  (`kb/render.py`), emitted as a fix-prompt preamble via `fixer.with_preamble(...)`, **after** Stage-1 match
  picks a `predicted` repo (oracle-blind). Each selected playbook renders as one compact block
  (`# Crash playbook: <id>` / `Signature:` / `Look at:` / `Fix:` / `APIs:`) — never raw Skill prose. An empty
  selection renders `""`, byte-identical to the `none` arm.
- **`render_skills(selected)` — the raw undistilled baseline (`--skills`, eval only).** Prepends the whole
  `guidance` of each matching source Skill (`## Skill: <id>`). This is a retained **control** — an explicit
  "what does the undistilled source do?" arm — **not** what the retain-loop promotes.

**The localize channel — `--skills-inject {both, fix-only}`** (raw-Skill arm only, eval):
- `both` (default): raw Skills feed **both** the localize retrieval query (`_skill_query`) and the fix preamble.
- `fix-only`: the localize query is forced empty → `localize(...)` is **byte-identical to the `none` arm**, so
  Skills feed *only* the fix/plan prompt. **A playbook is always preamble-only, so `--knowledge` is inherently
  localize-invariant** (it never touches the localize query).

**The gotcha (why this matters).** Localize runs before fix (both in `FixEvalRunner._one` and in `run_ticket`).
A fix-stage injection therefore *cannot* change `file_recall@1` (scored off localize). For `--knowledge` this
is structural; for `--skills` under `fix-only` it is *provable* — the localize query is empty. So the KB must
be graded on **`resolved_rate` / `patch_applies` / `fabrication_rate`**, never `file_recall@1`. Grading the KB
on a localize metric is exactly the mistake that produced the discredited earlier "KB null" (§7).

---

## 6. The retain-loop — "admit only on verified lift"

Nothing enters the injected set, or climbs a tier, on authorship alone. Two drivers gate it, both over the
**`KnowledgePlaybook`** store (still called `knowledge.json` / `--knowledge` in code — the rename was
surface-only; see §8). The redesign adapted this loop from per-atomic-claim to **per-playbook** — the
mechanism (screen → LOFO → placebo → promote) is unchanged, only what one governed unit *is* changed (a whole
crash-RCA record, not a single claim).

### 6a. `gloop kb-attribute` — the per-playbook retain loop

`attribute_and_govern` (`kb/attribute.py:144`) runs the loop one playbook at a time:
- **`screen_knowledge`** (`attribute.py:51`) — a cheap, oracle-blind **directional screen** over the plan
  archive's per-case `groundedness` + `patch_applies` → a shortlist (correlational; prioritizes, never
  promotes; no new spend).
- **`lofo_knowledge`** (`attribute.py:79`) — **leave-one-playbook-out** ablation Δ: keep a playbook iff
  removing it *strictly lowers* the measured lift.
- **placebo-swap A/B** — the shortlisted playbook vs a same-firing-set placebo twin
  (`build_knowledge_placebo`, `kb/knowledge_placebo.py`: same `applies_when` — so it fires on the identical
  cases — but empty `grounding_refs`/`required_apis` and length-matched, deliberately irrelevant
  `signature`/`localize`/`fix` text), gated by the two-sided `accept_grounded` (`fixeval/compare.py`) →
  **`apply_verdict`** promotes one rung on pass; at the bottom rung a failing streak **retires** the playbook
  permanently.

### 6b. `gloop kb-ab` — the promotion gate (retargeted to playbooks)

`run_ab` (`kb/ab.py`) reruns the whole fix-eval for arms `none / kb / placebo`, injecting playbooks at the
fix stage (candidate floor) via `FixEvalRunner(knowledge=..., knowledge_tier_floor="candidate")` — **not** raw
Skills. The `kb` arm is the parsed-and-minted playbook store (`knowledge.json`); `placebo` is the per-playbook
length-matched irrelevant control that fires on the identical cases; `none` is no injection. Any lift the real
playbooks show **over the placebo** isolates the *content* from the mere fact that *something* fired.
`grade_fix_all` is the sole oracle read.

**Honest cold-start.** `knowledge.json` is empty until `gloop kb-seed` (or a mint) runs, so on an empty store
all three arms select nothing and are **byte-identical to `none`** — the A/B is only meaningful *after*
seeding (asserted in `tests/kb/test_kb_ab_retarget.py`).

**The acceptance gate** — `strengthened_accept` (`kb/accept.py`) admits a set only if **all** hold:
- `pos_ok` — Δ`file_recall@1` > 0 **or** `newly_solved > newly_broken`;
- `honesty_ok` — Δ`fabrication_rate` ≤ 0 (never buy resolution with more fabrication);
- `phi_ok` — Δφ_c ≥ 0 at **every** risk-aversion c ∈ {0.5, 1.0, 2.0} (no regression in effective reliability);
- `wilson_lo > 0` — the Wilson-95 lower bound of `newly_solved/(newly_solved+newly_broken)` clears zero;
- `cost_ok` — advisory unless a `--cost-budget` is set.

Two verdicts are emitted: **`kb_vs_placebo`** (primary — isolates content) and `kb_vs_none`. The per-playbook
lane gates on `accept_grounded` (Δ`resolved_rate_strict` — the corrected default primary, see the note below
§7 — with Δ`fabrication_rate` ≤ 0 and Δ`plan_groundedness` ≥ 0).

### 6c. Lifecycle tiers

`apply_verdict` (`kb/lifecycle.py`) walks `candidate → applied → validated → canonical`: a pass promotes one
rung and resets the fail streak; a fail increments it, and only after **2 consecutive fails** (`hysteresis`)
demotes one rung (so a single noisy A/B can't knock down a canonical item). It is generic over any frozen tier
record; the retain-loop bridges each `KnowledgePlaybook` through `attribute.KnowledgeRecord` (`id`, `tier`,
`fail_count`, `demotions`), and `promote_or_retire` writes the new `tier` + evidence back onto the frozen
playbook. **In production the selection floor is `validated`** (`PlaybookRegistry`/`KnowledgeInjectingFixEngine`),
so an unpromoted `candidate` playbook is gated *out* of a production run — that is where "admit only on
verified lift" bites.

The per-playbook lifecycle bookkeeping (`measured_lift`, `wilson95`, `validating_case_ids`, and the
`fail_count`/`demotions` streak) lives in each playbook's `evidence` dict, written by `promote_or_retire`. An
`evidence_context` *designed* to pin the atlas SHA + `bge-m3` + model pin + date the lift was measured against
(so a stale entry is auto-demotable) is envisaged but **currently inert** — the field is passed `{}` at every
site, so the staleness discipline it enables is not yet wired.

---

## 7. Current status — Candidate: machinery redesigned, wired, and hermetically proven; efficacy still production-gated

The **2026-07-19 playbook redesign** (`docs/superpowers/plans/2026-07-19-kb-playbook-redesign.md` +
`docs/superpowers/specs/2026-07-19-kb-playbook-redesign-design.md`) moved the KB from *"fully built but empty
and `gloop run`-blind"* to **active**:

- **The store is seeded** — `gloop kb-seed` parses the 12 feedstock Skills into grounded `candidate`
  playbooks (no model, no `KLOOP_PRODUCE_API_KEY` dependency for seeding).
- **`gloop run` is no longer KB-blind** — with `--kb-store`/`KLOOP_KB_STORE` set, `KnowledgeInjectingFixEngine`
  injects `validated`-tier playbooks into the fixer's preamble; unconfigured, a run is byte-identical to
  before (fail-safe default, still the case in production today since nothing has been promoted to
  `validated` yet).
- **The loop learns from its own fixes** — `mint_playbook` is wired into the batch driver (`run/batch.py`) as
  an opt-in hook, so a clean-applying patch can candidate-seed a new playbook, oracle-blind.
- **Hermetically proven this cycle** (Type-1, no oracle/network): mint fires on a canned clean-applying fix
  and produces a grounded candidate; a fabricated ref is rejected; the bounded retriever selects top-2 by
  predicate (+ rerank when an embedder is present); the decorator injects into a fake fixer via
  `with_preamble`; an empty store leaves `gloop run` byte-identical.
- **`evidence_context` is still inert** — `{}` everywhere, despite the documented intent (unchanged by this
  cycle).

**What is *not* yet true, and is explicitly deferred (§9 of the design spec):** no playbook has been promoted
to `validated` on real data yet, so production injection is still dormant *in practice* (the machinery is
live, the gate has nothing to pass through it), and there is **no measured `resolved_rate` lift** — that A/B
(KB-on vs KB-off on real AAOS crash+fix tickets) is the scheduled `[production]` read that resolves
governance from Candidate onward. This is the same underlying constraint the **KB re-verdict** identified: a
fair `resolved_rate` read needs a **real** atlas + a **real** model + a **real-crash-with-fix** substrate that
produces nonzero resolution, which the dev-box proxy provably cannot supply
([`Phase-2 spec`](superpowers/specs/2026-07-13-kb-fair-eval-phase2-design.md), a production-side task). The
earlier "Archived null" itself remains **discredited** (it was measured on the wrong metric,
`plan_target_recall` not `resolved_rate`, and rode a localize-query pollution confound) — nothing here revives
it; the redesign is a fresh Candidate, not a rebuttal of an established null.

> **One correctness note for anyone extending this:** the per-playbook retain loop's `attribute_and_govern`
> defaults `primary="resolved_rate_strict"` (`kb/attribute.py:146`) — the game-proof metric every governance
> consumer uses. The earlier default of `primary="plan_target_recall@1"` was the *exact* metric the re-verdict
> flagged as discredited (a fix arm cannot move a localize metric); it has since been corrected. Do not revert
> this default back to a `plan_target_recall`-family metric.

---

## 8. Running it (the CLI drivers)

`kb-seed`/`kb-attribute`/`kb-ab` are Dev-Labs eval/build commands (gated on a real atlas + gateway creds for a
non-null read, `docs/build-setup.md`); `gloop run` is the one production-reachable consumer, and only when
explicitly configured.

- `gloop kb-seed --index-db <atlas.db> --out <knowledge.json>` — the deterministic feedstock parser (replaces
  the retired LLM `kb-extract`): parse each Skill's `Signature:/Localize:/Fix:` clauses → ground-check →
  persist admitted playbooks at `tier=candidate`.
- `gloop kb-attribute` — the per-playbook retain loop: screen → LOFO-confirm → placebo-swap A/B →
  promote/retire.
- `gloop kb-ab` — the 3-arm (`none/kb/placebo`) A/B over **playbooks** → `scorecard-*.json` + two
  `strengthened_accept` verdicts.
- `gloop fixeval --skills {none,mock,kb,placebo} [--skills-inject fix-only] [--knowledge {candidate,validated}]`
  — the measured fix arm (`--knowledge` = the parsed/minted playbook store; `--skills` = the raw baseline
  control); grade on `resolved_rate`, never `file_recall@1`.
- `gloop run --kb-store <knowledge.json> [--kb-topk N]` (or `KLOOP_KB_STORE`/`KLOOP_KB_TOPK`) — **production**:
  opt-in `validated`-only playbook injection into the fixer, plus the opt-in mint hook in the batch driver.
  Omit `--kb-store` and a run is byte-identical to KB-off.

---

## 9. File map

- **The Skill primitive (raw source):** `groundloop/skills/{base,predicate,ctx}.py`
- **The `KnowledgePlaybook` primitive + store:** `groundloop/kb/knowledge.py` (`KnowledgePlaybook`, `KNOWLEDGE_PATH`, `load_knowledge`/`save_knowledge` over `knowledge.json`; keeps a transitional `Knowledge` alias + legacy `type`/`content` fields)
- **Registries:** `groundloop/adapters/skills/mock.py` (`MockSkillRegistry`, raw Skills) · `groundloop/kb/registry.py` (`PlaybookRegistry` — predicate filter → bge-m3 rerank → top-k bound; `KnowledgeRegistry` transitional alias)
- **Feedstock + validator:** `groundloop/kb/data/aaos_kb_seed.toml` (12) · `groundloop/kb/validate.py` · `groundloop/kb/data/placebo.toml`
- **Seed (Skill → playbook, deterministic parse):** `groundloop/kb/seed.py` (`playbook_from_skill`, `seed_to_store`) · `groundloop/kb/knowledge_ground.py` (`check_knowledge_grounded`) · `groundloop/kb/knowledge_placebo.py`. *(The old LLM shredder, `kb/extract.py`, is retired/deleted.)*
- **Mint (fix → playbook, in-loop):** `groundloop/kb/mint.py` (`mint_playbook`, `crash_class_id`) · wired from `groundloop/run/batch.py` (opt-in hook after a clean-applying case)
- **Injection:** `groundloop/kb/render.py` (`render_playbooks`) · `groundloop/adapters/fix/knowledge_inject.py` (`KnowledgeInjectingFixEngine`, the `gloop run` composition-root decorator) · `groundloop/fixeval/runner.py` (`_skill_query`, `render_skills`/`render_playbooks`, `--skills-inject`) · `groundloop/cli/__init__.py` (`_wire_kb`, `--kb-store`/`--kb-topk`) · `groundloop/config/settings.py` (`KLOOP_KB_STORE`/`KLOOP_KB_TOPK`)
- **Retain-loop:** `groundloop/kb/{attribute,ab,placebo,accept,lifecycle}.py` · `groundloop/fixeval/compare.py`
- **Governance state:** [`capabilities.md`](capabilities.md) (Candidate) · design provenance: [`fix-loop.md`](fix-loop.md) · redesign: `docs/superpowers/specs/2026-07-19-kb-playbook-redesign-design.md`
