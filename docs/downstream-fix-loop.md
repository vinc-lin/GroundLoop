# GroundLoop — Downstream Fix Loop (design provenance)

> **Design-provenance snapshot — as of 2026-07-04.** This doc records the *design* of the post-match
> stages of GroundLoop's control plane — **localize → fix → grade → bind** — the part that runs *after*
> Stage-1 ticket→repo matching has picked an owning repo.
>
> **State of the code, plainly:** in GroundLoop today the **fix** stage is a `CannedFixEngine` **stub**
> (`groundloop/adapters/fix/canned.py`), **localize** is a placeholder step in the control plane, and
> the real **`AgentFixEngine` + tiered grader are FUTURE work** (see [roadmap.md — planned](roadmap.md)).
> The only grader that exists is the offline function `grade(record, oracle) -> Scores`
> (`groundloop/grade/grader.py`) — the tier ladder below is its target shape, not its current one.
>
> The actively-evolving experiments for this loop live in the **sibling `loop-agent` repo** (the
> **bfl** / "Bug-Fixing-Loop" fix-loop experiment, remote `bug-fixing-loop.git`) — a *separate* repo
> with its own `bfl` package and CLI. This doc absorbs bfl's v2 design as GroundLoop's design
> provenance, re-skinned to GroundLoop conventions. Primary sources, linked, not copied:
> [bfl v2 design spec](../../loop-agent/docs/superpowers/specs/2026-07-02-bug-fixing-loop-v2-design.md),
> [bfl architecture](../../loop-agent/docs/architecture.md),
> [bfl MVP plan](../../loop-agent/docs/superpowers/plans/2026-07-02-bfl-mvp.md).

`bfl` is a *separate* CLI in a *separate* repo. **GroundLoop's CLI is `gloop {run, index, produce,
doctor}`** and has **no** fix-loop subcommands yet — every `run / grade / board / compare / frontier`
surface named below is **aspirational for GroundLoop** (built in bfl, not in `gloop`). See
[architecture.md](architecture.md) for the hexagonal plane split this loop plugs into and
[charter.md](charter.md) for Stage 1–4 framing.

---

## 0. The load-bearing invariant (read first)

**The owning repo is a predicted output + hidden-oracle field — never a loop input.** This is
GroundLoop's Stage-1 core objective and it *supersedes* the bfl design at exactly one point: bfl
materializes the buggy tree from a `repo.json` that **names the owning repo as an input** (§3 below).
GroundLoop does not get that gift — its **match** stage (`CodeIndex.rank_repos`) must *predict* the
owning repo among 130+ before anything downstream runs, and the true owner lives only in the offline
oracle. So when reading any bfl artifact that hands the repo to the loop, treat it as
**GroundLoop's `_oracle` field, not GroundLoop's input.** Everything else in this doc — the tier
ladder, the anti-leak materialization, the eval harness — transfers as-is.

The other invariant is shared and unchanged: **the loop never sees the oracle.** Grading is a
separate offline pass (`groundloop/grade/grader.py`), structurally unable to feed the loop.

---

## 1. The grader tier ladder + authority rule

Grading is **capability-based and deterministic-first**: apply only the checks the oracle can support,
strongest-*grounded* first. No tier is a narrative judgment; the LLM rubric is advisory only. **No
Tier-3 build/test execution exists yet** — for AAOS a full Soong/Make build + Cuttlefish run is
hour(s)-long and multi-GB, so **deterministic file-localization + required-apis carry the practical
signal** today.

| Scorer | Tier | Needs (in oracle) | Grounded | Status | Check |
|---|---|---|---|---|---|
| Localization (file) | 1 | `localization.expected_files` | yes | **target MVP** | file-recall@k vs truth set (language-agnostic) |
| RequiredApis | 1.5 | `required_apis` | yes | **target MVP** | patch's added lines reference the right helper(s), whole-word |
| Localization (CST node) | 1 | `expected_files` + node truth | yes | deferred | CST-node-recall@k — needs a tree-sitter backend + node-level truth (neither in seed) |
| PatchSim | 2 | `fix_patch` | yes | deferred | structural AST/CST node-overlap — needs tree-sitter + `fix_patch` (absent in seed) |
| Tests | 3 | `tests` / `test_patch` | yes | declared, skipped | apply model patch ⟂ held-out test patch; run f2p+p2p — needs AOSP build/exec |
| RubricJudge | — | `rubric` | **no** | optional, off | blinded LLM PASS/FAIL — advisory only |

**Authority rule** — report all applicable tiers; the single `resolved` bit is set by the strongest
applicable **grounded** authority:

```
Tests  >  PatchSim  >  {Localization ∧ RequiredApis}  >  (none → None)
```

The bracketed conjunction is a *combined* authority — **both** must pass — recorded as a set of tiers
(e.g. `{LOCALIZATION, REQUIRED_APIS}`). The LLM rubric is **never** the grounded authority; it is
reported as an advisory `rubric_verdict`. For AAOS and the current seed the practical authority is
almost always `{Localization ∧ RequiredApis}`, so **the fix stage must emit both a structured
`locations` artifact and a `fix.patch`** (RequiredApis inspects the patch's added lines). Tasks whose
only applicable check is the rubric grade to `resolved = None` and are excluded from the headline rate
(reported separately as advisory-only).

Metric definitions are borrowed (SWE-PolyBench file+CST retrieval, CoSIL's deterministic Top-k
`FLEvalNew.py`, ARISE Line-Recall@1 vocabulary); the backend is ours. Diff-ref extraction —
`extract_refs(diff, gold_tokens) → (referenced_symbols, touched_files)` — will power Tier-1 (touched
files vs `expected_files`) and Tier-1.5 (symbols vs `required_apis ∪ gold_symbols`, whole-word); it is
**to be ported from the `knowledgeLoop` eval stack** (`extract.py`) and is **not resident under
`groundloop/` today** (see the migration-source docs at [`../../knowledgeLoop/docs/`](../../knowledgeLoop/docs/)).

---

## 2. The dataset / oracle JSON schema (Multi-SWE-bench-style)

Each benchmark entry is a directory; **the loop reads `ticket.json` + `repo.json` only**. Everything
under `_oracle/` is off-limits to the loop and read only by the offline grader.

```
dataset/<KEY>/
  ticket.json     # mock JIRA ticket — what the loop sees at intake
  repo.json       # how to materialize the buggy tree (see §0: in GroundLoop the repo NAME is oracle, not input)
  logs/           # attachments; empty for seed tasks, populated for real bugs
  _oracle/        # HIDDEN — never mounted into the loop's filesystem
    oracle.json
    root_cause.md # optional narrative reference — ONLY for the optional LLM-judge tier
  meta.json       # provenance, tags, leakage_control note, known per-model baselines
