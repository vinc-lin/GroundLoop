# KB Fair-Evaluation — Phase 2 design (a real-fix substrate the KB can actually be tested on)

**Status:** design, 2026-07-13. Follows Phase 1 (`2026-07-12-kb-fair-eval-phase1-design.md`). Proxy-only; no production deploy.

## Context — what Phase 1 settled, and the crux it exposed

Phase 1 fixed the *harness* (resolution is now gradeable via synth-planted `required_apis`; `fixeval
--skills-inject fix-only` isolates the KB from the localize query) and produced two clean findings on a
34-case slice: `fix-only` is provably localize-invariant, and injecting skills into the localize query
**degrades** localization by Δ−0.10 file@1 (much of the old "raw KB HURTS" was that confound). **But the KB's
fix-content value stayed untestable:** `resolved_rate = 0.0` in every arm — the fix loop abstained on ~all
cases because a **synthetic crash log is disconnected from the real PR fix**, so no patch resolves.

That exposes the crux Phase 2 must solve. The two properties fight each other on the substrates we have:

| Substrate | KB fires? (needs crash-log signal) | Resolution achievable? (needs a real, reconstructable fix) |
|---|---|---|
| **Synth logs** (Phase 1) | ✅ built to fire the skill | ❌ synthetic log ≠ the real fix → 0 resolution |
| **Raw mined issues** (user prose) | ❌ no stacktrace → skills don't select | ✅ real issue + real merged PR |

Neither works alone. **Phase 2 needs a substrate with BOTH.**

## Goal

Measure whether the dev-experience KB improves `resolved_rate` on **real AAOS-fleet bug-fixes whose issue
already contains a crash log/stacktrace** — so the KB *fires* on the real signal AND the fix is *achievable*.
A `[proxy]` read; a genuine positive → KB **Candidate → (stronger) Candidate** with a `[production]` read
still required for Core.

## Design

### A. Mine "real-crash-with-fix" cases (`gloop mine` extension)

Extend the miner to select and enrich a new case class:
1. **Filter for a real crash signal.** Keep issues whose body contains a stacktrace / crash log — reuse the
   KB's own `[skill.match]` signatures (SIGSEGV/SIGABRT/`FATAL EXCEPTION`/ANR/…) as the inclusion filter. This
   guarantees at least one KB skill *fires* on the real text (no synth needed).
2. **Extract `required_apis` from the real fix.** From the linked merged PR's diff, harvest the APIs/symbols
   the fix *added* (added-line identifiers / call targets) → `required_apis` (replaces the miner's hard-coded
   `[]`). This is the Phase-2 replacement for synth-planting, and it fixes the loop-wide "resolution
   never gradeable" gap on *real* data. Anti-leak: an API token names no repo; the leak red-test still runs.
3. **Preserve the real issue text** (do NOT scrub→synth it) — the real bug description is what makes the fix
   reconstructable. Keep the existing scrub of repo-name leakage only.

Output: real cases with `{real issue text incl. stacktrace, expected_files, required_apis}` → both KB-firing
and resolution-gradeable.

### B. The A/B (reuses Phase 1's harness — no new fix-loop code)

`gloop fixeval` on the mined real-crash slice, `--fixer direct` (and a `plan` confirmation):
- `none` · `kb --skills-inject fix-only` (the fair arm) · `kb --skills-inject both` (confound control).
Grade on **`resolved_rate` / `required_api_pass_rate` / `fabrication_rate`**, `file_recall` as the
localize-invariant control. Verdict via `strengthened_accept`. **Acceptance:** KB helps iff Δ`resolved_rate`
> 0 with Δ`fabrication_rate` ≤ 0 **and** base `resolved_rate` > 0 (headroom exists — the Phase-1 failure mode
must not recur; if base is still ~0 the slice is inadequate and we say so, not "null").

### C. Grading fidelity (honest limitation + the upgrade path)

`resolved_rate` here is a **proxy**: patch applies ∧ touched files ∩ `expected_files` ∧ every `required_api`
referenced. It does **not** execute tests, so a patch can "resolve" without truly fixing the bug. The gold
standard is execution-based (SWE-bench FAIL_TO_PASS). **Rigor upgrade (Phase 2b, only if 2a shows a signal):**
adopt test-execution resolution on a subset. Note the domain trade-off recorded during brainstorming: our KB
is AAOS-specific, so SWE-bench's Python corpus would need a matching Python KB — hence Phase 2a stays on the
AAOS fleet with the proxy metric, and 2b is a targeted rigor check, not a wholesale switch.

## Data flow

`gloop mine` (crash-signal filter + PR-diff `required_apis` + real text) → real-crash slice → `gloop fixeval`
(`none` / `kb·fix-only` / `kb·both`) → `grade_fix_all` (`resolved_rate`, base > 0) → `strengthened_accept` →
verdict → `capabilities.md` / `results-log.md`.

## Testing (hermetic)

- Miner: a PR-diff fixture → `required_apis` extracted from added lines (not `[]`); a crash-signal filter
  keeps a stacktrace issue and drops a prose-only issue; the leak red-test still passes.
- End-to-end (canned model): the real-crash slice makes `resolved_rate.n > 0` gradeable and a KB skill fires
  on the real text (selection non-empty).

## Non-goals / out of scope

Production deployment (still gated on a `[production]` read, unreachable from the dev box); a full SWE-bench
integration (Phase 2b, conditional); changing the fixeval default injection to `fix-only`; multi-domain.

## Risks

- **Enough real-crash-with-fix cases?** AAOS-fleet OSS repos may have few issues with *both* a stacktrace and
  a linked merged PR. Mitigation: widen the fleet / relax to any crash-signal issue with an obvious fix
  commit; if N is small, report it as a weak-signal `[proxy]` read, not a verdict.
- **Proxy resolution** overcredits (§C) — mitigated by requiring `required_api_pass` and by the Phase-2b
  execution upgrade.
- **Base `resolved_rate` still ~0** would mean the substrate is still inadequate → we stop and rethink, we do
  NOT report a null (the Phase-1 discipline).
