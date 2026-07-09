# Android Log Match v2 — Fault-Localization + Attribution (Design Spec)

**Date:** 2026-07-09 · **Status:** design, pending implementation plan · **Track:** Type-2 / Stage-1 matching

## 1. Problem & goal

GroundLoop's Stage-1 (ticket→repo matching) has a critical weakness: it cannot reliably **identify the
actual failure point in a long log**, nor **map that failure point to the owning repo**. Today's path
flattens `signals.tokens()` — a bag that includes unfiltered framework FQCNs (`android.*`, `com.android.*`,
`java.*`) — into a single global FTS pass scored by *distinct-token breadth* with no size normalization
(`adapters/index/atlas.py:17-28`). The result: large repos win on token volume, and the true fault site is
never isolated from the noise. The extractor itself is a line-agnostic regex sweep over one concatenated
blob (`domains/android_ivi/signal_extractor.py:24-42`) — it has no notion of *which line is the failure*.

**Goal.** Build a deterministic pipeline that (1) isolates the one true fault site from a long, noisy
full-system logcat, and (2) attributes that fault site to the owning repo — measured with the two stages
scored **separately** so we can tell extraction failures from attribution failures.

This is the **first problem**. It is built *toward the real ecarx/gkui vehicle estate* (unscrubbed package
namespaces are legitimate owner signal there), validated on a constructed proxy because no real-estate
assets (repos / tickets / logs / ground truth) are available.

## 2. Non-goals (explicit)

- **No-crash issues are OUT OF SCOPE.** UI-string / silent-state / behavior / wrong-condition bugs (e.g. the
  DHU1014-4240 USB UI-text class) are the deferred **second problem**. v2 localizes **crash/ANR faults from
  logs only**; the synth produces only cases with a crash/ANR anchor.
- **No ticket-text-primary matching, no JIRA-component routing, no source-code UI-string index.** Deferred to
  a later spec.
- **No deobfuscation.** R8/ProGuard-obfuscated frames are flagged and down-weighted, not resolved.
- **No `core/` changes, no atlas SQLite schema changes, no edits to the coordination-gated `rank_repos` /
  `owner_tokens.py` / `mine/`.** (See §10.)
- **No real JIRA/Gerrit integration** (a standing charter non-goal). The proxy uses mock data.

## 3. Regime & framing

The real estate differs from the current scrubbed benchmark in one decisive way: **package namespaces and
SONAMEs are legitimate, production-known owner signals** (nobody scrubs `com.ecarx.engineering`). So once the
fault site is correctly isolated, attribution is near-deterministic via a namespace/SONAME→repo routing
table — a very different regime from the current fuzzy breadth contest.

We mirror this regime on a proxy built from the **9 OSS fleet repos, unscrubbed**: their real namespaces
(`net.osmand`, `org.schabi.newpipe`, `com.google.oboe`, …) and library names stand in for `com.ecarx.*`.
This is a **separate dataset track** from the existing scrubbed Type-2 benchmark; the SP1 anti-leak
invariants remain scoped to the scrubbed benchmark (see §9).

## 4. Architecture overview

```
BUILD-TIME  synth (NEW, unscrubbed, clean|hard)
  9 OSS repos + atlas-9.db → logs/000.txt (full-system logcat, ~thousands of lines)
                           → _oracle: {owning_repo, fault_family, fault_frame, fault_file, fault_line,
                                        expected_files, decoys?}
RUN-TIME
  logcat parser  (NEW)  → [ LogLine{ts,pid,tid,level,tag,msg,raw}, ... ]
        ▼
  fault extractor (NEW) → anchor (FATAL EXCEPTION | Fatal signal N | ANR in)
        │                 → scope to crashing pid/tid → blamed frames (normalized, causal order)
        │                 → first non-framework frame = fault site → FaultRecord{…, confidence}
        ▼
  ┌ Phase 1 ─▶ fault_signals → tight Signals (fault-site tokens only) → AtlasIndex.rank_repos (UNCHANGED)
  └ Phase 2 ─▶ FaultRoutingIndex (NEW adapter): routing table (primary) ⊕ fault-scoped FTS ⊕ semantic?
                → RRF fusion → confidence gate (abstain: low_match_confidence | no_fault_found)
                → optional LLM rerank/explain over top-N
        ▼
  attribution_recall@1  +  fault_localization@k     (reported SEPARATELY, 3 arms: flood|faultslice|routing)
```

