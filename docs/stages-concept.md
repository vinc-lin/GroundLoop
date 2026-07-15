# The Concept Behind the Three Working Stages — Match · Localize · Fix

> **Audience:** technically-interested stakeholders. **Purpose:** explain the *idea* behind each of
> GroundLoop's three working stages — not the plumbing, the concept and why it is shaped that way. This is
> a focused companion to [`stakeholder-overview.md`](stakeholder-overview.md) §5, which gives the
> module-and-evidence specifics.
> **How to read the numbers:** every measured result is tagged **[proxy]** (dev-box proxy fleet —
> mechanism/regression only, and systematically optimistic) or **[production]** (real production data — the
> real efficacy number). A bare, untagged efficacy number would be a defect. The convention is canonical in
> [`environments.md`](environments.md).
> **Status:** v1, 2026-07-15.

## The shared idea: a narrowing funnel with one discipline

GroundLoop's loop is `ticket + logs → MATCH owning repo → localize → fix → bind`. The three *working*
stages — **Match, Localize, Fix** — form a **narrowing funnel**:

- **Match** takes 130+ candidate repos down to **one** (the predicted owner).
- **Localize** takes that one repo down to a **handful of files**.
- **Fix** takes those files down to a **concrete patch**.

Two principles sit under all three and are the reason to trust what comes out:

1. **Grounding over narrative.** Every decision is backed by a signal reality can verify — a symbol that
   actually exists in the code, a file that resolves — never by unverifiable model prose. Each stage leaves
   an auditable evidence trail: *why* a repo won (which tokens hit), *which* files were surfaced, *whether*
   a proposed fix could be grounded.
2. **The loop is never told the answer.** The owning repo is a **predicted output and hidden-oracle field,
   never a loop input**. There is no argument through which ground truth could enter the loop, so a good
   score means the mechanism *earned* it rather than being handed it.

And all three stages have the **same shape**: *retrieve candidates, then decide — with the standing option
to abstain.* The right to say "I don't know" runs through every stage by design, because the scoring system
is built so an honest abstention beats a confident wrong answer (that is the whole point of the `Φ_c`
metric — see [`stakeholder-overview.md`](stakeholder-overview.md) §8). What differs between the stages is
*what* is being retrieved and *what* the decision costs if it is wrong.

---

## 1. Match — *"which repo owns this defect?"*

**Concept: ticket→repo matching is a cross-repo *retrieval* problem, not a *reasoning* problem.**

When a tester files a bug, the discriminating evidence is usually already sitting in the failure logs — a
fully-qualified class name, a shared-library (`.so`) name, a native stack frame, an exception type. The bet
is that these **signals can be grounded against a real cross-repo index** (the *atlas*, a searchable store
of every repo's code units): the repo that actually *contains* the symbols a crash names is very likely the
repo that *owns* the crash. So Match does not "reason about" ownership. It ranks every repo in the fleet by
how much of the ticket's extracted signal hits that repo's real code, and the top-ranked repo is the
prediction — carrying, alongside its score, the exact matched tokens that earned it. You can read *why* a
repo won.

Three ideas make this stage conceptually sharp:

- **The owning repo is predicted, never given.** The system is built so the matcher *cannot* be told the
  answer — that is what makes a match score mean something. If the ticket text happened to name the repo,
  that is a **leak**, and it is scrubbed out before the loop sees it; otherwise "matching" would collapse
  into trivial string lookup rather than genuine behavioural attribution.
- **Match is the gate.** Localize and Fix are pure wasted effort if you are in the wrong repo, so Match is
  the primary objective and the stage measured hardest (`recall@1`, `recall@k`, `MRR`, plus cost per matched
  ticket).
- **The hard part is *within-family* confusion.** Telling one media/audio repo from another that looks
  almost identical is where a real triage engine earns its keep. Naive keyword matching (the `flood`
  baseline) is *size-biased* there — big repos win by sheer surface area. The lever that actually moved the
  real number was a **learned component→repo affinity prior** (which JIRA component has historically owned
  which repo), which lifted match `recall@1` **0.10 → 0.50** `[production]` (`recall@3` **0.90**
  `[production]`). On the single end-to-end production run, Match scored **7/10** `[production]`. Alternative
  matching strategies exist as opt-in arms but are `[proxy]`-only so far (e.g. functional/dispatch `recall@1`
  **0.68** vs flood 0.32 `[proxy]`).

Under the hood the atlas offers two grounding modes for the same idea: **membership** (does this signal
token literally exist in this repo's code? — pure keyword, fully offline) and **semantic** (embedding
similarity, to recover prose-heavy logs where exact keywords fail). Membership for signal-rich crash logs,
semantic for prose — but both answer the same question: *whose code does this evidence point at?*

---

## 2. Localize — *"where inside that repo?"*

**Concept: the same grounding idea, scoped down from the fleet to a single repo.**

Once Match has chosen a repo, Localize asks the next question with the same machinery, just narrowed:
retrieve the suspicious files and functions *within* that one repo by querying its code units with the
ticket's signals. Conceptually it is Match's little sibling — retrieval over the atlas — but two differences
matter:

- **Single-target vs. many-valid.** Match has *one* correct answer (exactly one repo owns the defect), so
  its metric is exact-match. Localize has a *set* of legitimately-relevant files (a fix can touch several),
  so it is scored as an "any-of" retrieval — did the right files show up in the top-k?
- **It runs *before* Fix, and that ordering is load-bearing.** Because localization happens first, anything
  injected later at the fix stage cannot change *what got localized*. This keeps localization quality and
  fix quality cleanly separable — you can measure a change to the fix stage without it secretly moving the
  localization number.

The current frontier here is **rank-1 precision**. Finding the right file *somewhere* in the top five is
much easier than ranking it *first*: on the production run, plain keyword localization got **7/10 file@5**
`[production]` but only **1/10 file@1** `[production]`. "We found it but didn't rank it first" is the gap,
and it is why there are experimental localize arms that query on the crash's *code tokens* rather than the
ticket's prose summary — one such arm lifts isolated `file@1` to **0.166** `[proxy]` (still awaiting a
production read). The concept holds: better grounding of the *query* against the *code* is the lever, not
more reasoning.

