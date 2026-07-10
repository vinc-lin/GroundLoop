# Stage-1 Match via Component Routing — Design Spec (2026-07-10)

## 1. Charter & situation

Production feedback on the real GEI corpus (relayed 2026-07-10) redirects the **functional-bug** match track.
On the real 19-repo atlas, ticket-text matching collapses to **recall@1 = 0.10** (size-biased: huge AOSP repos
like `Telecomm`/`NetworkStack` win rank-1 on any full-system logcat). The **dominant, near-zero-cost signal is
the JIRA `component` field** — an additive component→repo affinity prior lifts recall@1 **0.10 → 0.50** and
recall@3 to **0.90** on the 10 GEI cases (measured, FTS5-only, no model call). This supersedes the functional
next-steps of `docs/2026-07-09-android-log-match-v2-findings.md` for the functional class; the crash/fault track
there stays valid for its intended input.

**Reconciling the earlier "component not usable" decision:** that was correct for *naive lookup* — the skills
`owners.json` keys are **repo names** while JIRA `component` is **functional-area names** (`CarPlay`, `Audio`,
`WLAN`), so direct lookup is 0/10. The fix is an **empirically-derived affinity map** (`component → owning_repo`
co-occurrence, learned from the JIRA↔Gerrit oracle) that bridges the vocabulary at zero token cost. Component
routing is back — done right.

**Where the earlier functional (text-similarity) arm fits:** it is not wasted — it becomes a **base** the
component prior re-ranks (recall@3=0.90 means the component narrows the field to ~3 repos; the base must pick the
owner among them). This is a *ranking* problem inside a narrowed set, not a coverage problem.

**Environment reality:** the GEI data/atlas/scripts are **production-only** (unreachable from this dev box). So
this spec builds the component-routing **code** on the proxy — leak-safe, tested, with a synthetic-component
mechanism check — and **production runs** the real affinity build + the 406-case leave-one-out eval + Step-3
indexing. Production is the scoreboard.

## 2. The measured evidence (production, 10 GEI cases)

| arm | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|
| flood (logcat FTS5) | 0.10 | 0.10 | 0.40 | 0.245 |
| text (ticket summary+desc FTS5) | 0.10 | 0.20 | 0.30 | 0.226 |
| fusion RRF(flood+text) | 0.00 | 0.20 | 0.50 | 0.221 |
| **comp+fusion** (component prior) | **0.50** | **0.90** | **0.90** | **0.708** |

Two structural misses at 0.50 (both ranking, not coverage): `WLAN`→`BluetoothEnhancement` (a hand-map weight
error the **empirical** map auto-corrects) and `CarPlay`→Core-vs-Integration ambiguity (deferred to Step 4).

## 3. Non-goals (YAGNI / production-side)

- **Not building the real affinity table** (`component_affinity.json` over the 1,169-ticket oracle) — that runs
  on production. This spec ships the **miner script** + the loader + a synthetic proxy table.
- **Not Step 3** (indexing `XCUSBMediaService`, building the real crash dataset) — production-side; unblocks the
  crash track separately.
- **Not Step 4** (CarPlay Core-vs-Integration disambiguation) — only 2 GEI cases; explicitly gated on the
  406-run showing it's a broad problem; token-cost, done last if at all.
- **No LLM/embed cost in the component arm** — the prior is pure arithmetic over the affinity table.
- **No edits to `core/`, the atlas schema, `rank_repos`, `owner_tokens.py`, `repo_routing.py`, `mine/`.**

## 4. The empirical affinity map

- **Data table** `groundloop/domains/android_ivi/data/component_affinity.json` — built offline. Stores **raw
  co-occurrence counts** `counts[component][repo] = n` (NOT pre-normalized), so leave-one-out can subtract a
  case's own contribution before normalizing.
- **Loader** `groundloop/domains/android_ivi/component_affinity.py` — `ComponentAffinity.load(path)`; method
  `affinity(component, *, exclude=None) -> dict[repo, weight]` returns L1-normalized weights over repos for that
  component, optionally subtracting one `(repo)` unit for the excluded owner (leave-one-out). Unknown component →
  empty dict (no boost).