**Component map** (all additive; safety classified in §10):

| Module | Role | Phase |
|---|---|---|
| `groundloop/synth/faultlog.py` | unscrubbed long-log synth (clean\|hard) + fault-locus oracle | 0 / 3 |
| `groundloop/synth/data/framework_noise.py` | curated framework-noise + decoy template library | 0 / 3 |
| `groundloop/domains/android_ivi/logcat_parse.py` | line-structured logcat parser (2 formats) | 1 |
| `groundloop/domains/android_ivi/frame_norm.py` | pure `normalize_frame()` used everywhere | 1 |
| `groundloop/domains/android_ivi/fault_extract.py` | anchors + scope → `FaultRecord` (+ confidence) | 1 |
| `groundloop/domains/android_ivi/fault_signals.py` | `FaultRecord` → tight `Signals` (Phase-1 bridge) | 1 |
| `groundloop/domains/android_ivi/repo_routing.py` | production-known prefix/SONAME→repo table | 2 |
| `groundloop/adapters/index/fault_routing.py` | `FaultRoutingIndex` (routing ⊕ FTS ⊕ RRF ⊕ gate ⊕ LLM) | 2 |
| `groundloop/fixeval` / `eval` metric additions | `fault_localization@k`, 3-arm scorecard | 0 |
| `FaultRecord`, `LogLine`, `NormFrame` dataclasses | **adapter-owned** (not `core/`) | 1 |

## 5. Data plane — synth substrate & oracle

Drives from existing mined positives (which carry `owning_repo` + `expected_files` + real atlas frames) and
wraps each into a long, noisy, **unscrubbed** full-system logcat.

### 5.1 Fault block (reuse)
Reuse `synth/logs.py` (`crash_frames`, the 12 `CRASH_CLASSES`, `_atlas_method`) to emit a real crash from the
owner's atlas units, for the selected family:
- **java** — `E AndroidRuntime: FATAL EXCEPTION: <thread>` + `Process: <pkg>, PID: <pid>` +
  `<Exception>: <msg>` + `\tat pkg.Class.method(File:line)` frames.
- **native** — `F libc: Fatal signal N (SIG…)` / tombstone + `backtrace: #00 pc <hex> /…/libX.so (sym+off)`.
- **anr** — `E ActivityManager: ANR in <owner-proc>` + `Reason: …` + a `"main"` thread stack.

The owner's real tokens remain **in** the fault block (the point of the unscrubbed track).

### 5.2 Noise generator (new)
`synth/data/framework_noise.py` — a curated library of framework log templates
(`PackageManager`/`ActivityManager`/`WindowManager`/`SurfaceFlinger`/`binder`/`system_server`/`zygote`) with
`<*>` slots filled deterministically. Emits `--noise-lines` (default ~3000) across ~20–40 synthetic pids at
mixed levels (mostly I/D/W; occasional non-fault E). In **clean** mode the noise vocabulary **excludes every
fleet owner's tokens** — the only owner signal anywhere is the fault block.