```

`oracle.json` carries the MVP-grounded fields plus **Multi-SWE-bench north-star field names** (`base`,
`fix_patch`, `test_patch`, `tests.{fail_to_pass, pass_to_pass, skip_to_pass, none_to_pass}`) for
citability against that benchmark family:

```json
{
  "localization": { "expected_files": ["cl_image_scaler.cpp"],
                    "gold_symbols": ["CLImageScaler::set_scaler_factor"] },
  "required_apis": ["XCAM_DOUBLE_EQUAL"],
  "prior_art_files": ["base/xcam_defs.h"],
  "base":      { "repo": "libxcam-ocl", "sha": "<fix^>" },
  "fix_patch": null,
  "test_patch": null,
  "tests":     { "fail_to_pass": [], "pass_to_pass": [], "skip_to_pass": [], "none_to_pass": [] },
  "rubric":    "Pass iff raw == is replaced with XCAM_DOUBLE_EQUAL."
}
```

`localization` / `required_apis` are the MVP oracle (what the migrated task TOMLs already carry);
`fix_patch` / `test_patch` / `tests` are the deferred Tier-2/3 north-star fields. `prior_art_files` is
leakage bookkeeping (where a cross-repo helper lives) and is **not graded**. The `base` SHA is
`fix^` — the commit *before* the fix (§3). **Note:** the `base.repo` value `libxcam-ocl` above is
bfl's xrepo-split example name and is **not** one of GroundLoop's three built corpora — those are
`ndk-samples`, `libxcam`, and `android-gpuimage-plus` (pinned in `corpora/corpus.toml`), the seed
corpora carried over from the migration source; see the [charter](charter.md) fleet-layers section for
how these relate to the 130+ AAOS production target.

---

## 3. Anti-leak git-archive materialization (`@base = fix^`)

The tree handed to the loop **must not be able to reach the fix.** Materialization is deliberately
history-scrubbing:

- **`git archive <base> | fresh init`** — snapshot the mirror at `base = fix^` into a *new*
  single-commit repo, so there is **no upstream history to mine**. For real bugs, strip the **fix
  commit and all post-fix commits, branches, and tags**, then verify `git log` / `git show` cannot
  reach the fix. (SWE-bench Pro #93 shows agents *will* mine future history and tags if left reachable.)
- **The `test_patch` is never placed in the tree the loop sees** — it is applied *only* inside the
  grader at Tier-3 (fix-added tests leak the location; cf. Data Cleanness in Defects4J).
- **Prefer temporal (post-model-cutoff) selection** for real bugs.
- **Cross-repo retrieval is a required challenge, not leakage.** Writes are confined to the single
  `@base` work-tree; sibling repos are mounted **read-only** so localize/fix can find a helper that
  legitimately lives in another repo (the migration source's xrepo split demonstrates this: the answer
  helper sits in a sibling repo, un-greppable from the work-tree, and `meta` proves "0 hits in the
  work-tree"). The oracle is still never exposed.

In GroundLoop this is the **materialize** stage (`RepoEstate.materialize(repo) -> WorkTree`;
`MockEstate` in `groundloop/adapters/estate.py` is the current hermetic substrate). The bfl scrubbing
recipe is the design target for a real materializer. The leakage boundary is enforced *in code* — the
runner exposes only the work-tree + `ticket.json` (+ read-only siblings) and never copies `_oracle/`
into the loop's reachable filesystem; provider-specific hooks are defense-in-depth, not the primary
guarantee. This mirrors the Type-1 hermetic anti-leak invariants already asserted in the suite (see
[groundloop-testing-strategy.md](groundloop-testing-strategy.md)).

---

## 4. The eval harness surface (board / compare / frontier, $/solved)

The fix loop is *also* a benchmark: run the pipeline across a dataset subset, grade offline, and diff
runs so quality-per-dollar can be optimized after every change. **In bfl this is
`bfl {run, grade, board, compare, frontier}`; there is no `gloop` equivalent yet — treat the whole
surface as aspirational for GroundLoop** (mapped onto a future `gloop` fix-loop track in
[roadmap.md — planned](roadmap.md)).

- **run** → produces a `RunRecord` (config + per-bug outcomes); `grade` (the offline pass) is
  auto-invoked.
- **board** → scoreboard for one run.
- **compare** `--base A --head B` → the optimization diff: `Δresolved_rate`, `Δcost_per_solved`,
  **`newly_solved`**, **`newly_broken`** (regressions named explicitly), `localization_moved`.
- **frontier** `--models …` → model × metric grid with **cost-per-solved**.

**Metrics (MVP):** `resolved_rate` (headline, computed **only over grounded-gradeable tasks** —
`resolved == None` tasks are excluded from the denominator and reported separately as advisory-only);
`file_recall@1/@k`; `required_api_pass_rate`; `cost_total`, `cost_per_bug`, `cost_per_solved`, tokens;
p50/p95 latency; `timeout_rate`. Deferred with the AST backend: `cst_node_recall@k`, `line_recall@1`.

**Cost is first-class and model-portable.** bfl routes through `litellm` and defaults to cheap models
for routine runs. For GroundLoop specifically, the environment's gateway serves
**deepseek-chat / deepseek-reasoner + bge-m3 / mxbai / qwen3 (no OpenAI)**, and `produce` is
live-validated on **deepseek-chat** (the working default) — so a future `AgentFixEngine` targets the
same gateway. A **validation self-test** anchors correctness: replaying known per-model baselines from
`meta.baselines` must reproduce their pass/fail split (runner + grader together). All GroundLoop config
is env-only via **`KLOOP_*`** (see `groundloop/config/settings.py`); the embedder used by any
retrieval arm stays pinned to **bge-m3** — query-time must equal index-time or cosine ranking is
silently corrupted.

Retrieval, skills, and bounded grounded refinement are all exposed as **measured eval arms** in bfl
(`RunConfig.retriever` / `.skills` / `.max_refine`), never trusted inputs — "does injecting this help?"
is answered by `resolved_rate` / `cost_per_solved`, not assumed. Grounded refinement triggers only on
**in-world deterministic signals** (`git apply --check` fails → re-run fix; a cited location does not
resolve → re-run localize), **never** the oracle.

---

## 5. Reconciling bfl's 4-step pipeline with GroundLoop's 8-stage `run_ticket`

bfl's pipeline is **Intake → Locate → Localize → Propose-fix** (a *fixed* Agentless-style code-driven
pipeline). GroundLoop's control plane (`groundloop/core/workflow.py`, **FROZEN**) is the fuller
8-stage `run_ticket`: **intake → extract → match → materialize → localize → fix → submit → bind**. They
map like this:

| bfl step | GroundLoop `run_ticket` stage(s) | Note |
|---|---|---|
| **Intake** (ticket + materialize `@base` work-tree) | **intake** + **materialize** | GroundLoop splits ticket-fetch from tree-build |
| *(none — repo given via `repo.json`)* | **extract** + **match** | **The key divergence.** GroundLoop *predicts* the owning repo (`SignalExtractor.extract` → `CodeIndex.rank_repos`); bfl is handed it. See §0. |
| **Locate** (select project/scope within the given repo) | folds into **match** / localize scope | bfl MVP = whole work-tree; GroundLoop's scope is the matched repo |
| **Localize** (structured `locations` artifact) | **localize** | placeholder step in GroundLoop today |
| **Propose-fix** (`fix.patch` + free-text `diagnosis`) | **fix** (`FixEngine.propose`) | **`CannedFixEngine` stub** today; `AgentFixEngine` is future |
| *(none — JIRA mocked / out of scope in bfl)* | **submit** + **bind** | GroundLoop closes the JIRA↔commit chain via `ChangeSink.submit` + `.bind` |
| **Grade** (separate offline pass) | `grade(record, oracle)` — **not a `run_ticket` stage** | offline function, never imported by the loop |

Two structural consequences of the mapping:

1. **GroundLoop adds the two ends bfl mocks away.** bfl mocks JIRA and stops at the patch; GroundLoop
   owns the front (extract + match, the Stage-1 objective) and the back (submit + bind, the traceable
   JIRA↔commit chain). bfl's `MockJiraSource` corresponds to GroundLoop's `IssueSource` port
   (`MockJira` adapter); bfl has no analog of `ChangeSink`.
2. **`repo.json`-as-input is superseded.** bfl's `diagnosis.json` free-text stays a non-graded
   scratchpad in both worlds (grounding over narrative — the least verifiable output is never an
   authority). But bfl's habit of *reading the owning repo from `repo.json`* is replaced by
   GroundLoop's match prediction; the repo name becomes an `_oracle` field consumed only offline.

The cognition/control split is identical to bfl's two planes — the deterministic Python plane owns
sequencing/state/invariants and never reasons; the model plane (behind the `Model` /future
`FixEngine` ports) reasons and never decides control flow. See [architecture.md](architecture.md).

---

## References

- **bfl v2 design spec** — [`../../loop-agent/docs/superpowers/specs/2026-07-02-bug-fixing-loop-v2-design.md`](../../loop-agent/docs/superpowers/specs/2026-07-02-bug-fixing-loop-v2-design.md)
- **bfl architecture** — [`../../loop-agent/docs/architecture.md`](../../loop-agent/docs/architecture.md)
- **bfl MVP plan** — [`../../loop-agent/docs/superpowers/plans/2026-07-02-bfl-mvp.md`](../../loop-agent/docs/superpowers/plans/2026-07-02-bfl-mvp.md)
- **bfl roadmap** (first-A/B, deferred tiers) — [`../../loop-agent/docs/roadmap.md`](../../loop-agent/docs/roadmap.md)
- **Migration-source engines + eval stack** (cost card, diff-ref extractor, frontier eval machinery — to be ported, not yet resident under `groundloop/`) — [`../../knowledgeLoop/docs/`](../../knowledgeLoop/docs/)
- **GroundLoop siblings** — [charter.md](charter.md) · [architecture.md](architecture.md) · engines.md (planned) · roadmap.md (planned) · [groundloop-testing-strategy.md](groundloop-testing-strategy.md) · [m1-index-build.md](m1-index-build.md) · [../CLAUDE.md](../CLAUDE.md)