- **Offline miner** `groundloop/domains/android_ivi/mine_component_affinity.py` (a standalone script/function,
  NOT under the gated `mine/`) — `build_affinity(dataset_root) -> counts` reads each case's loop-visible
  `ticket.json` `component` **and** its offline `_oracle/oracle.json` `owning_repo`, tallies
  `counts[component][owner] += 1` over **answerable** cases (skip negatives / `__NOT_A_DEFECT__` / empty
  component), and writes the JSON. On production this runs over the full oracle; the counts are population
  statistics, not per-ticket memory.

## 5. Leak integrity (two distinct questions)

1. **Loop leak (runtime):** the arm's runtime input is **only `Ticket.component`** (a loop-visible JIRA field)
   plus the affinity table. It never reads `_oracle/` / `owning_repo` at match time. `Ticket.component` carries
   the contract "MUST NOT be the owning repo" (`core/types.py`). ✓ No loop leak. A red-test greps the runtime
   modules (`component_affinity.py`, the extractor, `ComponentPriorIndex`) for oracle symbols → zero.
2. **Train/test leak (eval validity):** the affinity table is *learned from the oracle*, so scoring a case with
   a table built over that same case is memorization. **Mitigation = leave-one-out**: when ranking case `C`
   (owner `O`, component `K`), the prior uses `affinity(K, exclude=O)` — the table with `C`'s own `(K→O)` unit
   subtracted. The miner stores raw counts precisely so LOO is exact and O(1). The eval runner passes the
   per-case owner to the prior **only through the offline-grader-adjacent LOO path**, never into the loop —
   i.e. LOO exclusion is applied in a dedicated eval mode that is explicitly not the production runtime path
   (production has a temporal/train-test split instead). This keeps the shipped runtime loop-blind while making
   the proxy/eval number honest.

   > Design note: to keep the runtime `ComponentPriorIndex.rank_repos(signals, catalog)` **loop-blind**, LOO is
   > implemented by giving the *eval harness* a per-case pre-excluded `ComponentAffinity` view (built offline by
   > the grader-side code that already knows the owner), NOT by passing the owner through `rank_repos`. The
   > production runtime uses the full (or temporally-split) table with no per-case exclusion.

## 6. ComponentExtractor + ComponentPriorIndex (frozen-safe)

`rank_repos(signals, catalog)` only ever receives `Signals` (never the `Ticket`), and `core/` is frozen. So the
component rides through the `Signals` seam, exactly like the prose slot:

- **`ComponentExtractor(base_extractor)`** (`groundloop/domains/android_ivi/component_signals.py`) — runs
  `sig = base_extractor.extract(logs, ticket)` (any base: `AndroidSignalExtractor`, `TextOnlyExtractor`,
  `FunctionalTextExtractor`), then, if `ticket.component`, appends a single reserved token
  `COMPONENT_MARK + ticket.component` to `sig.errors` (a carrier field bases treat as a harmless FTS token).
  A helper `component_of(signals) -> str` recovers it (strips `COMPONENT_MARK`; `""` if absent).
