# Authored Tier-B Test Cases — Design

> **Date:** 2026-07-20 · **Status:** design deliverable → implementation plan next.
> **Provenance:** the realistic e2e-corpus initiative (`2026-07-19-e2e-eval-corpus-design.md`) shipped the
> machinery, but the real supply is **~1** crash-with-fix case (only 1 of 108 mine74 cases carries a crash log).
> Mining can't fill Tier B on the current fleet. So we **author** a small, high-quality Tier-B corpus ourselves,
> grounded in the real fleet's real code. **First principle — grounding over narrative:** these are honestly
> *authored*, labeled distinctly, never `[production]`, never mixed into the mined `[proxy]` reads.

## 1. The honest framing (load-bearing)

An authored case is a **designed probe**, not an observed defect. We ground it as hard as possible — every oracle
field is **verified to exist in real fleet source** — but *we* wrote the crash, so:
- **Role:** a **mechanics / capability test** — "does the pipeline carry a realistic-shaped crash **end-to-end**
  (match → localize → fix) over real code?" We have **zero** end-to-end substrate today, so this is the first.
- **Not:** an effectiveness measurement. It does not establish real-world performance.
- **Label:** a distinct **`[authored]`** tag, **never `[production]`**, never blended with the mined `[proxy]`
  corpus. Docs state plainly "designed, not observed."

## 2. Scope

**3 cases** to start (a deliberate pilot — validate the authoring method before scaling), **full Tier B** (each
carries a real/plausible fix diff so `resolved_rate` is gradeable end-to-end). Diverse by crash type + repo:

| case | repo | domain / language | crash shape |
|---|---|---|---|
| A | **oboe** | C++ native audio | native `.so` backtrace (`#00 pc … liboboe.so (Class::method+NN)`) |
| B | **newpipe** | Java/Kotlin Android | Java stacktrace (`Exception … at pkg.Class.method(Class.java:NN)`) |
| C | **dlt-daemon** | C, **automotive** (Diagnostic Log & Trace — AAOS-relevant) | native crash / assertion / SIGSEGV backtrace |

The exact file + symbol per case are **chosen from real source at authoring time** (not fabricated in this spec)
and verified by the validator (§4).

## 3. What each case is (grounded-authored)

A standard eval **case dir** (so the existing harness runs over it unchanged), every field grounded in real source:
- `ticket.json` — `id`, `summary`, `description`, `logs[]` (the crash log). Oracle-blind + **leak-safe** (no repo
  name / owner slug anywhere in the ticket text).
- `_oracle/oracle.json` — `owning_repo` (the real repo), `expected_files` (a **real** file path in that repo),
  `required_apis` (a **real** symbol/method/function in that file), `fix_patch` (the diff, §below), `is_answerable=true`,
  `bug_kind="crash"`.
- `logs/<name>.txt` — the crash log, which **names the real class/method/`.so`** so the matcher's extracted signals
  genuinely resolve to `owning_repo` through the fleet atlas.
- `fix.diff` (referenced by `fix_patch`) — a **real or plausible unified diff** touching `expected_files` and the
  `required_apis` on real code lines, so `resolved_rate_strict` (touched-files ∩ expected ∧ APIs on added code) is
  gradeable. "Plausible" = a minimal, realistic edit to the real code (e.g. a null-check / bounds-guard on the real
  crashing line); it need not be the upstream fix, but must be a coherent edit to the real file.
- A shared `catalog.json` (the fleet the matcher ranks over) at the corpus root.

## 4. The grounding validator (the anti-fabrication gate — hermetic)

`validate_authored_case(case_dir, repo_root) -> list[str]` (a new labs module, e.g. `groundloop/mine/authored.py`)
returns a list of problems (empty = valid). Checks, against **real source**:
1. `oracle.expected_files` each **exists** as a real file under `repo_root/<owning_repo>/`.
2. each `required_apis` symbol **appears** in that real file's source.
3. the crash log **names** at least one oracle symbol/file/`.so` (so match/localize signals are grounded, not
   invented).
4. **leak-safety:** the `owning_repo` name/slug does **not** appear in `ticket.json` text (summary/description/logs).
5. `fix.diff` targets `expected_files` and references `required_apis` on added (`+`) code lines.
This is the guarantee that "authored" still means "grounded in real code," not "made up." It is **hermetically
testable** with a tiny fixture repo + a good case (passes) and a broken case (each check fails).

## 5. Where it lives / how it's run

- **Committed** under `groundloop/mine/data/authored/` (the corpus dir: `<case-id>/{ticket.json, _oracle/oracle.json,
  logs/…, fix.diff}` + `catalog.json`) — small, git-tracked; **this is the owned, reproducible corpus.** A README
  states the `[authored]` framing.
- **Run:** match + localize grade against the **real fleet atlas** (`/mnt/x/code/corpora/atlas-fleet.db`, off ext4,
  no gateway needed for FTS5); the **fix** stage + the full `render_e2e_funnel` need the gateway — **gated Type-2**,
  run by the user. The hermetic deliverable is the **cases + the validator + the validator tests**; a real funnel
  read over them is the gated follow-up.

## 6. Invariants / first-principle compliance

- **Honesty:** `[authored]` label everywhere; never `[production]`; docs say "designed, not observed"; the mechanics
  role is stated, not oversold as effectiveness.
- **Grounding:** every oracle field verified against real fleet source by the validator — no fabricated symbols/files.
- **Oracle-blindness + leak-safety:** the loop never sees `_oracle/`; the validator enforces no repo-name leak in the
  ticket.
- **No `core/` or atlas-schema edit;** the validator + cases are labs (`mine/`) + committed data.
- **Reuse:** cases use the standard case-dir format the existing `load_cases`/`load_eval_oracle`/`fixeval`/`grade`
  harness already consumes — no new loader.

## 7. Non-goals

- Not `[production]`, not an effectiveness claim, not a realism claim beyond "grounded in real code."
- Not a large corpus (3 to start; scale later only if the method proves out).
- Not mined (this is the authored complement to the mined `[proxy]` corpus, not a replacement).
- Not the upstream real fixes necessarily — a coherent plausible edit to the real crashing code suffices for Tier-B
  gradeability.

## 8. Module touch-map

| Change | Target |
|---|---|
| The grounding validator | new `groundloop/mine/authored.py` (labs) |
| Validator tests (fixture repo + good/broken cases) | `tests/mine/test_authored.py` |
| The 3 authored, grounded, validated cases + catalog + README | `groundloop/mine/data/authored/**` (committed) |
| Docs: the `[authored]` corpus + its role | `docs/evaluation.md`, `docs/STATUS.md` |
| Zero-diff | `groundloop/core/**`, atlas schema |

## 9. Open questions for the plan

- The exact real file + symbol per case — selected by reading real source at authoring time; the validator is the
  gate that they're real.
- Whether the 3 cases share one `catalog.json` (the whole fleet) or a minimal 3-repo catalog — plan picks (prefer
  the real fleet catalog so match ranks against confusable repos, not a trivial 3-way).
- The gated funnel read over the 3 cases (match+localize vs the real atlas; fix vs the gateway) is a follow-up, not
  a merge gate.
