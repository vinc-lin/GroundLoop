# Workflow Over-Design Audit & Simplification Plan

> **Status:** v1, 2026-07-15. **Provenance:** a code-grounded whole-workflow audit — a 5-slice parallel
> audit (match / localize / fix+KB / dev-labs / core+governance) → synthesis → **adversarial cut-safety
> verify** (workflow `wf_3650708f`, plus a recovered standalone localize audit). Triggered by the project
> owner's judgment that the workflow is over-designed and *localize is drifting from workable*. Every claim
> is anchored to code (`file:line`); each proposed cut's safety was adversarially verified — **one wrong
> recommendation was caught and dropped** (see DO-NOT).

## 1. Verdict

The over-design is **not** in the core loop or the primary stage's production path — those are lean and
healthy. It is in the **arms / eval / KB scaffolding layered around a system with exactly one production
run**, and in a recent habit of **promoting `[proxy]`-only arms to defaults** ahead of the `[production]`
read meant to authorize them. The owner's "localize is drifting from workable" instinct is the sharp edge
of that broader pattern.

## 2. Keep untouched — lean/healthy, verified (do NOT let the simplification touch these)

- **`core/`** — 172 LOC total (`workflow.py` 42 / `ports.py` 45 / `types.py` 85), 8 stages, 7 ports, frozen.
- **Match production core** — `ComponentPriorIndex` (RRF K=60 over the 12-line FTS5 base, honest loud
  degrade to flood), the one `[production]` lever `0.10→0.50` (`component_prior.py:26`, `atlas.py:17`).
- **`AtlasIndex.retrieve`** — plain FTS5 localize, the **only** localize path with a `[production]` number
  (`7/10 file@5`), and the byte-identical fallback floor of every other localize arm (`atlas.py:30-37`).
- **`ModelPatchEngine` (35 LOC) + `fix/patch.py`** — the lean fixer core (`model_patch.py`, `patch.py`).
- **Oracle-blind grading + `grade-run` self-scoring** — every `[production]` number came from
  `gloop run`+`grade-run`, not the standalone benchmarks. The honesty mechanism; keep intact.
- **Production-surface guards** — `KLOOP_DEV` dev-gate, the snapshot-verifying `--repos` guard, Fixture
  demotion (`cli/__init__.py:1081-1093`).

## 3. Over-design themes (grounded)

1. **Arm proliferation on secondary stages** — 7 `--match-arm` × 4 `--localize` choices; exactly **one of
   each** has a `[production]` number (`cli/__init__.py:761,775`).
2. **Proxy-chasing defaults dressed as governance** — `--localize tokens` and `--fixer plan` made
   **defaults** on `[proxy]`-only wins ahead of the resolving read; `tokens` is a self-declared exception
   to the fail-safe rule (`capabilities.md:113`, `cli/__init__.py:1005`).
3. **A KB stack governing an empty set** — ~1,022 LOC / 13 modules / 3 CLI subcommands + a 4-tier
   retain-loop, but `knowledge.json` does not exist → every KB arm is byte-identical to `none`
   (`kb/knowledge.py:50-57`, `kb/ab.py:44-55`).
4. **Measurement scaffolding out of proportion to one run** — 20 subcommands, 111 flags, 3,678 LOC of eval
   across 5 harnesses + `synth` (692 LOC); none produced a `[production]` number (`cli/__init__.py`).
