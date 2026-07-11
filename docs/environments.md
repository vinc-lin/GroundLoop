# Environments — Dev Box vs Production

GroundLoop runs against **two environments**, and conflating them is the single most expensive mistake in
this project. The **dev box** is where code is built and regression-tested against an OSS *proxy* for the
real fleet; **production** is the only place the real ecarx/GEI ecosystem — and its JIRA↔Gerrit oracle —
can be reached. This doc is the canonical statement of that split. Every other doc links here instead of
restating it.

**One-line rule:** the proxy tells you the mechanism *works*; only production tells you it *works well*.
Build on the proxy, trust production.

## The two environments

| | **Dev box (OSS proxy)** | **Production (real GEI)** |
|---|---|---|
| **What it is** | the unscrubbed OSS fleet — `atlas-9.db` + `corpora-local` snapshots (an OSS *stand-in* for the real fleet) | the real 19-repo ecarx/GEI atlas + the JIRA↔Gerrit oracle (the 10-case + 406-case sets) |
| **Reachable?** | **yes** — fast, cheap, hermetic; runs on every change | **no — production-only**; unreachable from the dev box |
| **What runs** | Type-1 hermetic tests (no network / no LLM) + Type-2-on-proxy | Type-2-on-GEI + the deployed `run_ticket` loop + feedback collection |
| **What the numbers mean** | **mechanism / regression — NOT efficacy** (does the pipeline execute + not regress) | **efficacy — the scoreboard** (does it actually match/localize/fix) + the feedback source |
| **Anchor doc** | [`evaluation.md`](evaluation.md) | [`production-guide.md`](production-guide.md) |

The proxy exists because the real corpus can't come to the dev box: it is reachable, fast, and leak-safe,
so it's the right substrate for *building* and *regression-testing*. But its scores are diagnostics of
the machinery, not of the product.

## The develop-against-feedback loop

```
build on the proxy  →  ship to `master`  →  production runs the real evals
        ▲                                              │
        └──────  numbers + failure cases feed back  ◄──┘   (iterate)
```

Development happens on the proxy (hermetic Type-1 + Type-2-on-proxy: fast, deterministic, no leak risk).
Merged work ships to `master`; **production** runs the real 10-case / 406-case oracle evals and the
deployed loop, then relays back the graded numbers and the concrete failure cases. Those become the next
eval slice, regression seed, or design lever — and the cycle repeats. **Production is the oracle of
record:** where the proxy and production disagree, production wins.

## The labeling convention (mandated repo-wide)

Every result number carries an environment tag, so no reader ever mistakes a mechanism check for an
efficacy claim:

- **`[proxy]`** — a mechanism / regression number, built on the dev box. *Optimistic; may not transfer.*
- **`[production]`** — an efficacy number, measured on GEI. *The real number.*

**Rule:** no bare efficacy number anywhere in `STATUS.md`, `results-log.md`, or any future findings doc —
it is **always** tagged. Worked example (a real result):

> functional recall@1 **0.68 `[proxy]`** → **0.10 `[production]`**

A number without a tag is a bug in the writeup.

## Standing lesson: the proxy is optimistic

The example above is the canonical cautionary tale. Functional-text matching scored recall@1
**0.68 `[proxy]`** but only **0.10 `[production]`** — a **size bias**: the OSS proxy's repos are sized
such that generic tokens accrue to a few large repos that win rank-1, and the real GEI atlas doesn't
share that shape. The proxy systematically flatters. Treat a `[proxy]` gain as a hypothesis that
survives only once production confirms it; never report a proxy number as an outcome.

## Reuse contract — one `atlas.db` shape across both environments

Both environments consume an `atlas.db` built the same way, so the two are **structurally identical** and an
index is reusable across runs. (This is about the atlas *shape*, not the scores — per the standing lesson
above, `[proxy]` and `[production]` numbers are **not** interchangeable.) The contract that keeps `atlas.db`
shareable:

- **embed model pinned `bge-m3`** at *both* index time and query time (a mismatch silently corrupts
  cosine ranking — the `SemanticAtlasIndex` dimension guard fails loud instead);
- **stable repo names + pinned SHAs** (the indexed `repo_head` is recorded per unit);
- a **shared `atlas.db` path**;
- the **SQLite schema unchanged** (there is no schema-version guard — any schema change forces a full
  re-index).

Change any of these and cross-run / cross-environment numbers are no longer comparable.