- **`ComponentPriorIndex(base_index, affinity, *, weight)`** (`groundloop/adapters/index/component_prior.py`) —
  implements `CodeIndex`. `rank_repos`: read `comp = component_of(signals)`, then **strip the marker before the
  base sees it** — `clean = strip_component(signals)` (drops the `COMPONENT_MARK` token so the component string
  never enters the base FTS/cosine query and can't be double-counted); `ranked = base_index.rank_repos(clean,
  catalog)`; `boost = affinity.affinity(comp)` (or the eval's LOO view); new score per repo =
  `base_score + weight * boost.get(repo, 0.0)`, restricted to `catalog`, re-sorted desc. `retrieve` delegates to
  the base. The `weight` is a calibration seed (default `_COMPONENT_WEIGHT`, chosen so the prior dominates
  ranking per recall@3=0.90); frozen after a production calib pass. `component_of`/`strip_component` are the
  matched-pair readers of the `COMPONENT_MARK` carrier token.

## 7. The component eval arm + `--match-arm`

- Add a **`component`** arm to `groundloop/funceval/arms.py` (and mirror in `groundloop/eval/arms.py`): pairs
  `ComponentExtractor(FunctionalTextExtractor())` (or the text base) with
  `ComponentPriorIndex(FunctionalTextIndex|AtlasIndex, affinity, weight=…)`, on the text/cosine tau scale.
- **`gloop funceval --affinity <component_affinity.json> [--loo]`** — loads the affinity table; `--loo` runs the
  eval in leave-one-out mode (grader-side per-case exclusion). Without `--affinity`, the component arm is
  skipped (opt-in).
- **`gloop run --match-arm {flood,routing,component}`** (composition root, default `flood` for back-compat) —
  swaps the index+extractor pair passed to `run_ticket`; the `component` value comes from the loop-visible
  `Ticket.component`. No `core/` edit.

## 8. Proxy validation (mechanism, not efficacy)

The proxy tickets have empty `component`. To exercise the re-ranker + LOO miner hermetically **and** in a small
proxy A/B, synthesize a coarse, **many-to-one** component per case (a component maps to several repos, mirroring
the real "component narrows to ~3, base picks" regime — never a 1:1 owner alias, which would be a fake win):

- `gloop synth --mode functional` gains a `--components <taxonomy.json>` option (or a sibling stamping pass) that
  writes a synthetic `ticket.component` drawn from a small taxonomy keyed by the owner's domain, with deliberate
  many-to-one overlap and a controlled fraction of ambiguous/blank components (so abstention + LOO both fire).
- Build the affinity table over the synthetic set, run `funceval --affinity … --loo`, and show the `component`
  arm lifts recall@1 over the text base **under LOO** — proving the mechanism (miner + re-ranker + honest LOO),
  not real efficacy. The findings doc states plainly this is a mechanism check; the real number is production's.

## 9. Metrics (acceptance)

- **Proxy (mechanism):** under **leave-one-out**, the `component` arm's recall@1 exceeds its text base on the
  synthetic-component set, and a red-test confirms LOO actually changes the score for a case whose owner is the
  sole contributor to its component (i.e. LOO is load-bearing, not a no-op).
- **Loop-blind:** the runtime `ComponentPriorIndex`/extractor/`component_affinity` read no oracle (red-test).
- **Frozen/gated zero-diff.** Full hermetic suite green + ruff clean.
- **Production (the real number, run by you):** `component` arm recall@1/@3 on the full 406-case oracle under
  LOO; the target is the 0.50/0.90 seen on the 10-case spot check, generalized.

## 10. Frozen / gated surfaces (never edit; may READ)

`groundloop/core/`; the atlas schema in `engines/atlas/store.py`; `AtlasIndex.rank_repos`; `owner_tokens.py`;
`repo_routing.py`; **all of `mine/`** — the affinity miner is a NEW standalone module under `domains/`, not an
edit to the gated GitHub miner. New modules + additive `funceval`/`eval`/`cli` edits only, swapped at the
composition root.

## 11. Build order (→ plan)

1. **ComponentAffinity loader + LOO** (`component_affinity.py`, raw counts, `affinity(component, exclude=…)`).
2. **Offline miner** (`mine_component_affinity.py` + `gloop mine-affinity` CLI) over a dataset → JSON.
3. **ComponentExtractor + `component_of`** (`component_signals.py`, `COMPONENT_MARK`).
4. **ComponentPriorIndex** (`component_prior.py`, additive re-ranker, catalog-restricted).
5. **`component` funceval arm + `--affinity`/`--loo`** + the grader-side LOO view; loop-blind + LOO red-tests.
6. **`gloop run --match-arm`** composition-root wiring.
7. **Synthetic-component proxy stamping + a proxy LOO A/B** (mechanism) → findings doc.
Production-side (you): real affinity build + 406 LOO eval; Step-3 `XCUSBMediaService` index; Step-4 CarPlay (gated).
