# GroundLoop — Fix Loop (design provenance)

> **Design-provenance snapshot — as of 2026-07-04.** This doc records the *design* of the post-match
> stages of GroundLoop's control plane — **localize → fix → grade → bind** — the part that runs *after*
> Stage-1 ticket→repo matching has picked an owning repo.
>
> **State of the code, plainly (updated 2026-07-11):** the fix-loop **eval surface has shipped** — `gloop
> fixeval` / `gloop grade-run` / `gloop compare`, driven by the real **`ModelPatchEngine`**
> (`groundloop/adapters/fix/model_patch.py`), with **Tier-1 (file-recall) + Tier-1.5 (required-apis)**
> grading live in `groundloop/fixeval/scorecard.py`. **localize** is real (`AtlasIndex.retrieve`). `gloop
> run`'s fix stage still **defaults** to the `CannedFixEngine` stub (`groundloop/adapters/fix/canned.py`);
> the real engine runs via `--fixer model`. Still **design-target** (the tier ladder below is its target
> shape, not its full current one): the **Tier-2/3 grader** (AST/CST sim + AOSP build/test exec), a real
> fix engine as the `gloop run` *default*, and the `board`/`frontier` surfaces. The frozen `grade(record,
> oracle) -> Scores` (`groundloop/grade/grader.py`) is the thin single-case grader; `gloop grade-run` is
> the per-stage scorecard over the real loop.
>
> The actively-evolving experiments for this loop live in the **sibling `loop-agent` repo** (the
> **bfl** / "Bug-Fixing-Loop" fix-loop experiment, remote `bug-fixing-loop.git`) — a *separate* repo
> with its own `bfl` package and CLI. This doc absorbs bfl's v2 design as GroundLoop's design
> provenance, re-skinned to GroundLoop conventions. Primary sources, linked, not copied:
> [bfl v2 design spec](../../loop-agent/docs/superpowers/specs/2026-07-02-bug-fixing-loop-v2-design.md),
> [bfl architecture](../../loop-agent/docs/architecture.md),
> [bfl MVP plan](../../loop-agent/docs/superpowers/plans/2026-07-02-bfl-mvp.md).

`bfl` is a *separate* CLI in a *separate* repo. GroundLoop has since built its own fix-loop surface —
**`gloop {fixeval, grade-run, compare}`** (+ the KB arm, §5) — so the eval / `compare` surface below is
**real in `gloop`**, not aspirational; only bfl's `board` / `frontier` scoreboards remain bfl-only (mapped
to a future `gloop` track in [roadmap.md](roadmap.md)). See [architecture.md](architecture.md) for the
hexagonal plane split this loop plugs into and [charter.md](charter.md) for Stage 1–4 framing.

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
`touched_files` / `references_api` / `added_lines` — **powers** Tier-1 (touched files vs `expected_files`)
and Tier-1.5 (symbols vs `required_apis`, whole-word); it is **already ported** from the `knowledgeLoop` eval
stack (`extract.py`) and **resident** at `groundloop/fixeval/patch.py`, driving live Tier-1/1.5 grading in
`groundloop/fixeval/scorecard.py`.

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
[evaluation.md](evaluation.md)).

---

## 4. The eval harness surface (board / compare / frontier, $/solved)

The fix loop is *also* a benchmark: run the pipeline across a dataset subset, grade offline, and diff
runs so quality-per-dollar can be optimized after every change. **In bfl this is
`bfl {run, grade, board, compare, frontier}`; GroundLoop has built the equivalents as `gloop {fixeval,
grade-run, compare}`** — bfl's `run`+`grade` → `gloop fixeval` (+ `gloop grade-run` for the per-stage
scorecard over the real loop), `compare` → `gloop compare`. Only `board` / `frontier` (the scoreboard +
model×metric grid) remain bfl-only, a future `gloop` track ([roadmap.md](roadmap.md)).

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

**Skills arm — LANDED in `gloop` (SP3, 2026-07-06).** The dev-experience **KB** is now a real measured
arm on the SP2 fix loop: `gloop fixeval --skills {none, mock}` injects retrieved playbooks
(`groundloop/skills/` + `MockSkillRegistry`, seeded with real RCA/ops playbooks) as a `render_skills()`
preamble on `ModelPatchEngine` **post-match** — the frozen `FixEngine.propose` signature is untouched.
Value is decided by running the two arms and diffing with `gloop compare` → the two-sided **`accept`**
gate: a positive lift on `Δfile_recall@1` **and** no honesty regression (`Δfabrication_rate ≤ 0`), cost
advisory. Real Skills drop in post-migration via **§5 below** (contract + migration transform + parity
self-test). See the SP3 spec (`docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md` §3).

---

## 5. Dev-experience KB (a measured fix arm)

