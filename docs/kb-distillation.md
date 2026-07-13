# How the KB distills knowledge into Skills

> **What this doc is.** A code-grounded guide to GroundLoop's dev-experience **Knowledge Base (KB)** — how raw
> crash-RCA knowledge becomes small, injectable **Skills** (and atomic **Claims**), and the *retain-loop* that
> admits one only on **measured lift**. It is the "how it works" companion to [`fix-loop.md`](fix-loop.md)
> (design provenance) and [`capabilities.md`](capabilities.md) (governance state).
>
> **Read this caveat first.** The distillation machinery below is **fully built and structurally correct**, but
> **nothing has been validated yet** — all 12 seed Skills sit at cold-start `candidate` tier, no distilled
> Skill or Claim has ever been promoted, and the KB's *efficacy* verdict is **production-gated** (see §8 and
> [`kb-reverdict`](capabilities.md#candidate--dev-labs-research-blocked-on-a-first-production-read)). This guide
> documents the *mechanism*, not a proven result. The KB is a **Candidate** fix arm, never default-on.

---

## 1. The one-sentence idea

A **Skill** is a tiny, repo-agnostic crash-fixing playbook. The KB's job is to turn messy dev experience into
Skills that are (a) **grounded** — every code entity they name actually exists — (b) **oracle-blind** — they
never encode which repo owns a bug — and (c) **earned** — a Skill only enters the injected set, or climbs a
tier, after an A/B measurement shows it *helps*. Everything else in this doc is how those three properties are
enforced mechanically.

**Core principle (the project ethos, applied to the KB):** *distrust unverified prose.* A Skill's authored
guidance is treated as a hypothesis, not a fact — it is injected into the fix loop only behind a gate, and it
is kept only if reality (a passing fix-eval) confirms it.

---

## 2. What a Skill is

`groundloop/skills/base.py:10-17` — a frozen dataclass:

```python
@dataclass(frozen=True)
class Skill:
    id: str
    applies_to: Callable[[object], bool]   # WHEN it fires — a compiled predicate over a SkillCtx
    guidance: str                          # the playbook text (the ONLY field that reaches the prompt)
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
- **Only `guidance` is injected.** `render_skills` (`base.py:30-34`) emits `## Skill: <id>` + `s.guidance` and
  nothing else — `hint_apis`, `signals`, `provenance`, and the predicate never reach the model. An empty
  selection renders `""`, a byte-identical no-op versus the `none` arm.

---

## 3. The two corpora

| Corpus | Count | A/B arm | Path |
|---|---|---|---|
| `adapters/skills/data/aaos_playbooks.toml` | 4 | `mock` (the SP3 seed) | `MockSkillRegistry` `SEED_PATH` |
| **`kb/data/aaos_kb_seed.toml`** | **12** | **`kb`** (the real feedstock) | `KB_SEED` |
| `kb/data/placebo.toml` | 12 | `placebo` (the null control, §7) | `PLACEBO_SEED` |

The 12 KB seed Skills cover the AAOS crash taxonomy (native SEGV/abort, foreground-service, fragment-lifecycle
NPE, ISE-after-save, binder-too-large, audio underrun, media-player state, camera/GL surface, ANR,
CME/race, native-lib load). Each `[[skill]]` carries `id`, `provenance`, `signals`, `hint_apis`, a `guidance`
string with three mandatory clauses (`Signature:` / `Localize:` / `Fix:`), and the `[skill.match]` predicate.

**Every corpus passes a validator** (`kb/validate.py`, `validate_corpus`) with two hard gates:
1. **Closed-vocab conformance** — the predicate uses only the allowed keys, and it **forbids** `always` /
   `repo_in` (a repo-pinned or always-on Skill is a lookup-table row / overfit) and requires all three
   `Signature:/Localize:/Fix:` clauses.
2. **Leak red-test** — `owner_denylist()` builds the set of every fleet repo short-name / namespace / slug /
   `.so`; any such token appearing in `guidance` / `signals` / `hint_apis` / `match` is a **LEAK** and fails
   the corpus. Generic dependency tokens (`android.`, `androidx.`, sonames) are deliberately *kept* — only
   *owner-identifying* tokens are banned. This is what makes a Skill oracle-blind by construction.

---

## 4. Distillation, Lane A — harvest → distill → LOFO → revalidate

This lane compresses raw traces into a **guidance blob**, keeping only the load-bearing lines. Driver:
`gloop kb-distill` (`_run_kb_distill`, `cli/__init__.py`). It is **gated dormant** — it exits immediately
unless a prior `gloop kb-ab` verdict already accepted the KB (`kb_vs_placebo.accepted`).

```
mining-split cases ─▶ cluster_by_signature ─▶ candidate_from_cluster(split_tag) ─▶ baseline-lift gate
                                                                                        │ (>0 required)
     admit ◀── apply_verdict ◀── revalidate(margin) ◀── lofo_fragments ◀── distill_guidance(oracle-blind)
```

1. **`cluster_by_signature`** (`kb/harvest/cluster.py`) groups cases by their single most-discriminative
   signal (top error → top `.so` → next family; `"unknown"` if none). Coarse on purpose so related failures
   co-cluster. Input is drawn **only** from the `calib`/`train` mining splits (`SHA1(case_id) % 4`), never
   `eval`/`holdout`.
2. **`candidate_from_cluster(..., split_tag)`** mints a repo-agnostic template Skill (`id="harvest-<slug>"`,
   `Signature:/Localize:/Fix:` guidance, `match={"any_text":[sig]}`). It is a **split + leak firewall**:
   returns `None` unless `split_tag ∈ {calib, train}` (no eval/holdout case may author a Skill later scored
   against eval/holdout) and `None` if the signature is itself a fleet-owner token.
3. **Baseline-lift gate.** The candidate's own guidance must earn a positive lift before anything is distilled
   from it: `run_fn(guidance) > 0`, where `run_fn` is a real fix-eval A/B returning the **`resolved_rate`**
   delta over the `none` baseline (the correct KB metric — see §5's gotcha).
4. **`distill_guidance(traces)`** (`kb/distill/extract.py`) is **oracle-blind** — it **raises** if any trace
   carries `owning_repo`/`expected_files`. It does **not** paraphrase: it extracts *verbatim*,
   order-preserving, de-duplicated lines drawn only from the `injected_guidance` of traces where `helped` is
   true, and drops any line containing an owner-denylist token.
5. **`lofo_fragments(guidance, run_fn)`** (`kb/distill/lofo.py`) — **leave-one-fragment-out** attribution.
   For each line, ablate it and keep it **iff** removal *strictly lowers* the measured lift. "Load-bearing" =
   its removal drops resolution; inert filler is pruned.
6. **`revalidate(distilled, baseline_lift, run_fn, margin)`** (`kb/distill/revalidate.py`) — the pruned blob
   must **re-earn** the pre-distillation lift within `margin` (0.0 demands the full lift), else it is rejected.
7. **Admit** — a survivor is written to `distilled.toml`, seeded as a `ProvenanceRecord(tier="candidate",
   lineage="distilled …")`, and bumped one rung via `apply_verdict` (§7).

---

## 5. Distillation, Lane B — claim-centric (per-atomic-claim)

Lane A distills *guidance*; Lane B distills into **atomic Claims** — the smallest checkable unit of advice.
`kb/claim.py:26-35`:

```python
@dataclass(frozen=True)
class Claim:
    id: str
    applies_when: dict                 # a [skill.match]-style predicate: WHEN this claim fires
    type: str                          # "localize_hint" | "fix_step" | "api_requirement"
    content: str                       # the ONE thing it advises (this text enters the plan prompt)
    grounding_refs: tuple[str, ...]    # code entities it asserts exist (checkable in the atlas)
    provenance: str                    # the source Skill id — kept, never trusted
    tier: str                          # candidate | validated | canonical | retired
    evidence: dict = ...               # lifecycle bookkeeping
```

1. **Extract (LLM proposes)** — `gloop kb-extract` (`kb/extract.py`) runs a model over each Skill's guidance,
   asking for `{claims:[{type, content, grounding_refs, applies_when}]}` and to "name NO product/repo/vendor
   identifiers." `parse_claims` is tolerant — returns `[]` on any malformed output, **never raises**. The LLM
   is a **proposer only**; nothing it says is trusted yet.
2. **Ground-check (deterministic gate)** — `check_claim_grounded` (`kb/claim_ground.py`) admits a claim only
   if it has **zero** reasons to reject: (a) **well-formed** (valid `type`, non-empty content, a *compilable*
   `applies_when`); (b) **grounded** — every `grounding_ref` resolves **fleet-wide** in the atlas via a
   whole-identifier boundary match (recall by keyword, then require the full token verbatim, defeating
   hallucinated qualified/snake refs riding on a real subtoken); (c) **leak-safe** — no fleet-owner token.
   Checking existence *fleet-wide* is what keeps it oracle-blind: "reveals nothing about WHICH repo owns the
   defect." Survivors persist to `claims.json` at `tier=candidate`.
3. **Attribute / retain** — `gloop kb-attribute` (`kb/attribute.py`, `attribute_and_govern`) runs the retain
   loop one claim at a time: a cheap oracle-blind **screen** (correlational directional lift, shortlist only) →
   **leave-one-claim-out** Δ → a **placebo-swap** A/B (the claim vs a same-firing-set placebo) gated by
   `accept_grounded` → **`promote_or_retire`** (one rung up on pass; at the bottom rung a failing streak
   **retires** the claim permanently).

---

## 6. Injection — how a Skill reaches the fix, and the metric gotcha

All injection happens in `FixEvalRunner._one` (`fixeval/runner.py`), **after** Stage-1 match picks a
`predicted` repo, keyed on arm signals + predicted repo (oracle-blind). There are **two channels**:

- **Fix-prompt preamble** — `render_skills(selected)` (guidance only) + `render_claims(selected_claims)`
  (each claim's `content` as a single bullet under a fixed type header) are prepended to the fix/plan prompt
  via `fixer.with_preamble(...)`.
- **Localize retrieval query** — `_skill_query(selected)` concatenates each Skill's `signals` + the text after
  any `Localize:` line, and biases the `localize(...)` retrieval query.

**`--skills-inject {both, fix-only}`:**
- `both` (default): skills feed **both** the localize query and the fix preamble.
- `fix-only`: the localize query is forced empty → `localize(...)` is **byte-identical to the `none` arm**,
  so skills feed *only* the fix/plan prompt. (Claims are always preamble-only, so `--claims` is inherently
  localize-invariant.)

**The gotcha (why this matters).** In `_one`, **localize runs before fix**. A fix-stage Skill therefore
*cannot* change `file_recall@1` (scored off localize). Under `fix-only` this is *provable* — the localize
query is empty. So the KB must be graded on **`resolved_rate` / `patch_applies` / `fabrication_rate`**, never
`file_recall@1`. Grading the KB on a localize metric is exactly the mistake that produced the discredited
"KB null" (§8).

---

## 7. The retain-loop — "admit only on verified lift"

Nothing enters the injected set, or climbs a tier, on authorship alone. Three things gate it:

**A/B with a content-isolating placebo.** `run_ab` (`kb/ab.py`) reruns the whole fix-eval for arms
`none / kb / placebo`. The **placebo** (`kb/placebo.py`) copies each KB Skill's `[skill.match]` *verbatim*
(so it fires on the identical cases) but replaces the guidance with length-matched, deliberately irrelevant
filler. Any lift the real KB shows **over the placebo** isolates the *content* of the guidance from the mere
fact that *something* fired. `grade_fix_all` is the sole oracle read.

**The acceptance gate** — `strengthened_accept` (`kb/accept.py`) admits a KB set only if **all** hold:
- `pos_ok` — Δ`file_recall@1` > 0 **or** `newly_solved > newly_broken`;
- `honesty_ok` — Δ`fabrication_rate` ≤ 0 (never buy resolution with more fabrication);
- `phi_ok` — Δφ_c ≥ 0 at **every** risk-aversion c ∈ {0.5, 1.0, 2.0} (no regression in effective reliability);
- `wilson_lo > 0` — the Wilson-95 lower bound of `newly_solved/(newly_solved+newly_broken)` clears zero (a
  lift backed by too few actually-resolved cases is rejected);
- `cost_ok` — advisory unless a `--cost-budget` is set.

Two verdicts are emitted: **`kb_vs_placebo`** (primary — isolates content) and `kb_vs_none`. The claim lane's
analogue is `accept_grounded` (gates on Δ`plan_target_recall@1` **or** Δ`resolved_rate_strict`, with
Δ`fabrication_rate` ≤ 0 and Δ`plan_groundedness` ≥ 0).

**Lifecycle tiers + hysteresis** — `apply_verdict` (`kb/lifecycle.py`) walks
`candidate → applied → validated → canonical`: a pass promotes one rung and resets the fail streak; a fail
increments it, and only after **2 consecutive fails** (`hysteresis`) demotes one rung (so a single noisy A/B
can't knock down a canonical playbook). Each transition is a new frozen `ProvenanceRecord`. **In production the
selection floor is `validated`** (`runner.py`), so an unpromoted `candidate` Skill/Claim is gated *out* of a
production run — that is where "admit only on verified lift" bites.

**Provenance** — a `ProvenanceRecord` carries `tier`, `lineage`, `validating_case_ids`, `measured_lift`, and
an `evidence_context` *designed* to pin the atlas SHA + `bge-m3` + model pin + date the lift was measured
against (so a stale entry is auto-demotable). **Caveat:** `evidence_context` is currently passed `{}` at every
site — the field exists but the staleness discipline it enables is not yet wired.

---

## 8. Current status — machinery built, efficacy production-gated

The pipeline is fully implemented and wired, but the on-disk state proves **nothing has been validated**:

- **No Claims exist** — `kb/data/claims.json` is absent; `ClaimRegistry` fires nothing. The claim lane has
  never persisted output (with no `KLOOP_PRODUCE_API_KEY`, the canned model proposes 0 claims).
- **No distilled Skills exist** — `kb/data/distilled.toml` is absent; `kb-distill` has never promoted one.
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

> **One correctness caution for anyone extending this:** the two lanes optimize **different** primary metrics —
> Lane A's `run_fn` uses the `resolved_rate` lift (correct), while the claim retain-loop's
> `attribute_and_govern` defaults `primary="plan_target_recall@1"` — the *exact* metric the re-verdict flagged
> as discredited. Prefer `resolved_rate` when you wire the real production A/B.

---

## 9. Running it (the CLI drivers)

All are Dev-Labs eval commands (Type-2, gated); they need a real atlas + gateway creds to produce a non-null
read (`docs/build-setup.md`). None is on the `gloop run` production path.

- `gloop kb-ab` — the 3-arm (`none/kb/placebo`) A/B → `scorecard-*.json` + two `strengthened_accept` verdicts.
- `gloop kb-promote` — fold a verdict into the per-Skill provenance tiers (`apply_verdict`).
- `gloop kb-distill` — Lane A (dormant unless `kb_vs_placebo` accepted): harvest → distill → LOFO → revalidate.
- `gloop kb-extract` / `gloop kb-attribute` — Lane B: propose Claims → ground-check → the per-claim retain loop.
- `gloop fixeval --skills {none,kb,mock,distilled} [--skills-inject fix-only] [--claims {candidate,validated}]`
  — the measured fix arm; grade on `resolved_rate`, never `file_recall@1`.

---

## 10. File map

- **The Skill primitive:** `groundloop/skills/{base,predicate,ctx}.py`
- **Registries:** `groundloop/adapters/skills/mock.py` (`MockSkillRegistry`) · `groundloop/kb/registry.py` (`ClaimRegistry`, tier-floor gate)
- **Feedstock + validator:** `groundloop/kb/data/aaos_kb_seed.toml` (12) · `groundloop/kb/validate.py` · `groundloop/kb/data/placebo.toml`
- **Lane A:** `groundloop/kb/harvest/cluster.py` · `groundloop/kb/distill/{extract,lofo,revalidate}.py`
- **Lane B:** `groundloop/kb/{claim,extract,claim_ground,claim_placebo,attribute}.py`
- **Injection:** `groundloop/fixeval/runner.py` (`_skill_query`, `render_skills`/`render_claims`, `--skills-inject`)
- **Retain-loop:** `groundloop/kb/{ab,placebo,accept,lifecycle,provenance}.py` · `groundloop/fixeval/compare.py`
- **Governance state:** [`capabilities.md`](capabilities.md) (Candidate) · design provenance: [`fix-loop.md`](fix-loop.md)
