# Android Log Match v2 — Live A/B Findings (2026-07-09)

The v2 fault-localization + attribution pipeline (spec `docs/superpowers/specs/2026-07-09-android-log-match-v2-design.md`,
plan `docs/superpowers/plans/2026-07-09-android-log-match-v2.md`) is **built, reviewed (READY TO MERGE), and
validated live**. This is the Phase-3.2 result: the 3-arm A/B (`flood` → `faultslice` → `routing`) on a real
196-case faultlog dataset over the 9-repo `atlas-9.db`, plus a log-quality audit of the generated substrate.

The run is **fully deterministic — no gateway, no LLM, no cost** (parse → extract → FTS/routing).

## Setup

- **Substrate:** `gloop synth --mode faultlog` over the mined positives (`dataset-neg-synth-sub`) → **196
  unscrubbed long-logcat cases** (132 java / 47 native / 17 anr), each a ~3006-line full-system logcat with a
  real owner crash buried in framework noise, `--noise-lines 3000`. Built in `clean` and `hard` (decoy)
  difficulties. Dataset tagged `dataset_kind: faultlog_unscrubbed` (separate track from the scrubbed
  benchmark).
- **Fleet:** all 9 OSS repos (`atlas-9.db`, 12.5 GB, 475k units) — a real confusable catalog.
- **Arms:** `flood` = today's full-token `AndroidSignalExtractor`; `faultslice` = the new fault-scoped
  extractor; `routing` = `faultslice` + `FaultRoutingIndex` (production-known prefix/SONAME routing + RRF).
- Reproducer: `faultlog_ab_run.sh`; log `/home/vinc/gl-eval/faultlog-ab.log`.

## The headline — attribution nearly doubles, and becomes decoy-robust

`attribution_recall@1` (top-1 predicted repo == owning repo), the metric the whole pipeline targets:

| arm | CLEAN recall@1 | recall@3 | coverage | HARD recall@1 | recall@3 | coverage |
|---|---|---|---|---|---|---|
| **flood** (baseline) | 0.48 | 0.78 | 0.72 | **0.32** | 0.61 | 0.78 |
| **faultslice** | 0.86 | 0.92 | 0.86 | **0.86** | 0.92 | 0.86 |
| **routing** | **0.94** | 0.94 | 0.93 | **0.94** | 0.94 | 0.93 |

Two findings, both decisive:

1. **Tight fault extraction nearly doubles attribution** — `flood 0.48 → faultslice 0.86` on clean. This is
   the "critical weakness" directly fixed: the old matcher floods FTS with hundreds of generic framework
   tokens and lets big repos win; feeding *only* the isolated fault-site tokens recovers the owner. Routing
   then lifts it to **0.94**.
2. **Fault-scoping is immune to adversarial noise; the baseline is not.** Under `hard` decoys (non-owner
   namespaces/SONAMEs, binder chatter, confusable near-misses injected into the noise) the `flood` baseline
   **drops 0.48 → 0.32** — the decoys are exactly the framework/other-repo tokens it can't distinguish from
   signal. `faultslice` and `routing` are **unchanged** (0.86 / 0.94), because the injected noise never
   enters a fault-scoped signal. The design isn't just better on clean logs — it removes the failure mode.

## Fault localization — strong and decoy-immune

| metric | CLEAN | HARD |
|---|---|---|
| `frame@1` (top frame == oracle fault frame) | **0.88** | 0.88 |
| `frame@5` (true frame among blamed frames) | 0.95 | 0.95 |
| `file@1` (fault file basename match) | 0.68 | 0.68 |
| `no_fault` (no anchor found) | 9 / 196 | 9 / 196 |

The extractor nails the exact fault frame **88%** of the time and finds it in the top-5 blamed frames **95%**.
Identical clean-vs-hard confirms extraction anchors on the crash, not the noise. `file@1` (0.68) is lower than
`frame@1` because native backtraces carry no filename, so native cases can't score `file@1` by construction
(spec §13) — it is a Java-frame metric.

## Log-quality audit (the generated substrate is honest + discriminating)

Passing plumbing tests proves the pipeline runs; these checks prove the *logs are good test material*.
Measured over the 196 clean logs (`log_quality.py`):