The dev-experience **KB** — real RCA/ops **Skills** authored by previous developers, living in another
environment — is wired as a **measured arm** on the fix loop (§4), **never a trusted input**. Today it
runs on a **`MockSkillRegistry`** seeded with real GroundLoop RCA/ops playbooks
(`groundloop/adapters/skills/data/aaos_playbooks.toml`) — "mock" is only the *wiring*; the content is
real. When the previous developers' Skills arrive (in that other environment's format) they migrate into
`Skill` records **unchanged**, swap in at the composition root, and are proven faithful by the **parity
self-test** — **no `groundloop/core/` edit, no SQLite schema change.**

**The `Skill` contract** (`groundloop/skills/base.py`):

```python
@dataclass(frozen=True)
class Skill:
    id: str                                 # stable, unique
    applies_to: Callable[[SkillCtx], bool]  # compiled from declarative data (below) — NOT hand-written code
    guidance: str                           # playbook text injected into the fix/RCA prompt
    hint_apis: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()           # retrieval tags
    provenance: str = ""                    # source doc/commit — KB traceability
```

`render_skills(skills)` renders selected Skills under a `# Applicable playbooks` header; an empty list
⇒ `""` ⇒ a **byte-identical no-op vs the `skills=none` arm**. The `SkillRegistry` Protocol is just
`select(ctx) -> list[Skill]`; `NullSkillRegistry` is the `none` arm.

**The `SkillCtx` contract + oracle-blindness rule** (`groundloop/skills/ctx.py`):

```python
@dataclass(frozen=True)
class SkillCtx:
    signals: Signals        # the arm's structured, extracted signals
    repo: Optional[str]     # the PREDICTED owning repo (a loop prediction, never the oracle)
    text: str               # lowercased haystack: ticket summary + description + all log content
```

`build_ctx(signals, ticket, repo)` builds it from **loop-visible inputs only**. **Oracle-blindness
rule: a predicate MUST NOT read the oracle** — no `expected_files`, no `required_apis`, no `_oracle/`
path (a KB that could read the oracle would smuggle the answer into its selection). Enforced by a
red-test, `tests/skills/test_invariants.py`. This is §0's load-bearing invariant applied to KB selection.

**The migration transform** (`groundloop/adapters/skills/migrate.py`). The primary source format is
**markdown + front-matter** (how the real dev-experience/superpowers Skills arrive); the secondary
`loop-agent/bfl` `Skill` dataclass migrates via `from_bfl_skill` (copies `id`/`guidance`/`hint_apis`,
carries `applies_to` as-is, **drops `tools`**, sets `signals=()` + `provenance="bfl:<module>"`).

| Front-matter / body | → `Skill` field |
|---|---|
| `id` | `id` (unique across the set) |
| `triggers: a, b` (comma-list) | `applies_to` (via `triggers_to_spec` → `compile_predicate`) + `signals` |
| `provenance` | `provenance` (defaults to `md:<filename>`) |
| markdown body (after the `--- … ---` block) | `guidance` |

- `migrate_markdown_skills(dir)` — parse each `*.md`'s front-matter + body → `Skill`; **raises on a
  duplicate id** (fail loud). (The seed loader `load_skills` does not enforce uniqueness — keep seed ids
  unique.)
- `triggers_to_spec(triggers)` — translate the foreign trigger vocabulary → a declarative match spec
  (union per key, de-duped). **`KeyError` on an undocumented trigger** — extend `_TRIGGER_MAP`.
- `compile_predicate(spec)` (`groundloop/skills/predicate.py`) — compile the spec into the closure.
  **Closed match vocabulary** (unknown key → `ValueError`; every `*_regex` compiled eagerly so a bad
  pattern fails at load, never mid-select): `always` (bool), `repo_in` (over `ctx.repo`),
  `any_text` / `all_text` / `any_text_regex` (over `ctx.text`), and `any_<family>` / `any_<family>_regex`
  for `family ∈ {packages, classes, methods, symbols, libraries, errors}` (over `ctx.signals.<family>`).
  **Semantics:** clauses are **OR'd** (the skill applies if ANY fires); a list within a key is OR'd;
  `all_text` is the AND escape hatch; an **empty spec never fires**.
- **No code in data** — predicates are declarative specs compiled to closures, never serialized lambdas /
  `eval` / `exec`. This is what lets a real Skill set swap in by replacing the *data*, and what makes the
  data reviewable for secret/leak hygiene. Always carry `provenance` so every injected playbook is
  traceable to its source.

**Composition-root swap** — the registry is chosen in `groundloop/cli/__init__.py::_run_fixeval` behind
`--skills {none, mock}`:

```python
if args.skills == "mock":
    skills = MockSkillRegistry.load(embedder=embedder)   # <- replace load() with the migrated registry
runner = FixEvalRunner(..., skills=skills)
```

To ship the real Skills, build the registry from the migrated records —
`MockSkillRegistry(migrate_markdown_skills(<dir>))` — at this **one call site**: no `core/` edit, no
runner change. **Reuse contract:** the optional rerank embedder is pinned **bge-m3** and gated on
`KLOOP_EMBED_BASE_URL` (query == index); the hermetic default is predicate-only.

**The parity self-test** (`tests/skills/test_migration_parity.py`) proves a migrated registry reproduces
the native seed's behavior:

1. Provide the SAME logical skills in **two genuinely different shapes** — a native declarative seed
   (`seed.toml`) and the foreign markdown (`md/*.md`) — **aligned** so the seed's match spec equals what
   `triggers_to_spec` produces from the markdown triggers (this is the point: it catches a mistranslated
   trigger).
2. Author a **discriminating ctx panel** (`build_panel()`): each skill matches a proper, non-empty subset
   (some ctx selects only A, some only B, some both, some none); a `test_panel_is_discriminating`
   meta-assert guards against a vacuous all-empty / all-match panel.
3. Assert **predicate-only** id-set equality across the panel — `select` with **no embedder** (the bge-m3
   rerank is Type-2 / non-deterministic without a fixed gateway and must NOT be in the parity assertion).
4. Add a **negative control**: corrupt one migrated predicate and assert parity **fails** on ≥1 ctx —
   proving the test has teeth.

**Constraints & honesty ceiling.** The registry reads **only its data file + the loop-visible
`SkillCtx`** — never `_oracle/`; grading (`groundloop/fixeval/scorecard.py`) is the sole offline oracle
read. The KB is a **measured arm**: its value is decided by the §4 `accept` gate, not assumed. The parity
test proves the transform **reproduces author intent + regression-guards `triggers_to_spec` + documents
the contract** — it does **not** prove semantic correctness in general; do not over-read a green run. The
mock seed is small, so the arm validates **plumbing + direction of effect**, not the full lift real Skills
will show: a near-zero Δ on the mock seed is a **`[proxy]`** mechanism check (dev box vs production,
[environments.md](environments.md)) — the real lift is a **`[production]`** number. **Troubleshooting:**
parity fails ⇒ seed spec and trigger map disagree (diff the per-ctx selections); `ValueError` at load ⇒
an unknown predicate key or a bad regex; `KeyError` in `triggers_to_spec` ⇒ an undocumented trigger (add
it to `_TRIGGER_MAP`); a skill firing on everything ⇒ an empty/`always` spec or an over-broad `any_text`
token.

---

## 6. Reconciling bfl's 4-step pipeline with GroundLoop's 8-stage `run_ticket`

bfl's pipeline is **Intake → Locate → Localize → Propose-fix** (a *fixed* Agentless-style code-driven
pipeline). GroundLoop's control plane (`groundloop/core/workflow.py`, **FROZEN**) is the fuller
8-stage `run_ticket`: **intake → extract → match → materialize → localize → fix → submit → bind**. They
map like this:

| bfl step | GroundLoop `run_ticket` stage(s) | Note |
|---|---|---|
| **Intake** (ticket + materialize `@base` work-tree) | **intake** + **materialize** | GroundLoop splits ticket-fetch from tree-build |
| *(none — repo given via `repo.json`)* | **extract** + **match** | **The key divergence.** GroundLoop *predicts* the owning repo (`SignalExtractor.extract` → `CodeIndex.rank_repos`); bfl is handed it. See §0. |
| **Locate** (select project/scope within the given repo) | folds into **match** / localize scope | bfl MVP = whole work-tree; GroundLoop's scope is the matched repo |
| **Localize** (structured `locations` artifact) | **localize** | real (`AtlasIndex.retrieve` → `locations`); a richer structured artifact is the target shape |
| **Propose-fix** (`fix.patch` + free-text `diagnosis`) | **fix** (`FixEngine.propose`) | `CannedFixEngine` stub in `gloop run`'s default; the real **`ModelPatchEngine`** runs via `gloop fixeval` / `--fixer model` |
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
sequencing/state/invariants and never reasons; the model plane (behind the `Model` + `FixEngine`
ports) reasons and never decides control flow. See [architecture.md](architecture.md).

---

## References

- **bfl v2 design spec** — [`../../loop-agent/docs/superpowers/specs/2026-07-02-bug-fixing-loop-v2-design.md`](../../loop-agent/docs/superpowers/specs/2026-07-02-bug-fixing-loop-v2-design.md)
- **bfl architecture** — [`../../loop-agent/docs/architecture.md`](../../loop-agent/docs/architecture.md)
- **bfl MVP plan** — [`../../loop-agent/docs/superpowers/plans/2026-07-02-bfl-mvp.md`](../../loop-agent/docs/superpowers/plans/2026-07-02-bfl-mvp.md)
- **bfl roadmap** (first-A/B, deferred tiers) — [`../../loop-agent/docs/roadmap.md`](../../loop-agent/docs/roadmap.md)
- **Migration-source engines + eval stack** (cost card, frontier eval machinery — to be ported, not yet resident under `groundloop/`; the diff-ref extractor is already resident at `groundloop/fixeval/patch.py`) — [`../../knowledgeLoop/docs/`](../../knowledgeLoop/docs/)
- **GroundLoop siblings** — [environments.md](environments.md) · [charter.md](charter.md) · [architecture.md](architecture.md) · [engines.md](engines.md) · [roadmap.md](roadmap.md) · [evaluation.md](evaluation.md) · [build-setup.md](build-setup.md) · [../CLAUDE.md](../CLAUDE.md)
