# Stakeholder Technical Overview — Design Spec

> **Status:** Design v1 (2026-07-15). Defines *what* the stakeholder-facing technical overview must
> contain, *for whom*, *with what framing*, and *against what evidence* — the content contract the
> implementation plan will execute. It does **not** write the document; it specifies it.
>
> **Provenance:** brainstormed 2026-07-15 (superpowers:brainstorming). Confirmed decisions: primary goal
> = **build confidence in the method**; depth = **comprehensive briefing (~8–12 pp)**; format =
> **markdown doc in `docs/`**; spine = **Approach C (narrative arc)**.

---

## 1. Purpose & audience

**Deliverable.** One new markdown document: **`docs/stakeholder-overview.md`**.

**Audience.** Management stakeholders who are **technically interested** — they want the real mechanics
(architecture, stages, testing, scoring), not a marketing gloss, but they are not the day-to-day
engineers and should not need the full specs to follow it.

**Primary job (the frame that governs every editorial choice): build confidence in the method.** The
document must leave a technical manager convinced that GroundLoop's results can be *trusted* — that the
methodology is rigorous, the numbers are honestly earned, and the line between "validated product" and
"research scaffolding" is deliberately policed. This is the throughline; when a choice trades depth for
confidence-clarity, choose confidence-clarity.

**Why this frame fits GroundLoop.** The project's identity is **"grounding over narrative"** — trust only
what reality verifies. A stakeholder document that *itself* overclaims would betray the very thesis it
describes. Therefore honest status (what is `[production]`-validated vs `[proxy]`-only vs still mocked) is
a **feature to foreground**, not a caveat to bury. The document earns confidence precisely by being candid
about maturity.

**Non-goals.**
- Not a replacement for the canonical docs (`charter.md`, `architecture.md`, `evaluation.md`,
  `capabilities.md`, …). It **synthesizes and links down** into them; it does not duplicate them and must
  not drift from them.
- Not a sales deck, roadmap-only pitch, or funding ask. Confidence-in-method, not persuasion-by-vision.
- Not a how-to / runbook (that is `guide.md` / `build-setup.md` / `production-guide.md`).

## 2. Framing rules (apply throughout)

These are hard editorial invariants, checked in acceptance (§5):

- **R1 — Evidence tagging is mandatory.** Every efficacy/effectiveness number carries a `[proxy]` or
  `[production]` tag, per [`environments.md`](../environments.md). A bare efficacy number is a defect.
  Mechanism/design statements need no tag; measured outcomes always do.
- **R2 — No overclaim.** State maturity honestly: exactly one production run has happened (10 functional
  GEI cases); most matcher/fix arms are `[proxy]`-only **Candidate**; the KB is **Candidate/unproven**;
  the JIRA and Gerrit ends are **still mocked**. Confidence comes from *honest* status + *rigorous*
  method, never from inflating results.
- **R3 — Link, don't duplicate.** Each section ends with a "canonical source" pointer to the authoritative
  doc(s). The overview is a **map into** the docs, kept deliberately thin on internals that live elsewhere.
- **R4 — Secret hygiene.** No credentials, tokens, LAN IPs, internal endpoints, real `.env` contents, or
  gateway hostnames. Repo/tool names and public OSS proxy repos are fine.
- **R5 — Grounded to the tree.** Every module, port, CLI subcommand, metric, and governance state named in
  the doc must actually exist in the codebase/docs as of the writing date. No aspirational capabilities
  described in the present tense — forward-looking items are labelled as such.
