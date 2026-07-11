# 10-Case End-to-End Evaluation — Status & Root Cause (2026-07-11)

First full **8-stage `gloop run`** over the 10 functional GEI cases (`$GL_DATA/dataset-new/`), **component
match arm**, empirical affinity map (`component_affinity.json`, mined from **1,169 JIRA↔Gerrit oracle
pairs**), real atlas (**19 repos, 126,919 units**), bge-m3 (TEI) retrieve + **qwen3p6-27b** re-rank. Every
case ran all 8 stages to a bound change (0 crashes). This is the first **production efficacy read** for the
component-routing pivot (proxy mechanism check was `docs/2026-07-10-component-routing-findings.md`; production
is the only real scoreboard). It documents what happened at each stage and the root cause of every miss.

> **This is production-only feedback.** The GEI corpus / the 10-case + 406-case oracles live only in the
> production environment; the dev box cannot reach them. Numbers here were relayed from the production run.

## Scorecard (the three graded stages)

| Stage | Metric | Score | Note |
|---|---|---|---|
| **Match** | recall@1 (owning repo) | **7/10** ⚠ | per the per-case table below; the run summary reported **8/10** — see the count-reconciliation note |
| **Localize** | file@5 (oracle repo, rerank top-5) | **7/10** | measured on the oracle repo → match-independent |
| **Localize** | file@1 | **1/10** | rerank gets it into top-5, rarely exactly top-1 |
| **Fix** | patches a real oracle file | **0/10** | **empty worktree** — no corpus checkout for any owner (ungraded, not a fix-stage failure) |

**⚠ Count reconciliation (grounding over narrative).** The run's summary line read **Match 8/10** ("8 cases
at affinity rank 1"), but the per-case table below shows **7 ✓ / 3 ✗** (misses: `13363`, `14905`, `8185`).
The 8-vs-7 gap is because the root-cause writeup groups the two CarPlay-Core misses (`14905` + `8185`) as a
single "near-tie" *cause* — that's 2 root causes but **3 missed cases**. **Reconcile against the raw
scorecard** and correct this doc + STATUS to whichever the run output actually reports; the granular table is
treated as truth here (7/10) pending that confirmation.

**A second measurement correction.** An earlier pass reported "localize 0/10." That number was reading the
**fix stage's** patched file (fabricated — see Fix below), not the **localize** retrieve output, which
`gloop run` does not persist. Measured directly on `AtlasIndex.retrieve`, localize is **7/10 file@5** — the
retrieve+rerank pipeline is working; the fabrication is a *fix-stage* grounding gap, not a localize failure.

---

## Per-case status

| Case | Component | Owner (oracle) | Match | Localize (rerank rank) | Fix worktree |
|---|---|---|---|---|---|
| 12870 | Audio | engineering | ✓ r1 | ✓ @2 (AudioConnectionsViewModel.kt) | empty |
| 13196 | Engineering Mode | engineering | ✓ r1 | ✓ @1 (ScreenshotUtils.kt) | empty |
| 13363 | Bluetooth | XCClusterService | ✗ r6 | ✓ @4 (GeneralApiManager.kt) | empty |
| 14905 | CarPlay | CarPlayCoreService | ✗ r2 | ✗ not in pool | empty |
| 4240 | Engineering Mode | engineering | ✓ r1 | ✗ not in pool | empty |
| 5877 | WLAN | BluetoothEnhancement | ✓ r1 | ✓ @2 (DefaultNameProcessor.java) | empty |
| 6360 | CarPlay | CarPlayIntegrationService | ✓ r1 | ✓ @2 (PrivacyActivity.kt) | empty |
| 8185 | CarPlay | CarPlayCoreService | ✗ r2 | ✗ not indexed | empty |
| 8233 | WLAN | BluetoothEnhancement | ✓ r1 | ✓ @5 (BorderCrossingService.kt) | empty |
| 8678 | CarPlay | CarPlayIntegrationService | ✓ r1 | ✓ @3 (CPUIExtension.kt) | empty |

Tally: **Match 7 ✓ / 3 ✗** · **Localize 7/10 file@5, 1/10 file@1** · **Fix 0/10 (ungraded)**.
"Match rN" = oracle's rank in the pure-affinity ordering. "Localize @N" = oracle file's rank after qwen
re-rank on the oracle repo.

---

## What happens at each stage (the pipeline)

1. **intake** — `MockJira.fetch` loads `ticket.json` (summary, description, JIRA `component`, logs).
2. **extract** — `ComponentExtractor(AndroidSignalExtractor)` produces log/token signals **and** rides the
   `component` string through the frozen `Signals` seam as a reserved marker.
3. **match** — `ComponentPriorIndex.rank_repos`: base `AtlasIndex` (FTS5) contributes a scale-invariant
   rank-based RRF term (≤1/60≈0.017); the L1-normalized component affinity is added on top and dominates.
4. **materialize** — `MockEstate.materialize`: looks for `$GL_DATA/repos/<owner>`; **none exists except
   XCIPadMediaService**, so all 10 fall back to an **empty** worktree.
5. **localize** — `AtlasIndex.retrieve` (symbol-only, noise-filtered): keyword pool ∪ bge-m3 vector pool
   (k=60 each) on the summary+description query, then qwen re-rank to top files. Reads the **atlas**, not the
   worktree — so it works despite the empty worktree.
6. **fix** — `ModelPatchEngine`: qwen reads worktree snippets + localize files → proposes a patch. With an
   empty worktree it has no real source, so it **fabricates** a plausible path.
7. **submit / bind** — `MockGerrit` records the change and links it to the ticket (`changes.jsonl`).

---

## Root cause analysis

### Match — 2 causes / 3 missed cases

**(a) 13363 `Bluetooth` → `XCClusterService` (oracle at affinity rank 6).**

