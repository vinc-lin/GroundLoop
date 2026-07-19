# Realistic End-to-End Eval Corpus — Design

> **Date:** 2026-07-19 · **Status:** design deliverable → implementation plan next.
> **Provenance:** the eval-surface audit (this session) found the effectiveness reads run on the **mine74 prose
> regime** (OSS feature/UI issues, ~0 logs) — a shape production never sends. The one time a `[proxy]` localize
> positive was checked against `[production]` GEI it was **0/10 INERT** (the dispatch arm), *because* the proxy
> tested prose-only tickets and real tickets carry logcat. The audit also found the eval scorecard is
> **over-built** (mrr/ndcg/abstention/negatives/KB all idle) while the *substrate* is the real weakness.
> **First principle — grounding over narrative:** trust only what reality verifies. This replaces the substrate
> with a small, REAL, uniform, full-end-to-end corpus and measures the whole loop honestly per stage.

## 1. Goal

Build a **realistic, full-end-to-end test-case corpus** (real crash-log GitHub issues closed by merged PRs) as
the substrate for effectiveness reads, and an **honest end-to-end funnel** that grades every stage on the *same*
cases — reporting submit/bind as the mock they are. Trim the eval to what this read uses. **Priority: high-quality
cases.** `core/` + the atlas schema stay **zero-diff**; the corpus builder + harness are labs.

## 2. What a case is — the quality bar (Tier B only, uniform)