- **R6 — Reconcile known discrepancies, don't launder them.** Where the source docs carry a flagged
  count-reconciliation caveat (e.g. the production run's "recall@1 7/10 by the per-case table vs 8/10 in
  the run summary"), the overview states the honest per-case number and notes the caveat rather than
  silently picking the flattering figure.

## 3. Structure & per-section content contract (Approach C — narrative arc)

Ten sections. Each entry below is the **content contract**: what the section must cover, the primary
evidence source, and the framing note. Section length scales to complexity; total target ~8–12 pp.

### §1 Executive summary
- **Covers:** what GroundLoop is in two sentences; the one-line loop `ticket + logs → MATCH owning repo →
  localize → fix → bind`; the core bet (Stage-1 matching is the primary objective and the gate); one
  **honest-status** paragraph (production-validated end-to-end at small N; the JIRA/Gerrit ends still
  mocked; most alternative arms proxy-only).
- **Source:** `charter.md` §1–2, `STATUS.md`, `capabilities.md` §4.
- **Framing:** confidence-first — the reader should learn *why to trust it* and *how mature it is* before
  any mechanics. Include a compact "how to read this document" note pointing at the `[proxy]`/`[production]`
  convention (R1).

### §2 The problem & the bet
- **Covers:** the 130+‑repo AAOS estate; manual, experience-dependent mis-routing today; why ticket→repo
  **matching** is the core objective (downstream stages only have value against correctly matched tickets);
  the cross-repo grounding evidence (null intra-repo; +40–60pp cross-repo lift; roughly capability-
  invariant — "context is the dominant lever, not model tier").
- **Source:** `charter.md` §1, §5, §7.
- **Framing:** establishes *why the method is shaped the way it is*. All lift figures tagged `[proxy]`
  and explicitly labelled directional (R1/R2).

### §3 The trust architecture *(the confidence spine)*
- **Covers:** the four pillars that make the numbers believable —
  1. **Grounding over narrative** (NFR-1): decisions backed by reality-verifiable signals; distrust
     unverifiable LLM prose.
  2. **The hidden oracle + oracle-blind control plane:** the owning repo is a *predicted output +
     hidden-oracle field, never a loop input*; `run_ticket` has no oracle parameter, so the classic
     owning-repo leak is **structurally impossible**; grading is a separate offline pass.
  3. **Deterministic control plane vs cognition plane** (NFR-6): Python owns sequencing/state/termination;
     the LLM only supplies *content* at each step, never decides what happens next.
  4. **The `[proxy]` vs `[production]` discipline:** dev-box proxy numbers flatter the mechanism and are
     mechanism/regression-only; the real scoreboard is production; every result is tagged.
- **Source:** `architecture.md` §1–2, `charter.md` §4 + NFR-1/4/6, `environments.md`.
- **Framing:** this is the load-bearing section for the whole document's goal. State each pillar once,
  crisply, so later sections can reference rather than re-argue it.

### §4 System architecture & modules
- **Covers:** hexagonal ports & adapters; the frozen `core/` control plane; the **7 core ports** (table:
  port → responsibility → mock vs real adapter); behavior swapped at the **composition root**
  (`cli/__init__.py`), never in `core/`; the **atlas** (SQLite of code units; FTS5 keyword + bge-m3 vector
  forms; symbol vs doc units); the **domain pack** seam (`domains/android_ivi/`, one pack today, YAGNI on
  multi-domain); a one-line note on migrated engines (atlas/lore/produce migrated verbatim, not rewritten).
- **Source:** `architecture.md` §2–7.
- **Framing:** answers "the modules within the system architecture." Keep the port table as the anchor;
  push internals to `architecture.md` (R3).

### §5 The four stages
- **Covers:** for **each** stage — **Match / Localize / Fix / Bind** — a compact block of four fields:
  - **Principle:** the one idea the stage embodies (e.g. Match = rank the owning repo from grounded
    signals over a real cross-repo index, never string-lookup a leaked name).
  - **Module(s):** the port + the real adapter(s) implementing it (Match = `CodeIndex.rank_repos` /
    `AtlasIndex`; Localize = `CodeIndex.retrieve`; Fix = `FixEngine.propose` / `PlanningFixEngine` +
    `ModelPatchEngine`; Bind = `ChangeSink.submit`/`bind` / `MockGerrit`, **still mocked**).
  - **How it's improved (the arms):** name the concrete selectable arms for that stage (Match:
    flood → component-affinity RRF, semantic, judge, functional, dispatch, fault-routing; Localize: atlas
    FTS5, `tokens`/`SignalQueryIndex`, semantic, dispatch; Fix: canned → model → plan (Bug Plan Mode);
    plus the dev-experience KB as a measured fix arm). One line each, cross-referencing §6 for the method.
  - **Current evidence:** the best measured number(s), correctly tagged — e.g. Match component prior
    `0.10 → 0.50` recall@1 `[production]`; Localize `7/10 file@5` `[production]`; Fix `0/10 ungraded`
    (empty-worktree artifact) `[production]` + `fabrication_rate 0.0` `[proxy]`; Bind = mocked (not an
    efficacy claim).