5. **Effort-vs-priority inversion (key finding)** — of ~14 merged tracks, ~4 served FIX/KB (a *Later* stage
   that isn't gradeable + an inert KB) and ~1–2 the charter-**deferred** functional "second problem," while
   the **primary match gate** got essentially one track (its one validated lever) and its real open gap
   (rank-1 *within-component* disambiguation) is unaddressed (`docs/STATUS.md` Done list).
6. **Governance meta-process weight** — a 6-state model + a bespoke Provisional-Core exception whose
   most-exercised recent function is licensing unproven arms to be the default (`capabilities.md §1-2`).

## 4. Simplification plan

Guardrail on every item: **keep the capability selectable** (only change *defaults* and *menus*); **park or
archive, never hard-delete** a recorded result (governance); **no `core/` edits**; **green suite + ruff after
each cut**.

### DO NOW — verified safe
| # | Action | Target | Cut-safety (verified) | Files |
|---|---|---|---|---|
| 1 | Revert core localize **default** `tokens`→`atlas` | `_resolve_arms` (`cli/__init__.py:1005`) | Confirmed no-regret: `tokens` already degrades byte-identically to `atlas`; `atlas` is the `[production]` floor. `--localize tokens` stays selectable. | `cli/__init__.py`; `tests/run/test_localize_arm.py`; `tests/run/test_core_defaults_unchanged.py`; `CLAUDE.md`; `capabilities.md` |
| 2 | **Archive** `--localize dispatch` (`LocalizeDispatchIndex`) + drop the dead `is_functional_localize`/`PROSE_MARK` **routing** helpers (keep `code_query`) | `cli/__init__.py:1178-1193`, `localize_dispatch.py`, `functional_signals.py` | Doubly inert: never constructed under any default; `[production]` read `0/10`. Only its own tests + the (removed) menu choice depend on it. **Do not touch the match-`dispatch` arm at `:1140`.** | `cli/__init__.py`; `adapters/index/localize_dispatch.py`; `domains/android_ivi/functional_signals.py`; tests |
| 3 | **Park** `--localize semantic` (drop from the localize menu; keep `SemanticAtlasIndex` for match-side reuse) | `cli/__init__.py:1160-1174`, choices at `:775` | Measured negative at `file@1` (`audio 0.017→0.001`); `SemanticAtlasIndex` stays for `--match-arm semantic`. Labs localize default must move `semantic`→`atlas`. | `cli/__init__.py`; `tests/run/test_localize_arm.py`, `test_labs_profile.py` |
| 4 | **Park** `--match-arm judge` (drop from the run menu; keep `LLMJudgeIndex` for eval) | `cli/__init__.py:761,1131-1139` | Zero measured recall anywhere; nothing on the run path depends on it (eval keeps its own copy). | `cli/__init__.py`; tests |
| 5 | Reconcile `capabilities.md` governance states | `capabilities.md` | Doc-only. `tokens`→Candidate (reverted); localize-`dispatch`→Archived (measured null); localize-`semantic`→parked Candidate; `judge`→parked. | `capabilities.md` |

### DO NEXT — safe, larger
- **Collapse `functional`/`dispatch` match duplication** and park the functional second-matcher sub-stack
  (`FunctionalTextIndex`, `text_profile.py`/`build-textprofile`, `funceval`) — a full parallel apparatus for
  a charter-deferred problem.
- **Consolidate the arm-construction surfaces into one registry** — the verifier corrected the count:
  **four** (`cli/__init__.py`, `eval/arms.py`, `funceval/arms.py`, `faulteval/arms.py`), each with its own
  tau. Gate the merge on all three eval suites.

### DO NOT — blocker caught by the verify pass
- **Do not "merge routing into component."** Factually wrong (`FaultRoutingIndex` keys on log-derived
  sonames/prefixes via `FaultSignalExtractor`; `component` keys on the JIRA-component field — different
  mechanisms) **and unsafe** (deleting it breaks `--match-arm dispatch`, `funceval`, `faulteval`, and 5
  tests). Keep `FaultRoutingIndex`; just stop investing in `repo_routing.ROUTES/SONAMES` (a hardcoded
  proxy-fleet table, inert on GEI).

### REDIRECT — where freed effort goes (owner's steer + charter)
- **Match rank-1 within-component disambiguation** — the real open gap (`recall@3 0.90` but `recall@1 0.50`;
  the production misses were a CarPlay near-tie at a 0.005 gap + label≠owner cases). *That* moves the
  number, not a new arm.
- **Fix-gradeability** — check out the owner repos so fix stops being `0/10 ungraded` and the downstream
  half becomes measurable.
- **Process guardrail** — freeze proxy→default promotions: no new arm / harness / governance-state becomes
  a default until a `[production]` read pulls on it.

## 5. Execution log
- [x] Cut 1 — revert core localize default `tokens`→`atlas` (+ tests + `CLAUDE.md`) — committed `488c3a1`
- [x] Cut 2 — archive `--localize dispatch` (delete module/tests, drop `is_functional_localize`) — `3f1f0ab`
- [x] Cut 3 — park `--localize semantic` (+ labs localize default → `atlas`) — `905e94e`
- [x] Cut 4 — park run `--match-arm judge` (eval `--judge` kept) — `2b20870`
- [x] Cut 5 — reconcile `capabilities.md` governance states (this commit)
- (deferred to DO-NEXT: functional sub-stack park; arm-registry consolidation; stakeholder-doc arm-list sync)

Each cut lands only with the full suite green + ruff clean, `core/` and the atlas schema untouched.
