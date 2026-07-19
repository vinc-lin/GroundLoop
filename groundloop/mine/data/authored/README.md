# Authored cases — `[authored]`

This directory holds **3 hand-authored, full-Tier-B crash cases**, each grounded in real source from
the GEI fleet corpus (`/mnt/x/code/corpora/<repo>/`, pinned by `owning_repo_sha` in each case's
`_oracle/oracle.json`):

- `crash-01-native-audio-resampler` — native SIGSEGV in `oboe` (`MultiChannelResampler::writeFrame`)
- `crash-02-java-stream-helper` — `IndexOutOfBoundsException` in `newpipe` (`SecondaryStreamHelper.getStream`)
- `crash-03-c-logging-message` — native SIGSEGV in `dlt-daemon` (`dlt_message_read`)

`catalog.json` lists the full 9-repo GEI fleet (from `/mnt/x/code/corpora/atlas.toml`), not just the
3 owning repos, so a matcher run against this dataset ranks the ticket against a realistic set of
confusable candidates rather than a rigged 1-of-1 choice.

Every case is checked by `groundloop.mine.authored.validate_authored_case(case_dir, corpora_root)`,
which returns `[]` only when: each `expected_files` entry is a real file in the real repo tree, each
`required_apis` symbol appears in that file's real text, the crash log names an oracle symbol
(grounded, not disconnected prose), the ticket (summary/description/logs **and** `ticket["id"]`) never
leaks the `owning_repo` name, and `fix.diff` both touches an `expected_files` path and references a
`required_apis` symbol on an added line. `fix.diff` hunk headers/context are hand-verified against the
pinned SHA's real file content so `git apply --check` applies cleanly with zero fuzz/offset.

## What this is — and is not

**Role: a mechanics/capability test, not an effectiveness measurement.** These 3 cases exist to answer
one question: *can the loop carry a realistic crash end-to-end over real code* (ticket -> match ->
localize -> fix -> grade), with every oracle field anchored to source that actually exists on disk —
not whether the loop is *good* at it. n=3 is far too small, and hand-authored-for-clarity text is not a
sample from the real ticket distribution.

- **Never `[production]`.** No result computed against this corpus may carry the `[production]` tag
  (see `docs/environments.md` for the tag convention) — there is no production JIRA/Gerrit behind these
  cases, only real fleet source.
- **Never blended into the mined `[proxy]` corpus.** Aggregate scorecards (recall@k, `resolved_rate`,
  etc.) reported over the mined GitHub-issue corpus must not silently fold these 3 cases in — report
  `[authored]` results separately so a 3-case mechanics check can never masquerade as a proxy
  effectiveness read.
- Grounded (real files/symbols/diffs) does not mean representative: the crash logs and ticket prose
  here are written for clarity, not sampled from real JIRA/logcat noise the way the mined corpus is.

Use this corpus to smoke-test a pipeline change end-to-end over real code; use `docs/evaluation.md`'s
mined `[proxy]` corpus (and the production fleet, for `[production]`) for actual effectiveness numbers.