| dimension | check | result |
|---|---|---|
| **Realism** | read a sample: format, multi-process, framework-then-owner frames | ✅ (see sample below) |
| **Needle placement** | anchor position fraction (0=top, 1=bottom) | min 0.25 / **p50 0.44** / max 0.75 — buried mid-log, never always at the end |
| **Log length** | lines per case | p50 **3006** (a genuine long log) |
| **Ground-truth integrity** | oracle `fault_frame` present in log text | **196 / 196** |
| **Honesty (no answer-leak)** | owner namespace/SONAME appears in *noise* (clean mode)? | **0 / 187** — attribution is earned, not given away |
| **Diversity** | family / owner spread | 132 java / 47 native / 17 anr; all 9 repos present but **skewed** (newpipe 48 … media3 5, gpuimage 2) |
| **Discrimination** | does the A/B separate arms? | flood 0.48 → faultslice 0.86 → routing 0.94 (wide, monotonic — not saturated/floored) |

The **0/187 owner-leak** result is what makes the numbers trustworthy: the clean-mode framework noise never
names the owner, so `faultslice`/`routing` genuinely earn attribution from the fault frame.

Sample (organicmaps java case — noise, then the buried crash, then the owner fault site):
```
07-05 10:34:00.000  6980  6980 I system_server: Waiting on 3620 for com.android.settingsms
07-05 10:34:00.014  3204  3204 W WindowManager: Slow Looper main: doFrame took 7505ms
   … ~760 more noise lines …
07-05 10:34:07.221  4821  4821 E AndroidRuntime: FATAL EXCEPTION: main
… java.util.ConcurrentModificationException: collection modified during iteration
…   at java.util.ArrayList$Itr.checkForComodification(ArrayList.java:1042)     ← framework (skipped)
…   at app.organicmaps.car.CarAppSession.onEvent(CarAppSession.java:776)       ← OWNER fault site ✓
```
Oracle: `fault_frame=app.organicmaps.car.CarAppSession.onEvent`, `fault_file=…/CarAppSession.java`,
`fault_line=776` — the extractor skips the `java.util` frames and picks the owner frame, matching exactly.

## Caveats & follow-ups

- **`no_fault=9` has a known root cause:** all 9 are the oboe **audio-underrun** synth class
  (`build_audio_underrun`), which emits an AAudio *performance warning* (`buffer underrun` / `onAudioReady`),
  **not** a `FATAL EXCEPTION` / `signal N` / `ANR in` anchor. The extractor correctly finds nothing to
  anchor — a non-fatal underrun is really a *silent behavior* bug (the deferred **second problem**), not a
  crash to localize. It is scored as a `frame@1` miss, so it modestly depresses localization. **Easy
  follow-up:** drop the audio-underrun class from the faultlog synth (crash-only benchmark), or add an
  `underrun`/`onAudioReady` anchor if we want to fold non-fatal signals in.
- **Dataset owner-skew** (media3 5, gpuimage 2) mirrors the mined-issue distribution; thin repos give noisy
  per-repo recall. A note, not a synth bug.
- **Internal vs external validity:** these checks establish *internal* validity (self-consistent, honest,
  discriminating, realistic-shaped). *External* validity — do these match real ecarx/AAOS logs — needs real
  logs and is exactly what the pipeline is built to eventually ingest. The synth is a faithful stand-in, not
  a substitute.
- **Sanctioned design deferrals** (from the final holistic review, all non-blocking): RRF is not yet
  confidence-weighted (the `Arm.extractor` interface yields only `Signals`, not the `FaultRecord`);
  `FaultRecord.confidence` is coarser than spec §6.4 (only `obfuscated→MEDIUM`, and unconsumed downstream);
  `fault_line` is written to the oracle but not yet graded. All are threadable later without rework.

## Engineering result

- **18 commits**, full suite **494 passed / 7 skipped**, ruff clean.
- **Frozen/gated surfaces untouched:** no `groundloop/core/`, no `engines/atlas/store.py` schema, no
  `adapters/index/atlas.py` `rank_repos`, no `owner_tokens.py`, no `mine/` — the whole feature rides new
  domain/synth/index/faulteval modules swapped at the composition root.
- Final holistic review verdict: **READY TO MERGE** (end-to-end integration, cross-module round-trip
  consistency, anti-leak, and frozen-surface contracts all verified).

## Bottom line

On a real 9-repo confusable atlas, isolating the fault site before matching **doubles** attribution recall@1
(0.48 → 0.86) and makes it **immune to adversarial noise that halves the baseline** (flood 0.48 → 0.32 under
decoys; faultslice/routing unchanged); the production-known routing table lifts it to **0.94**; and fault
localization hits the exact frame **88%** of the time. The v2 design — *stop ranking repos from raw
full-system logcat tokens; rank from the isolated, weighted fault site* — is validated end-to-end.