Every case is a **real GitHub issue** that:
1. **carries a crash log / stacktrace / native-backtrace / logcat in its body** (the representative shape — this is the whole point);
2. **is closed by a merged PR** that touches production files (gives the fix + expected files);
3. lives in an **Android / native (C/C++/JNI) / AAOS-adjacent** repo (signals resemble the real fleet);
4. is **leak-safe** (reuse the miner's existing scrub + closed-loop owner-leak reject).

Its oracle covers the **whole chain**: `owning_repo`, `expected_files` (PR's touched production files),
`required_apis` (identifiers from the diff ∩ crash vocab), `fix_patch` (the diff), and the `issue`/`pr` refs +
pinned `base_sha`/`fix_sha`.

**Uniform** — no partial-oracle cases; if it can't be graded through fix, it is not in the corpus (this is why
Tier A / match-localize-only cases are excluded — they would mix populations and muddy the end-to-end funnel).
**Small n accepted** — real crash-with-clean-fix issues are scarce; the plan broadens the mined repo set to
maximize, and treats **~10–30 cases** as the honest expectation (small-but-real over large-but-fake). Honest-refusal
**negatives are excluded** (a different population that would reintroduce the multi-population confusion).

## 3. The committed case manifest (reproducibility)

A **version-controlled manifest** (`manifest.toml`/`.json`, committed to git) — one entry per case:
`{repo, issue_number, issue_url, pr_number, pr_url, base_sha, fix_sha, owning_repo, expected_files, required_apis}`.
This is the recipe + oracle. The **bulky data** (full logs, repo checkouts, the multi-GB atlas.db) stays off-repo
on ext4 and is **regenerable from the manifest** via `gh` + git at the pinned SHAs. This closes the audit's
"datasets are unversioned dev-box memory" gap: git shows exactly which real issues/PRs every number rests on, and
anyone can rebuild the identical corpus. **Public GitHub data only — no secrets, no LAN IPs, no `.env`.**

## 4. The corpus builder (extend the miner)

Extend the existing `groundloop/mine/` (`gh_miner`/`harvest`/`signal`/`scrub`/`emit`) rather than build anew:
- **Crash-log filter:** admit an issue only if its body matches a stacktrace/logcat/native-backtrace pattern
  (reuse/extend `mine/signal.py::classify`, which already splits prose-vs-log).
- **Merged-fix requirement:** require a merged-PR closer with production-file touches (reuse `harvest.py`'s
  issue→merged-closer + `filters.py::production_files`).
- **Broadened repo set:** target more Android/native/AAOS-adjacent repos (crash-issue-rich AND atlas-indexable —
  the plan picks the exact set).
- **Emit** the full-chain oracle (reuse `emit.py`) **plus the committed manifest**.
- Surfaced as a mining flag/mode (e.g. `gloop mine --require-crash-log --require-merged-fix`) or a thin
  `gloop build-e2e-corpus` wrapper — the plan decides (prefer reuse over a new command).

## 5. The end-to-end funnel harness (reuse `fixeval`/`grade`)

The crash-log corpus **unblocks the harness that already exists**: `gloop fixeval` currently 100%-abstains on
mine74 prose (match scores 0 → abstain), but real signal-bearing tickets let match score, so the loop reaches
localize and fix. So the harness is mostly **reuse**:
- Run the whole loop per case; `FixEvalRunner` + `grade_fix_all` already compute `file_recall@k`,
  `patch_apply_rate`, `resolved_rate_strict`, `required_api_pass_rate`, `fabrication_rate`.
- Add a **FUNNEL report** — one per-case table + a summary over the SAME N cases:
  `match recall@1 → localize file@1/@5 → fix patch_applies / resolved_rate_strict / required_api_pass`.
- **Submit/bind reported as MOCK** (a literal "mock — not scored; live Gerrit/JIRA out of scope" row), never as
  `bound`. The real merged PR is the fix-stage ground truth (`resolved_rate_strict` = right files + right APIs),
  so "did we produce the real fix" is measured at fix; the actual bind stays mock and the funnel says so.
- Tagged **`[proxy]`** (real OSS, not GEI production).

## 6. The simplify — proportionate cleanup (not a deletion project)

- **Retire genuinely-dead** metrics: `eval/metrics.py::ndcg_at_k` + standalone `mrr()`/`success_at_k` (never
  computed in any read; the scorecard computes MRR inline), and the orphaned `synth/functional.py::
  build_functional_negatives` (no caller).
- **Quarantine, not delete**, the honesty/selective/abstention/negatives stack (`abstention_recall_oof`,
  per-class abstain, phi_c-over-unanswerable) + the KB-as-eval arm — behind an honest "**not exercised by this
  corpus**" label. They encode intended future evaluation; this corpus (positives only) doesn't feed them, and
  faking that it does would be narrative.
- **`docs/evaluation.md`:** add a "what's actually exercised vs idle" reality section reflecting the audit.

## 7. Invariants / first-principle compliance

- **Grounding over narrative:** honest per-stage grading; submit/bind mock, not faked; small-real over large-fake;
  fix is *measured* (expected weak/scarce), not a target to hit.
- **Oracle-blindness:** the loop never sees the oracle — the committed manifest's oracle fields are read **only
  offline by the grader** (reuse the `_oracle` sidecar discipline / the `ORACLE_KEYS` split).
- **Leak-safety:** reuse the miner's scrub + closed-loop owner-leak reject; no owner slug reaches the matcher.
- **No `core/` or atlas-schema edit;** builder + harness live in labs (`mine`/`fixeval`/`grade`), reachable via
  the sanctioned lazy seam.
- **Secret hygiene:** the manifest holds only public issue/PR/SHA refs.

## 8. Scope / non-goals

- **Tier A excluded** (match+localize-only cases) — uniform Tier B only.
- **Honest-refusal negatives excluded** (different population).
- **NOT closing the loop** — no real fix-engine work, no live Gerrit/JIRA; this is end-to-end *measurement*, not
  *closure*. An honest end-to-end read is what would ground any *future* decision to invest in closure.
- **GEI/production stays production-only;** this makes the **`[proxy]`** substrate representative, it does not
  replace the `[production]` gate.

## 9. Module touch-map

| Change | Target |
|---|---|
| Crash-log filter + merged-fix requirement + full-oracle + manifest emit | `groundloop/mine/{gh_miner,harvest,signal,filters,emit}.py` |
| The committed manifest file + a small loader | new `corpus/` (or `mine/`) manifest + module |
| End-to-end funnel report over the corpus | `groundloop/grade/` or `groundloop/fixeval/report.py` (reuse `grade_fix_all`) |
| Retire dead metrics / orphaned negatives generator | `groundloop/eval/metrics.py`, `groundloop/synth/functional.py` |
| Quarantine labels + reality section | `docs/evaluation.md`, `docs/capabilities.md`, `docs/STATUS.md` |
| Zero-diff | `groundloop/core/**`, atlas schema |

## 10. Open questions for the plan

- The exact broadened repo set (crash-issue-rich AND atlas-indexable) — the plan picks it, and notes the atlas
  rebuild the corpus needs (off ext4, gated live).
- Where the committed manifest lives (a top-level `corpus/` dir vs under `mine/`) — plan decides.
- Extend `gloop mine` with flags vs a new `gloop build-e2e-corpus` — plan decides (prefer reuse).
- The live corpus build + the first end-to-end funnel read are **gated Type-2** (need `gh` + the gateway + an
  atlas), run by the user — NOT a hermetic merge gate. The hermetic deliverable is the builder/filter/manifest +
  the funnel report, unit-tested with fixtures.
