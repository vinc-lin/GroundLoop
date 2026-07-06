# GroundLoop — First End-to-End Evaluation (2026-07-06)

**Scope.** A first, grounded evaluation of the project as it stands: the whole loop exercised end-to-end on
real data (`run_ticket`: intake → extract → match → materialize → localize → fix → submit → bind), plus a
cross-stage scorecard with the real numbers and an honest maturity map. Runnable measurements were run;
anything needing the live gateway + full fleet repos is marked **GATED** (not measured), never guessed.

**Substrate.** 9-repo AAOS fleet · `atlas-9.db` (475,415 symbol units, 12.5 GB, ext4) · two eval datasets:
`dataset-synth` (212 synthesized signal-rich-log cases) and `dataset-full` (261 real mined-log cases).
Test surface: **293 passed / 7 skipped, ruff clean.**

---

## Verdict (executive summary)

- **Stage-1 match is the real, measured capability and the current bottleneck.** On synth logs it reaches
  **recall@1 = 0.60** (Φ₁ = +0.31); on *real* mined logs the membership matcher collapses to **0.02** and
  only the bge-m3 **semantic** arm recovers to **0.23**.
- **Localization is quietly strong — and unscored by the standard harness.** Given the right repo it hits
  **file_recall 0.85@1 / 0.94@5**; end-to-end it is dragged to **0.53@1 / 0.60@5** almost entirely by match
  error. The retrieval stage is not the problem; the matcher is.
- **The loop runs end-to-end** on real tickets (all 8 events fire, a patch is produced, a change is bound).
  But **fix quality is unmeasured** (gated live env; `resolved_rate` is a proxy, no test execution) and
  **submit/bind are mocks**.
- **The dev-experience KB is built and grounded** (fires on 55% of real cases, placebo control valid) but
  its **lift is unmeasured** (gated).
- **Honest refusal is built but untested on real data** — the eval datasets carry **zero** negatives.
- **Cost is ~$0/ticket** for match+localize (pure FTS5, no LLM); the live fix stage is ~$0.003/case (gated).

The one-line story: **a strong, cheap, LLM-free localizer sitting behind a matcher that works on
signal-rich logs but not yet on real prose logs — and a downstream fix/KB layer that is wired but not yet
measured.**

---

## 1. End-to-end pipeline smoke (`run_ticket`, real cases, oracle-blind)

All 8 control-plane events fire on every case; `bound=True`. The loop never sees the oracle (comparison
below is offline).

| case | events | match (chosen) | localize | fix → submit → bind |
|---|---|---|---|---|
| `oboe-2103` | all 8 | **oboe ✓** (4.0 vs gpuimage 2.0) | expected file retrieved ✓ | patch · change `I9bd268e9` · bound ✓ |
| `newpipe-12489` | all 8 | **newpipe ✓** (11.0 vs media3 9.0) | expected file retrieved ✓ | patch · change `Ic04ea10c` · bound ✓ |
| `cameraview-26` | all 8 | **media3 ✗** (oracle=cameraview, rank 3 @7.0) | wrong repo → miss | patch on wrong file · bound ✓ |

`cameraview-26` is the honest failure mode: a small-repo case loses rank-1 to a giant (media3), and the
match error **cascades** — localize runs on the wrong repo, the fix touches the wrong file. Match is
upstream of everything.

---

## 2. Stage-1 match — the core objective (measured)

**`dataset-synth` (212, synthesized signal-rich logs):**

| arm | recall@1 | recall@3 | mrr | coverage | sel-acc | Φ₁ |
|---|---|---|---|---|---|---|
| membership + text | 0.02 | 0.30 | 0.28 | 0.03 | 0.29 | −0.01 |
| membership + **logs** | **0.60** | 0.80 | 0.73 | 0.79 | 0.69 | **+0.31** |

**`dataset-full` (261, real mined logs):**

| arm | recall@1 | mrr | coverage | Φ₁ |
|---|---|---|---|---|
| membership + text | 0.02 | 0.23 | 0.03 | −0.01 |
| membership + logs | 0.02 | 0.24 | 0.08 | −0.06 |
| semantic + text | **0.23** | 0.37 | 0.01 | 0.00 |
| semantic + logs | 0.22 | 0.37 | 0.01 | 0.00 |

**Per-repo (synth, membership+logs) — the size-bias:**

| repo | recall@1 | | repo | recall@1 |
|---|---|---|---|---|
| dlt-daemon | 26/26 | | organicmaps | 11/13 |
| osmand | 9/9 | | oboe | 42/45 |
| media3 | 6/6 | | antennapod | 24/53 |
| android-gpuimage-plus | 2/2 | | **newpipe** | **6/47** |
| | | | **cameraview** | **1/11** |

Native / unique-`.so` repos win outright; small Java repos land top-3 but lose rank-1 to larger repos whose
generic tokens (camelCase sub-words, common Android classes) accrue competing evidence.

---

## 3. Localize — strong, and not scored by the harness (measured here)

`file_recall@k` of the retrieve stage over 106 sampled synth cases:

| | file_recall@1 | file_recall@5 |
|---|---|---|
| **localize-only** (given the oracle repo) | **0.85** | **0.94** |
| **end-to-end** (given the *predicted* repo) | 0.53 | 0.60 |

Reading: retrieval finds the fix files 85–94% of the time **when pointed at the right repo**; the ~30-point
end-to-end drop is match error, not localize error (`0.60 match × 0.85 localize ≈ 0.51`). The standard
Type-2 harness computes only Stage-1 today — this localize number is a first measurement and argues for
surfacing it as a scored metric.

---

## 4. Fix / Submit / Bind — wired, not yet measured

- **Fix engine is real** (`ModelPatchEngine`, one `deepseek-chat` propose over candidate files). The loop
  produces a patch and completes end-to-end (§1). The **live fix-quality A/B is GATED** (needs the gateway
  + all 9 fleet repos as git checkouts — only 2 are present here). `resolved_rate` is a **proxy**
  (localization ∧ required-API ∧ `git apply --check`), not test execution — AAOS repos lack runnable suites.
- **KB arm (dev-experience Skills):** the corpus (12 leak-safe crash-RCA playbooks) fires on **117/212
  (55%)** of real synth cases via the production `select()`; the **placebo control mirrors it exactly
  (117/117)** — a valid A/B null arm. Hermetic direction-of-effect passes (injecting the KB moves a fixture
  from abstain → applying patch, `resolved` 0→1). **The real KB lift is GATED** (same live env).
- **Submit + Bind are MOCKS** (`MockGerrit` synthesizes a Change-Id; `MockJira` writes a local ledger and
  flips status). No real Gerrit/git/JIRA.

---

## 5. Honest refusal — built, untested on real data

The abstain gates, selective-prediction Φ_c, `abstention_recall_oof`, and `fabrication_rate` are
implemented and fixture-tested. But **`dataset-synth` and `dataset-full` contain 0 `is_answerable:false`
cases** — so the anti-hallucination metrics are **not exercised on the real eval set**. The negatives live
only in hermetic fixtures. This is the biggest measurement gap for the project's stated "grounding over
narrative" thesis.

---

## 6. Maturity map + cost

| Stage | Status | Real number | Cost/ticket |
|---|---|---|---|
| **Match** (Stage-1) | ✅ real + measured (headline) | 0.60@1 synth · 0.02/0.23 real (mem/sem) | $0 (FTS5) |
| **Localize** | ✅ real + strong, **unscored** by harness | 0.85@1 (oracle repo) · 0.53@1 e2e | $0 (FTS5) |
| **Fix** | ⚠️ real engine, wired; quality **GATED** | proxy-only, no live A/B yet | ~$0.003 (gated) |
| **Submit/Bind** | ❌ mock | loop completes (bound ✓) | $0 |
| **KB arm** | ⚠️ built + grounded; lift **GATED** | 55% fire, placebo-valid | ~$0.003 (gated) |
| **Honest refusal** | ⚠️ built + fixture-tested; **not on real data** | n/a (0 negatives in eval set) | — |

---

## 7. Honest caveats

1. **The 0.60 headline is on *synthesized* logs.** Real mined logs are ~0.02 (membership) / 0.23
   (semantic). The synth logs are grounded fabrications (real crash-site symbols on real fix files), so
   0.60 measures the matcher's ceiling *given signal-rich logs*, not real-world log quality.
2. **Match is the bottleneck**, and the size-bias (small repos lose rank-1 to giants) is its dominant error.
3. **Fix quality is unmeasured**; `resolved` is a proxy, not a passing test.
4. **No honest-refusal negatives in the eval datasets** — the abstention/fabrication story is untested on
   real data.
5. **Bind is a mock** — the JIRA↔commit chain is a local ledger, not a real tracker.

## 8. Next steps (evaluation-driven, ranked)

1. **Attack the match bottleneck** — the eval-driven size-normalization fix (coordinate on `rank_repos`),
   and route real prose logs through the **semantic** arm (0.23 vs 0.02).
2. **Score localize in the harness** — it is already strong (0.85@1); surfacing it makes the cascade
   visible and gradeable.
3. **Run the gated live fix-loop A/B** (gateway + fleet repos) — the first fix-quality + KB-lift numbers,
   via `gloop fixeval --skills {none,kb,placebo}` → `strengthened_accept`.
4. **Mine honest-refusal negatives into the eval datasets** (SP1b typed miner) so Φ_c / `fabrication_rate`
   are exercised on real data — the missing anti-hallucination measurement.
5. **Broaden the synth generator** to the 3 zero-firing crash classes (binder / savedInstanceState / ANR)
   so the full KB corpus is exercisable.

---

*Method: numbers from `gloop eval` scorecards (`scorecard-synth`, `scorecard-full`), a `run_ticket` smoke
over `dataset-synth`, and an offline localize `file_recall` pass; all on `atlas-9.db` off ext4. Gated items
require `KLOOP_PRODUCE_API_KEY` + the 9 fleet repos and were not run.*