### 5.3 Difficulty modes
- **clean** — owner tokens only in the fault block; framework-only noise. The easy substrate for Phases 0–2.
- **hard** — seeded, controlled decoys injected into the noise, each drawn from **other fleet repos' known
  metadata** (never the owner's oracle) and pointing at **non-owner** repos:
  1. unrelated owner/package tokens in non-fatal lines (e.g. a `net.osmand` INFO line in an oboe case);
  2. red-herring non-fatal `E` lines (caught/logged exceptions that are not the fault);
  3. binder noise (`binder`/transaction chatter) that is not the fault;
  4. confusable near-miss namespaces (sibling/adjacent prefixes to stress routing precision);
  5. non-owner `.so` decoys (`dlopen libX.so` load lines) so `.so`→repo keys on the *crashing backtrace*,
     not any `.so` mention.
  Injected decoys are recorded in `_oracle.decoys` for diagnostics only; a correct pipeline ignores them.

### 5.4 Line format, placement, determinism
Every line rendered `MM-DD HH:MM:SS.mmm PID TID LEVEL TAG: MSG` with a seeded base clock advancing by small
deltas and per-process PID/TID assignment. The contiguous fault block is inserted at a seeded position (not
always the tail), noise before and after. **Fully deterministic** — seeded from `stable_hash(case_id)` (the
existing `select_crash_class` pattern); **no wall-clock, no `random`**.

### 5.5 Oracle (dataset-side JSON — NOT the frozen atlas schema)
```json
{ "owning_repo": "oboe", "fault_family": "native",
  "fault_frame": "AudioStreamAAudio::requestStart",
  "fault_file": "src/aaudio/AAudioStream.cpp", "fault_line": 212,
  "expected_files": ["src/aaudio/AAudioStream.cpp"],
  "decoys": ["net.osmand", "liborganicmaps.so"] }
```
`fault_frame`/`fault_file`/`fault_line` are drawn from the atlas unit that produced the top frame.
`expected_files` retains compatibility with existing recall metrics.

### 5.6 CLI
`gloop synth --mode faultlog --src <mined> --atlas-db <db> --out <ds> --difficulty {clean,hard}
--noise-lines N --families java,native,anr`. The dataset carries `dataset_kind: faultlog_unscrubbed` in its
catalog so the SP1 leak invariants skip it (§9).

## 6. Compute plane — parser, extractor, faultslice

### 6.1 Parser — `logcat_parse.py`
Regex for the two standard formats → `LogLine{ts,pid,tid,level,tag,msg,raw}`. Continuation lines (`\tat …`,
`#00 pc …`, `Caused by:`) attach to the preceding line's pid/tid. Unmatched lines preserved as raw. Returns
the ordered list. Pure/deterministic; no atlas or network access.

### 6.2 Frame normalization — `frame_norm.py`
A pure `normalize_frame(raw) -> NormFrame` used **identically** by the extractor, routing, and the
`fault_localization` metric (so all comparisons are apples-to-apples):
- **Java:** strip synthetic/lambda suffixes (`$$Lambda$N`, `$1`, `access$NNN`, `$suspendImpl`); decode JNI
  `Java_pkg_Class_method` → `pkg.Class.method`; keep full `pkg.Class.method` for frame comparison, expose the
  package (via the outer class for `Outer$Inner`) for routing; drop arg descriptors.
- **Native:** `soname` = basename with path + version stripped (`/system/lib64/libfoo.so.1.2` → `libfoo.so`);
  `symbol` = demangled best-effort with the `+0xNN` offset stripped, else raw.
- **Obfuscation:** frames matching an obfuscated shape (`a.b.c`, single-letter segments) are flagged
  `obfuscated=True` → the extractor lowers confidence; not deobfuscated.
`NormFrame{package, klass, method, soname, symbol, obfuscated, raw}`.

### 6.3 Fault extractor — `fault_extract.py`
Over the parsed lines:
- **Anchors (per family):** java = `AndroidRuntime E … FATAL EXCEPTION` + `Process:/PID:`; native =
  `F libc … Fatal signal N (SIG…)` / tombstone `*** ***` + `backtrace:`; anr = `ActivityManager E … ANR in
  <proc>` + `Reason:` + `"main"` thread.
- **Scope:** collect the contiguous stack block for the anchor's pid/tid, filtering interleaved other-pid
  lines.
- **Top owner-relevant frame:** walk normalized frames top-down, **skip framework frames** (prefix skiplist
  `android.`/`androidx.`/`java.`/`javax.`/`kotlin.`/`com.android.`/`com.google.android.`/`dalvik.`/`libc`/
  `libart`/system `.so`) → first non-framework frame = the fault site. *This is the guide's "generic-token
  filter", applied as frame **selection**, not token dropping.*
- **Multi-fault:** if multiple anchors, pick the first fatal / the one bearing an owner-relevant frame;
  record all candidates (Phase-2 Drain3 sharpens this).
- **Output `FaultRecord`** (adapter-owned; NOT `core/`):
  `{family, exception, frames:[NormFrame], top_frame:NormFrame, fault_file_hint, pid, tag, confidence}`.
  No anchor → `FaultRecord = None`.

### 6.4 FaultRecord confidence (explicit)
| Level | Criteria |
|---|---|
| **HIGH** | single fatal anchor; unambiguous pid/tid scope; a non-obfuscated owner-relevant top frame found |
| **MEDIUM** | anchor found but top frame ambiguous (multiple owner-candidate frames) OR multiple anchors with a clear first-fatal OR top frame obfuscated-but-non-framework |
| **LOW** | anchor found but **all** frames are framework (no owner-relevant frame) OR conflicting/interleaved scope OR ANR with a shallow main-thread stack |
| **NONE** | no fault anchor → `FaultRecord = None` → `no_fault_found` abstain |
Confidence feeds the Phase-2 gate (LOW/NONE bias toward abstain) and the RRF weighting.

### 6.5 Phase-1 faultslice — `fault_signals.py`
`from_fault_record(fr) -> Signals` populates the six **frozen** `Signals` fields with **only** fault-site
tokens (top_frame + blamed owner frames: class/package/method, `.so`/symbol, exception), then calls
`AtlasIndex.rank_repos` **unchanged**. The tiny fault-specific token set eliminates the size-bias flood — this
is the extraction lever, delivered with **zero gated changes**.

## 7. Phase-2 precision layer

### 7.1 Routing table — `repo_routing.py` (production-known ONLY)
Curated `PREFIX→repo` + `SONAME→repo` table over the fleet's real namespaces/libraries
(`net.osmand→osmand`, `org.schabi.newpipe→newpipe`, `liboboe`/`libaaudio→oboe`, …). `route(fault_record) ->
[(repo, weight)]`, applied to the **fault site** (not the whole log).

**Anti-leak invariants (hard):**
- The table encodes **production-known ownership metadata only** — namespace/SONAME ownership derivable from
  each repo's manifest/build files (the analogue of a triage engineer's estate knowledge). It is **global and
  case-independent**.