---

## 3. Fix — *"propose a patch — or honestly abstain"*

**Concept: this is the only *generative* stage, so its load-bearing idea is refusal, not generation.**

Match and Localize are retrieval — they rank things that already exist. Fix has to *produce* something new,
and that introduces a failure mode the other two simply do not have: **fabrication** — a model confidently
writing a patch that references code which does not exist, or that edits outside the localized scope. The
governing principle is blunt and it flips the usual instinct: **a confident wrong fix is worse than no
fix.** So the design does not just "generate a patch." It runs a grounded plan-then-act loop:

> **plan** the fix → **ground-check the plan** against the localized scope (*before* reading any disk) →
> **re-plan** if it does not ground → **abstain** (emit an empty patch) if it still cannot be grounded →
> **execute** → **re-check the executed diff** against scope.

That is "Bug Plan Mode." The point is not that it fixes *more* bugs — it is that when it *cannot* ground a
fix, it says so instead of hallucinating one. This mirrors, at the code level, the same "honest abstention
beats a confident wrong answer" principle the scoring system enforces at the metric level.

Two measured facts capture exactly this split:

- **Its proven property is honesty, not (yet) effectiveness.** Bug Plan Mode measures `fabrication_rate =
  0.0` `[proxy]` — with a recorded case where it abstained precisely where a naive fixer fabricated a patch.
  Whether it actually *resolves* more bugs (`resolved_rate`) is still **unproven and production-gated**: on
  the dev box the metric has never been gradeable (the synthetic crash logs are disconnected from the real
  fix, so nothing resolves), and the OSS proxy fleet has too few genuine crash-with-fix cases to decide it.
- **The one production read was ungraded, honestly.** On the production run, Fix scored **0/10** but
  **ungraded** `[production]` — an *empty-worktree artifact* (the owner repos were not checked out, so any
  real fixer would fabricate paths), **not** a fix-stage failure. The scheduled `[production]`
  `resolved_rate` A/B (plan vs. single-shot model) is what will finally confirm Fix into the production core
  or revert it.

(The fourth stage, **Bind** — persisting the auditable JIRA↔commit chain — is deliberately still *mocked*
at both ends; it carries no efficacy claim. See [`stakeholder-overview.md`](stakeholder-overview.md) §5.)

---

## The thread that ties them together

Read as one machine, the three stages are the same idea applied at three resolutions, and they share two
properties that are the source of the whole system's trustworthiness:

- **A standing abstain option.** Match can refuse to guess when its top-1-vs-top-2 margin is too thin;
  Localize surfaces auditable candidates rather than asserting one file; Fix abstains rather than fabricate.
  None of the three is forced to produce a confident answer it cannot ground.
- **An evidence trail at every step.** The matched tokens behind a repo score, the retrieved files behind a
  localization, the grounded plan behind a patch — each decision is inspectable against reality, not taken
  on the model's word.

That is "grounding over narrative" expressed three times over — and it is exactly why GroundLoop's scoring
rewards an honest "insufficient evidence" over a confident wrong answer. The funnel narrows 130+ repos to a
patch; the discipline makes each narrowing *earned*.

**Canonical source:** [`charter.md`](charter.md) §2 (the four stages) · [`architecture.md`](architecture.md)
§2–3 (ports + the `run_ticket` pipeline) · [`capabilities.md`](capabilities.md) §3 (arm/state evidence) ·
[`results-log.md`](results-log.md) (the tagged numbers) · [`fix-loop.md`](fix-loop.md) (Bug Plan Mode) ·
[`stakeholder-overview.md`](stakeholder-overview.md) §5, §8 (the module/evidence table + the `Φ_c` scoring
rationale).
