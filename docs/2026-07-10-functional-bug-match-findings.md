# Functional-Bug Matching Arm — Live A/B Findings (2026-07-10)

The functional (no-crash) matching arm (spec `docs/superpowers/specs/2026-07-10-functional-bug-match-design.md`,
plan `docs/superpowers/plans/2026-07-10-functional-bug-match.md`) is **built, reviewed (READY TO MERGE), and
validated live** on the OSS proxy. This is the Phase-6 result: the 5-arm A/B (`functional` / `dispatch` vs the
v2 crash arms `flood` / `faultslice` / `routing`) over a functional dataset and a crash dataset, with the
crash/functional metrics reported separately.

## The situation (why this is a proxy)

The real validation surface — the **10 GEI cases** and the **406-case oracle** — lives only in the production
environment. We develop against production **feedback** on the OSS proxy; production is the oracle of record.
The feedback that scoped this work: on the 10 GEI cases the v2 `FaultSignalExtractor` returned `no_fault_found`
on **8/10** (no crash frame to anchor on), the routing table had **zero coverage**, and `flood` let large noisy
repos win. This arm targets exactly that class.

## Setup

- **Substrate:** `gloop synth --mode functional` over the mined `dataset-9` → **212 unscrubbed no-crash cases**
  (74 UI-text / 69 audio / 69 CarPlay). Each is a prose ticket describing the bug in **domain terms** (no owner
  slug — see anti-leak below); audio/CarPlay cases carry an **optional non-crash log** (owner's real `.so` /
  handler frame, no crash anchor). Labeled `bug_kind=functional`. The crash half is v2's **196 faultlog** cases
  (`bug_kind=crash`).
- **Fleet:** all 9 OSS repos (`atlas-9.db`, 12.5 GB, 475k units).
- **Text backend:** a **lightweight per-repo bge-m3 text profile** (README + manifest namespace + bounded module
  identifiers) built by `gloop build-textprofile` — a small standalone store, **not** a 12 GB atlas rebuild.
- **Arms:** `functional` = `FunctionalTextIndex` (prose→profile cosine ⊕ optional log-FTS RRF) + text extractor;
  `dispatch` = per-case router (crash-anchor → v2 `FaultRoutingIndex`, prose-only → functional); `flood` /
  `faultslice` / `routing` = the v2 crash arms, as ablations.
- Reproducer: `funceval_ab.sh` / `funceval_rebuild.sh`; log `/home/vinc/gl-eval/funceval-func2.log`.

## Headline — functional attribution doubles, and the crash arms correctly abstain

`attribution_recall@1` over the **212 functional (no-crash)** cases:

| arm | recall@1 | recall@3 | coverage | sel-acc | Φ₁ |
|---|---|---|---|---|---|
| **flood** (baseline) | 0.32 | 0.58 | 0.30 | 1.00 | +0.30 |
| **functional** | **0.68** | 0.79 | 0.58 | 0.83 | **+0.39** |
| **dispatch** | **0.68** | 0.79 | 0.58 | 0.83 | **+0.39** |
| faultslice (v2) | 0.01 | 0.18 | 0.00 | — | 0.00 |
| routing (v2) | 0.01 | 0.18 | 0.00 | — | 0.00 |

Three findings, all decisive:

1. **Text-primary matching more than doubles functional attribution** — `flood 0.32 → functional 0.68` recall@1
   (Φ₁ +0.30 → +0.39). Feeding ticket title+description similarity (the extractor now uses `ticket.summary`,
   which the v2 extractor ignored) recovers the owner on no-crash tickets where the code-token baseline can't.
2. **The v2 crash arms reproduce the production failure mode and the new arm fixes it.** `faultslice`/`routing`
   score **0.01 with 0.00 coverage** on functional cases — they correctly find no fault anchor and abstain
   (exactly the GEI `8/10 no_fault`). The functional arm turns those silent misses into real attributions.
3. **`flood` only answers what its logs hand it.** `flood` coverage is **0.30** (it abstains on 70%): it grounds
   only the audio/CarPlay cases whose optional log names the owner's `.so`/frame (hence sel-acc 1.00 on the few
   it answers), and is blind to the **74 prose-only UI-text cases**. The functional arm's advantage is largest
   exactly there.

## Crash regression check — `dispatch` matches v2, no regression

`attribution_recall@1` over the **196 crash** cases (150 answerable):

| arm | recall@1 | recall@3 | coverage | sel-acc | Φ₁ |
|---|---|---|---|---|---|
| flood | 0.48 | 0.78 | 0.72 | 0.52 | −0.05 |
| functional | 0.23 | 0.36 | 0.55 | 0.34 | −0.11 |
| faultslice | 0.86 | 0.92 | 0.86 | 0.98 | +0.41 |
| routing (v2) | 0.94 | 0.94 | 0.93 | 1.00 | +0.49 |
| **dispatch** | **0.94** | 0.94 | 0.96 | 0.97 | **+0.46** |

