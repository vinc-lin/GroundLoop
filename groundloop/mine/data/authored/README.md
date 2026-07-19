# Authored cases — `[authored]`

This directory holds **21 hand-authored, full-Tier-B crash cases** (grown from the original 3), each grounded in
real source from the fleet corpus (`/mnt/x/code/corpora/<repo>/`, pinned by `owning_repo_sha` in each case's
`_oracle/oracle.json`). Coverage spans all **9 atlas-indexed fleet repos** × diverse crash shapes:

| repo | cases | shapes |
|---|---|---|
| oboe (C++ native audio) | 3 | native `.so` backtrace |
| newpipe (Java/Android) | 3 | Java stacktrace (NPE / IndexOOB) |
| dlt-daemon (C, automotive) | 3 | native SIGSEGV / SIGABRT-assert |
| media3 (Java media/ExoPlayer) | 3 | Java stacktrace (ISE / NPE / OOB) |
| android-gpuimage-plus (JNI/C++) | 2 | JNI-boundary / native |
| antennapod (Java/Kotlin) | 2 | Java stacktrace |
| organicmaps (C++/JNI, large) | 2 | native / JNI-boundary |
| osmand (Java maps, large) | 2 | Java stacktrace |
| cameraview (Java) | 1 | Java stacktrace |

(3 cases — a cameraview JNI, an organicmaps native, an osmand ANR — are a deferred top-up.) `catalog.json` lists the
full 9-repo fleet, so a matcher run against this dataset ranks each ticket against realistic confusable candidates,
not a rigged 1-of-N choice.

Every case is gated by `groundloop.mine.authored.validate_authored_case(case_dir, corpora_root)`, which returns `[]`
only when: each `expected_files` entry is a real file in the real repo tree; each `required_apis` symbol appears in
that file's real text; the crash log names an oracle symbol (grounded, not disconnected prose); the ticket
(summary/description/logs **and** `ticket["id"]`) never leaks the `owning_repo` name; and `fix.diff` touches an
`expected_files` path, references a `required_apis` symbol on a **non-comment** added line, **and `git apply --check`s
byte-clean** against the pinned SHA. The mechanical gate is strict enough to trust at this scale (each case was also
independently adversarially verified against real source at authoring time).

## What this is — and is not

**Role: a mechanics/capability test, not an effectiveness measurement.** These cases answer one question — *can the
loop carry a realistic crash end-to-end over real code* (ticket → match → localize → fix → grade), with every oracle
field anchored to source that actually exists on disk — not whether the loop is *good* at it. Even at ~21, this is
hand-authored, not a sample from the real ticket distribution.

- **Never `[production]`.** No result over this corpus may carry the `[production]` tag — there is no production
  JIRA/Gerrit behind these cases, only real fleet source.
- **Never blended into the mined `[proxy]` corpus** or `docs/results-log.md`. Report `[authored]` results
  separately so a hand-authored mechanics check can never masquerade as a proxy effectiveness read.
- Grounded (real files/symbols/diffs) does **not** mean representative: the crash logs and ticket prose here are
  written for clarity, not sampled from real JIRA/logcat noise.

Use this corpus to smoke-test a pipeline change end-to-end over real code, and to compare *arms* on a realistic crash
substrate (arm-selection / mechanism-debugging). Use the mined `[proxy]` corpus + the production fleet for actual
effectiveness numbers.