- It **must never** read any per-case `oracle.json` field (`owning_repo`, `fault_frame`, `fault_file`,
  `expected_files`) nor any dataset case directory.
- **Enforcement:** (a) the builder reads only repo metadata paths, asserted by a red-test that it opens no
  dataset/oracle path; (b) an invariant test that `route()` output for a case is independent of that case's
  oracle; (c) each entry carries a provenance note (source manifest/library).
- **Validity scope:** the routing table is meaningful only on the **unscrubbed** track; on the scrubbed
  benchmark namespace ownership is deliberately neutralized, so the table is not applied there.

### 7.2 `FaultRoutingIndex` — `adapters/index/fault_routing.py`
Wraps `AtlasIndex` and is swapped in at the composition root (`rank_repos` untouched):
- **candidates** = `union(routing candidates, base FTS top-k)` — routing can *inject* an owner the base FTS
  dropped below its cutoff (resolves the "wrapper can't recover a dropped owner" caveat);
- **score** = **RRF** over {routing rank, fault-scoped FTS rank, optional semantic rank}, weighted by
  FaultRecord confidence;
- **confidence gate** = reuse `eval/abstain.decide` over the fused margin; abstain reasons
  `low_match_confidence` / `no_fault_found`;
- **optional LLM rerank/explain** over top-N + FaultRecord evidence (reuse `GatewayJudge`; never sees raw
  logs — only the distilled FaultRecord + candidates).
- **Drain3** noise-compression feeds the extractor's multi-fault disambiguation here.

## 8. Metrics & evaluation

- **`fault_localization`** (NEW, the extraction read): using `normalize_frame`,
  - `fault_localization_frame@1` = fraction where the extractor's `top_frame` == oracle `fault_frame`;
  - `fault_localization_frame@k` = oracle `fault_frame` present among the top-k blamed frames;
  - `fault_localization_file@1` = `top_frame`'s file == oracle `fault_file` (coarser, robust to frame ties).
- **`attribution_recall@1/@3`** (the mapping read): existing recall over the (fault-scoped) candidate ranking.
- **abstention / Φ_c:** reuse the selective-prediction apparatus; `no_fault_found` + `low_match_confidence`
  are graded as honest abstains.
- **Three arms** over the faultlog dataset, via `gloop compare`:
  - `flood` — today's full `signals.tokens()` (the baseline we must beat);
  - `faultslice` — Phase 1 (fault-scoped tokens + base matcher);
  - `routing` — Phase 2 (`FaultRoutingIndex`).
  Reporting the two metrics separately per arm shows *which stage* each arm fixes.

## 9. Anti-leak & oracle-blindness

- **Dual-track separation.** The unscrubbed faultlog dataset (`dataset_kind: faultlog_unscrubbed`) is a
  separate track from the scrubbed Type-2 benchmark. The SP1 leak invariants (`tests/mine/`, `tests/test_
  invariants.py`) remain scoped to the scrubbed benchmark and skip the faultlog track (gated on
  `dataset_kind`).