`dispatch` recall@1 **0.94 == routing 0.94** — the per-case router sends crash-anchored tickets to v2's fault
routing unchanged. (Coverage/Φ differ by ~0.03 because the `fault_scale = TAU_FUNC[0]/_TAU_RRF[0]` bridge that
lets one abstain-threshold serve both score scales isn't a perfect 1:1 of the score floor; net Φ₁ +0.46 vs
+0.49 is a match, not a regression.) `functional` alone is weak on crash (0.23) — text-cosine over a crash
ticket — which is why the dispatcher, not the bare functional arm, is the production "solve" path.

## The dispatch arm — one arm, both classes

`dispatch` gets **0.94 on crash and 0.68 on functional**, routing purely on whether a crash anchor is present in
the logs (`extract_fault_record(...) is not None`). It is the honest end-to-end "solve" number: it does not
regress the crash class v2 already handles, and it recovers the functional class v2 was blind to.

## Develop-against-feedback in action

The first live run **failed partway**: `build-textprofile` emitted one chunk per source directory (antennapod
alone = 828), flooded the shared single-GPU embed gateway, and a batch `ReadTimeout` aborted the build after
only **4 of 9 repos** — dragging `functional` to a false **0.26** (owners with no profile can't be ranked). The
fix (`perf(index): bound + prioritize repo-text profile chunks; resilient profile embedder`) caps chunks to
READMEs + manifest + bounded module identifiers and uses smaller, longer-timeout embed batches; the rebuilt
9/9-repo profile gave the valid **0.68**. This is precisely the loop this project runs: the proxy surfaces a
failure, we fix it, and only then trust the number.

## Anti-leak (the number is earned, not given)

Functional tickets ground the owner by **domain-semantic** similarity (e.g. "offline map and place navigation"
→ organicmaps' README), never by naming the repo. A red-test asserts the owning-repo slug never appears in the
ticket summary/description (`tests/synth/test_functional.py`), and a source-scan red-test asserts the matching
modules never read the oracle (`tests/index/test_functional_antileak.py`). Without this, the leaked FQ class the
first draft embedded would have let `flood` recover the owner from the ticket and inflated a false win — caught
by the final holistic review before any number was recorded.

## Caveats & follow-ups

- **`flood` grounds audio/CarPlay via the optional log** (owner `.so`/frame), so the functional win is largest
  on the prose-only UI-text slice; on audio/CarPlay both arms benefit from the log. This is honest — the arm's
  unique value is the no-signal-at-all UI-text class.
- **Abstention here is coverage-based** (functional coverage 0.58 = it abstains on 42% when the text signal is
  too weak). This dataset is 100% answerable, so `abstention_recall_oof` is not exercised in this run; the
  functional honest-refusal negatives (`build_functional_negatives`) are unit-tested but not folded into this
  A/B dataset yet — a natural next slice.
- **Component routing is out** (the user confirmed JIRA `component` is unusable even in production); the arm is
  text-primary by design.
- **Internal vs external validity:** these establish that the mechanism works, doubles functional attribution,
  and does not regress crash — on the proxy. The real recall on the GEI/406 oracle is a **production-feedback**
  measurement; this arm is built to feed that loop.

## Engineering result

- **28 commits**, full suite **530 passed / 7 skipped**, ruff clean.
- **Frozen/gated surfaces zero-diff** across the whole branch: no `groundloop/core/`, no
  `engines/atlas/store.py` schema, no `adapters/index/atlas.py` `rank_repos`, no `owner_tokens.py`, no
  `repo_routing.py`, no `mine/` — the feature rides new domain/index/funceval/synth modules + additive
  offline-grader edits, swapped at the composition root.
- Subagent-driven, per-task two-stage review + a final holistic review. The reviews caught **six real defects**
  that would have silently corrupted the eval — most importantly the ticket-text owner-slug leak (would have let
  `flood` cheat) and the `dispatch` tau-scale mismatch (would have made `dispatch` over-abstain on crash).

## Bottom line

Isolating a no-crash ticket's **domain-semantic** signal and matching it against a lightweight per-repo text
profile **doubles** functional-bug attribution (recall@1 0.32 → 0.68) where the crash-based matcher scores ~0
and correctly abstains; a per-case dispatcher then delivers **0.94 on crash and 0.68 on functional** from one
arm, with no crash regression. The v2 "second problem" — *identify and attribute the no-crash functional bug* —
is validated end-to-end on the proxy and ready to feed the production loop.