- **Source:** `charter.md` §2, `capabilities.md` §3, `results-log.md`, `STATUS.md`, `fix-loop.md`.
- **Framing:** the spine of "principles behind each stage" + a per-stage view of "iterative improvement."
  Be scrupulous that Fix and Bind are honestly presented as not-yet-graded / mocked (R2/R6). Use a
  consistent 4-field template per stage so the reader can compare stages at a glance.

### §6 The improvement engine *(how each stage gets better)*
- **Covers:** the shared machinery behind §5's arms —
  - **Arms + offline A/B:** a stage's behavior is a swappable adapter at the composition root; a new
    strategy is an *arm* measured against the incumbent, `core/` untouched.
  - **The evaluation pyramid:** tune on the cheap, deterministic layers (retrieval Success@k/MRR,
    grounding precision/recall — ms/case, N in the hundreds); reserve the expensive, noisy agentic A/B for
    *outcome validation*, not tuning; the ~±20pp N≈10 noise floor is why.
  - **Production-Core / Dev-Labs governance:** the promotion axis Core / Provisional-Core / Candidate /
    Archived (+ the permanent-role Dev-Labs-Infra / Fixture states); the **promotion rule** (a capability
    enters Core only after it consistently beats the incumbent on **real production data** + stability/cost/
    regression gates); **Provisional-Core** as the named, bounded exception for fail-safe capabilities;
    the enforcement that **defaults must be Core-aligned and fixtures must be explicit** (the "hermetic toy
    was the default" finding and its fix).
- **Source:** `capabilities.md` (all), `evaluation.md` §10, `workflows.md`.
- **Framing:** answers "methods for iteratively improving each stage" at the *system* level. The
  governance model is itself a confidence argument — show that the process structurally prevents an
  experiment from masquerading as the product.

### §7 Testing
- **Covers:** the **two paired test surfaces** — **Type-1** hermetic development tests (correctness,
  pass/fail, no network/no real LLM, runs every change; shared fixtures + anti-leak invariants) and
  **Type-2** live effectiveness eval (real models + a real atlas.db, `skipif`-gated); how they map onto the
  dev-box ↔ production split; the **anti-leak invariants** (`tests/test_invariants.py`) as green regression
  guards (ticket never names the owner; loop never reads the oracle; deterministic control flow; run-record
  oracle-free).
- **Source:** `evaluation.md` §14 + §9, `charter.md` NFR-4/8, `environments.md`.
- **Framing:** "the current testing approach." Emphasize that leak-tightness is *tested*, not merely
  intended — a direct confidence lever.

### §8 Evaluation & scoring
- **Covers:** the **scorecard** as the verdict (per-arm × per-repo × per-stage + cost + provenance,
  JSON + markdown twin); **Stage-1 forced metrics** (recall@1 the headline, recall@3/@5, MRR, mean rank);
  the **selective view / grounded refusal** (abstain on low margin; coverage, selective risk, the
  risk-coverage curve) and **Effective Reliability Φ_c** — *a wrong guess (−c) is strictly worse than an
  honest abstain (0), so guessing can never beat grounded refusal*; `abstention_recall_oof` on
  out-of-fleet negatives; **cost as a first-class metric** (`$/ticket-matched`, `$/solved`); the
  statistics honesty knobs (Wilson CIs; AURC/AUGRC gated on n≥~128); and the **one-run-is-both** property
  (a single `run_ticket` is simultaneously a real fix attempt and a graded eval case, bridged by the hidden
  oracle).
- **Source:** `evaluation.md` §7 (+ §2, §10), `charter.md` §4.
- **Framing:** "the evaluation/scoring system." The Φ_c "guessing can never win" point is the crown jewel
  for a confidence audience — give it room. Tie scoring back to §3's trust pillars.

### §9 Where we stand
- **Covers:** honest maturity snapshot — a compact **Core vs Candidate vs Fixture/mocked** table (drawn
  from the capability registry) of what is production-validated vs proxy-only vs still a stub; **the first
  production run** (10 functional GEI cases, first full 8-stage run: match recall@1 **7/10** `[production]`
  per the per-case table — noting the 7-vs-8 reconciliation caveat, R6 — localize 7/10 file@5, fix
  ungraded empty-worktree); the **remaining gaps to a real Core** (live JIRA `IssueSource` + live Gerrit
  `ChangeSink`; the deferred `[production]` `resolved_rate` A/B that resolves Bug Plan Mode); and the
  **roadmap direction** toward the 130+‑repo fleet.
- **Source:** `capabilities.md` §3–4, `STATUS.md`, `results-log.md`, `roadmap.md`.
- **Framing:** the honest close that *cements* rather than undercuts confidence — a stakeholder trusts a
  team that states its gaps precisely. No hedging, no inflation (R2).

### §10 Glossary & pointers
- **Covers:** a short glossary of the load-bearing terms (owning repo, atlas.db, fleet, signals, grounding,
  oracle, CBM, Type-1/Type-2, `[proxy]`/`[production]`, arm, Core/Candidate); a "read next" table pointing
  each topic to its canonical doc.
- **Source:** `charter.md` §9, the docs index in `CLAUDE.md`.
- **Framing:** makes the document a navigable map into the SSOT (R3).

## 4. Content sourcing & accuracy method

Because accuracy is the whole point of a confidence document, the implementation must **ground every
claim to the tree/docs**, not to memory:

- Primary sources are the canonical docs already cited per-section; where a number appears, cite the doc
  it came from so a reviewer can verify.
- Numbers are lifted from `results-log.md` / `STATUS.md` / `capabilities.md` **verbatim with their existing
  tags**; the overview never re-derives or "rounds up" a figure.
- Where two source docs disagree (the known 7-vs-8 count), follow R6 (state the honest per-case figure +
  the caveat).
- A dedicated **fact-check + leak-check pass** (an adversarial reviewer) verifies R1–R6 before the document
  is considered done — no unfamiliar capability, no untagged number, no leaked secret, no overclaim.

## 5. Acceptance criteria

The document is done when:

1. **All ten sections present**, in the Approach-C order, each ending with a canonical-source pointer (R3).
2. **Every efficacy number carries a `[proxy]` or `[production]` tag** (R1) — zero bare efficacy numbers.
3. **No overclaim** (R2): the doc states plainly that exactly one production run exists, that most arms are
   proxy-only Candidates, that the KB is unproven, and that JIRA/Gerrit are mocked.
4. **Every named module / port / CLI subcommand / metric / governance state exists** in the codebase/docs
   as of 2026-07-15 (R5); a spot-check of ~10 named entities resolves.
5. **The 7-vs-8 (and any other flagged) discrepancy is reconciled honestly** (R6).
6. **Secret hygiene clean** (R4): no creds/tokens/IPs/endpoints/hostnames.
7. **Length ~8–12 pp**, readable by a technical manager in one sitting; the Φ_c "guessing can't win" and
   the oracle-blind "leak is structurally impossible" points are both present and legible.
8. **Passes a final adversarial fact-check + leak-check** (§4) with no unresolved findings.
9. Markdown lints/renders cleanly; internal doc links resolve.

## 6. Guardrails (repo conventions)

- **No `core/` edits, no SQLite schema changes** — this is a docs-only change; it touches nothing in
  `groundloop/core/` or `engines/atlas/store.py`. (Stated for completeness; the doc adds one file.)
- **Docs-only diff:** the only file created is `docs/stakeholder-overview.md` (plus this spec and its
  plan). Optionally add a one-line pointer to it from the `CLAUDE.md` docs index and/or `STATUS.md`, if the
  reviewer wants it discoverable — decided at plan time, not assumed here.
- Commit only when the doc is complete and self-reviewed; end commit messages with the
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer. Commit/push only when
  the user asks.

## 7. Out of scope / deferred

- Diagrams beyond ASCII/mermaid (format is markdown; a styled hosted Artifact was explicitly **not**
  chosen).
- Any new measurement or eval run — the document reports existing, already-logged results only; it triggers
  no `gloop` runs and produces no new numbers.
- Translations, slide decks, or an executive one-pager derivative (possible follow-ups, not this task).