- **Synth decoys never come from the owner oracle** — only from other fleet repos' known metadata (§5.3).
- **Routing table is production-known only** (§7.1), never per-case oracle.
- **The loop/eval stays oracle-blind;** grading (`fault_localization`, recall, Φ_c) is an offline pass that
  reads the oracle; the extractor/matcher/gate never do.

## 10. Frozen-surface safety

- **`core/` untouched.** `FaultRecord`/`LogLine`/`NormFrame` are adapter-owned dataclasses; `Signals` is
  *populated* (not modified); `run_ticket`, the ports, and `RepoScore`/`Ticket` are unchanged. The abstain
  gate lives in the eval/fixeval harness (as it already does), never in frozen `run_ticket`.
- **Atlas SQLite schema untouched.** The synth *reads* the atlas for real frames; the oracle is dataset-side
  JSON. No new columns/tables/kinds.
- **Coordination-gated surfaces untouched.** `rank_repos` is unchanged (Phase 1 changes its *input*; Phase 2
  *wraps* it). `owner_tokens.py` is unchanged (routing is a **new** module with the opposite contract).
  `mine/` is unchanged (synth drives from existing mined positives).
- Behavior swaps happen at the composition root (`cli/__init__.py`), consistent with the existing
  `AtlasIndex`/`SemanticAtlasIndex`/`LLMJudgeIndex` pattern.

## 11. Testing

**Type-1 (hermetic):**
- `logcat_parse` — both formats, continuation lines, malformed lines, interleaved pids.
- `frame_norm` — Java lambda/inner/JNI cases, native path/version/offset strips, obfuscation flagging.
- `fault_extract` — one test per family (anchor+scope+top-frame); multi-fault picks first fatal; all-framework
  → LOW; no-anchor → None; confidence-level assignment.
- `fault_signals` — `FaultRecord` → tight `Signals` (only fault-site tokens).
- `faultlog` synth — fault block present; noise volume; oracle correctness; **clean** = owner token only in
  fault block; **hard** = decoys present, drawn from non-owner metadata, `decoys` recorded; determinism (same
  `case_id` → identical log).
- `repo_routing` — `route()` correctness; **anti-leak red-tests** (builder opens no oracle path; case-
  independence).
- `FaultRoutingIndex` — candidate-union injects a dropped owner; RRF ordering; gate abstain reasons.
- `fault_localization` metric — frame@1/@k/file@1 over `normalize_frame`.

**Type-2 (live, gated):** build a faultlog dataset over `atlas-9.db` (clean, then hard), run the 3-arm A/B,
report `fault_localization` + `attribution_recall` lifts (`flood` → `faultslice` → `routing`).

## 12. Build order (phases)

- **Phase 0 — substrate & measurement.** `faultlog.py` (clean) + noise library + oracle + `fault_localization`
  metric + the 3-arm scaffold. *Exit:* a faultlog dataset builds and the `flood` baseline is measured.
- **Phase 1 — faultslice.** `logcat_parse` + `frame_norm` + `fault_extract` (+ confidence) + `fault_signals`.
  *Exit:* `faultslice` vs `flood` measured on clean — "does tight extraction fix attribution?", with no gated
  changes.
- **Phase 2 — routing.** `repo_routing` (production-known, anti-leak) + `FaultRoutingIndex` (RRF + gate +
  optional LLM) + Drain3. *Exit:* `routing` vs `faultslice` lift measured on clean.
- **Phase 3 — hard-mode validation.** `faultlog.py` hard-mode decoys + re-run the 3-arm A/B on hard. *Exit:*
  robustness gate — the pipeline holds up against owner/namespace/SONAME/binder decoys.

## 13. Open questions / risks

- **Frame→file resolution.** `fault_localization_file@1` needs the extractor to resolve a frame to a repo file
  independent of the oracle; for native frames without a path this leans on `.so`→repo + symbol. Where a frame
  can't be resolved to a file, we score `frame@k` only and note it.
- **Routing coverage on the OSS proxy.** Some fleet repos share generic namespaces; the table encodes only
  distinctive prefixes/SONAMEs, and `FaultRoutingIndex` falls back to fault-scoped FTS when routing abstains.
- **Hard-mode calibration.** Decoy density is a synth knob; too high makes cases unwinnable, too low makes
  hard-mode == clean. We tune density so the `flood` baseline degrades measurably while a correct extractor
  holds — reported, not hidden.
- **Determinism vs realism.** Seeded synth trades some realism for reproducibility; acceptable for a benchmark
  substrate (real logs would replace it when available).