Label ≠ owner. The ticket is tagged `Bluetooth`, but the defect (Bluetooth-music folder/track info on the
**cluster** display) was fixed in `XCClusterService`. The affinity map — correctly reflecting history — sends
`Bluetooth` to `BluetoothEnhancement` (0.49) first; `XCClusterService` carries only 2/53 of `Bluetooth`'s
mass. **No prior over the `component` field alone can fix this** — the tester's component and the code owner
genuinely disagree. Needs a log/ticket-text signal (the bug mentions "cluster"/"仪表").

**(b) 14905 & 8185 `CarPlay` → `CarPlayCoreService` (oracle at affinity rank 2).**

Near-tie. `CarPlay` splits almost evenly in history: `CarPlayIntegrationService` 75 vs `CarPlayCoreService`
74 (normalized 0.381 vs 0.376). The 0.005 gap is **smaller than the base FTS5 RRF term (≤0.017)**, so the
logcat signal is the effective tiebreaker — fragile. `6360`/`8678` (true owner = Integration) land right;
`14905`/`8185` (true owner = Core) land wrong. This is the documented CarPlay Core-vs-Integration ambiguity:
it needs semantic disambiguation (ticket text vs the two repos' descriptions), not a weight tweak.

The other 7 cases have the oracle at affinity **rank 1** — the empirical prior is clean for Audio,
Engineering Mode, and WLAN (the WLAN→BluetoothEnhancement:25 correction the hand-map missed is now learned).

---

### Localize — 3 misses, two distinct causes

The retrieve pipeline is **coverage → pool → rerank**. Measured on the oracle repo (so match errors don't
contaminate it):

- **Rerank works.** For all 7 cases whose oracle file reaches the candidate pool, qwen lifts it into top-5 —
  often from deep pool ranks (6360: pool@42→rerank@2; 8678: pool@38→rerank@3; 13363: pool@13→rerank@4).
  file@5 == pool-recall (7/7): rerank never drops an in-pool oracle file out of the top-5.
- **The keyword pass alone almost never hits** (kw_hit = None for 8/10); the **bge-m3 vector pass** is what
  pulls the oracle file into the pool. Hybrid retrieval is load-bearing.

**(a) 8185 — coverage gap.** `CpAccessibilityManager.kt` (the sole expected file) is **not in the atlas**
(the indexed CarPlayCoreService snapshot predates or excludes it). Localize ceiling = 0 regardless of
retrieval.

**(b) 14905 & 4240 — pool recall gap.** The oracle files (`CpSessionStateManager.java` /
`LogManagementFragment.kt`) **are indexed** but neither the keyword nor the vector pass on the
summary+description query surfaces them into the 60+60 pool. The query text doesn't lexically or semantically
align with the file's symbol text. This is the per-symbol-embedding ceiling noted in the localize plan —
reaching them needs per-file aggregation / richer unit text / larger k.

---

### Fix — 0/10 grounded (single cause)

**Empty worktree.** `$GL_DATA/repos/` contains a checkout only for `XCIPadMediaService`; none of the 10
owners (engineering, CarPlay*, BluetoothEnhancement, XCClusterService) have one. `MockEstate` falls back to
an empty dir, so `ModelPatchEngine` has no real source and fabricates paths (e.g. `system/core/init/init.cpp`
for a WLAN case). The fix stage is therefore **ungraded** on this set — its patched files in `changes.jsonl`
are not real and must not be read as localization.

---

## Takeaways & next steps

1. **Match is healthy and the empirical map generalizes** — the misses are a label/owner disagreement
   (13363) and the CarPlay near-tie (14905/8185), both needing signal *beyond* the component field. Neither
   is a weight-tuning problem. (This is the first production confirmation that the mined affinity prior —
   the pivot's core lever — carries over from the 1,169-pair training set to unseen tickets.)

2. **Localize is 7/10 file@5, not 0/10** — hybrid retrieve + qwen rerank works. Closing the last 3 needs:
   - index `CpAccessibilityManager.kt` (coverage — 8185)
   - per-file embedding aggregation / richer unit text / larger k (pool recall — 14905, 4240)

3. **Fix is unmeasurable until owners are checked out.** Add corpus checkouts for the 4 owner repos under
   `$GL_DATA/repos/` (as done for `XCIPadMediaService`) → the fix stage reads real source instead of
   fabricating. This is the **highest-value unblock** for grading downstream. *(Production-side.)*

4. **CarPlay disambiguation** (gate on the 406-run): a ticket-text-vs-repo-description semantic tiebreak for
   the Core-vs-Integration near-tie — cheapest first (keyword heuristics: `reconnect`/`重连` → Integration,
   `session`/`Siri` → Core), then embed vs the two repos' business descriptions, then LLM re-rank. Do this
   **only if the 406 confirms CarPlay ambiguity is broad**; this 10-case slice shows 2/4 CarPlay cases miss
   (small n). The same is true for the 13363 label≠owner case: build a `component`-override text signal
   (e.g. "cluster"/"仪表" → `XCClusterService`) only once the 406 shows label/owner disagreement is broad.

## Where responsibility sits (dev box vs production)

- **Production-side (run there):** the 4 owner-repo checkouts (unblocks fix grading); index
  `CpAccessibilityManager.kt` + any other missing snapshots (closes the coverage gap); the full **406-case
  LOO** run that arbitrates whether CarPlay ambiguity and label≠owner disagreement are broad problems worth
  building for.
- **Dev-box (buildable here, leak-safe on the proxy, gated on the 406):** the CarPlay Core-vs-Integration
  semantic tiebreak; the `component`-override text signal for label≠owner cases; per-file embedding
  aggregation for localize pool recall. Each stays oracle-blind at runtime and is validated on production.
