# Runbook — `[production]` GEI gate for `--localize cascade_judge`

**Purpose:** decide whether `cascade_judge` (the cascade recall pool reordered by the LLM file-judge) earns
**Candidate → Core** on real GEI data. `[proxy]` showed it is the best localize arm to date (file@1 0.245 vs the
prior-best `rerank_cw_judge` 0.206, ~equal cost — `docs/results-log.md` 2026-07-18), on **prose functional**
tickets. GEI is **crash-heavy**, a different regime, so this read must **split by `bug_kind`** and is the
resolver. GEI/406 data is **production-only** — run this on the production box; the orchestrator (Claude) cannot.

**Owner:** you (production env). **Est. cost:** ~`$0.0015/case` × 2 judge arms × |GEI| (the LLM judge is the
spend; the plan fixer runs too but its output isn't graded for the localize decision).

---

## 0. The decision this answers

`cascade_judge` is promoted from Candidate to Core-default localize **iff**, on GEI, graded by `gloop grade-run`:

1. **It lifts as-run localize `file@1`** over the current Core default (`atlas`) — **overall AND on the crash
   split** (no crash-regime regression; crash is GEI's majority and where FTS code-tokens already localize well,
   so the judge must not *hurt* it).
2. **It does not regress the functional split** vs `rerank` (the prior-best judged arm) — ideally reproduces the
   `[proxy]` win there.
3. **Cost/latency per case is acceptable** for the production loop.

If (1) holds only on the functional split, keep `cascade_judge` as a **reachable Candidate** (opt-in), not the
global default — same governance line as the labs arms (`docs/capabilities.md`).

---

## 1. Prerequisites — verify BEFORE running (each is a real gate)

Set these once (never echo secrets/URLs):
```bash
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a          # KLOOP_EMBED_BASE_URL (bge-m3), KLOOP_PRODUCE_API_KEY (+ gateway), KLOOP_REGISTRY
export GEI_DATASET=...            # the GEI case dirs (ticket.json + _oracle/oracle.json), e.g. $GL_DATA/dataset-new
export GEI_ATLAS=...              # the 19-repo production atlas.db (on ext4)
export GEI_CATALOG=...            # catalog.json of GEI repo names
export GEI_REPOS=...              # clone root: <root>/<repo>/<file> must resolve  (REQUIRED — see gotcha #1)
export WORK=/var/tmp/cjgate; export RUNS=$WORK/runs; export CARDS=$WORK/cards
mkdir -p "$RUNS" "$CARDS"         # keep everything off v9fs — /var/tmp, /home/vinc, or /dev/shm
```

**Hard prerequisites (a failure here invalidates the read):**

1. **`--repos` resolves to real source.** The cascade returns bare file paths, so the judge's SOURCE context
   comes entirely from `source_reader` over `$GEI_REPOS/<repo>/<file>`. Without it the judge reranks **bare
   paths** (worse than a source judge) — the number would be meaningless. Verify a known file reads:
   `test -f "$GEI_REPOS/<some-repo>/<some/known/File.kt>" && echo OK`.
2. **The GEI atlas has DOC UNITS (CodeWiki).** cascade_judge's CodeWiki-context edge (the +0.055 in `[proxy]`)
   comes from a doc lane that needs doc units in the atlas. If there are none, cascade_judge degrades to a
   source-only judge (~0.157, not 0.245) and the read is NOT comparable to `[proxy]`:
   ```bash
   sqlite3 "$GEI_ATLAS" "SELECT COUNT(*) FROM units WHERE kind='doc';"   # must be > 0
   ```
   If `0`: the 19-repo atlas has no CodeWiki — you must first produce+index doc units for the GEI fleet (a large
   build), or accept that this read measures a **source-only** cascade_judge (label it so).
3. **The atlas has bge-m3 vectors** (the cascade semantic tier): `sqlite3 "$GEI_ATLAS" "SELECT COUNT(*) FROM
   vectors;"` should ≈ `SELECT COUNT(*) FROM units`. If under-populated, the semantic tier is dead.
4. **`bug_kind` on the oracle** (for the split). `gloop grade-run` reads `oracle.bug_kind`; if the GEI oracles
   lack it, run the labeller first: `gloop label-bugkind --dataset "$GEI_DATASET"` (see `--help`).
5. **Embedder + judge reachable, off ext4.** `gloop doctor --atlas-db "$GEI_ATLAS"` (repos ready, embed gateway
   OK); confirm `KLOOP_PRODUCE_API_KEY` is set (the judge) and `KLOOP_REGISTRY` points at the GEI entity_maps
   (the CodeWiki doc→source bridge — without it the doc lane can't attach wiki even if doc units exist).

---

## 2. The runs (match arm fixed = Core `component`; vary only `--localize`)

Three arms: the Core baseline, the prior-best judged arm, and the candidate. Same dataset/atlas/repos throughout.

```bash
RUN () {                                  # RUN <arm-name> <localize-flag>
  gloop run --dataset "$GEI_DATASET" --catalog "$GEI_CATALOG" --index-db "$GEI_ATLAS" \
            --repos "$GEI_REPOS" --work "$WORK/$1.work" --changes "$WORK/$1.changes" \
            --out "$RUNS/$1" --match-arm component --localize "$2" --fixer plan
}
RUN atlas        atlas           # the current Core default (baseline to beat)
RUN rerank       rerank          # rerank_cw_judge equivalent: judge over its OWN pool (prior best) — needs KLOOP_REGISTRY+creds+--repos
RUN cascade_judge cascade_judge  # the candidate: judge over the CASCADE pool
```
Notes: `--localize rerank` **fail-fasts** without an embedder (by design); `cascade_judge` does not (it degrades,
but you want the embedder ON — prerequisite #3). `--fixer plan` runs but only the **localize** section of the
scorecard drives this decision.

---

## 3. Grade + compare (as-run + isolated, by `bug_kind`)

```bash
GRADE () {                                # GRADE <arm-name> [compare-card]
  gloop grade-run --runs "$RUNS/$1" --dataset "$GEI_DATASET" --index-db "$GEI_ATLAS" \
                  --out "$CARDS/$1.json" ${2:+--compare "$2"}
}
GRADE atlas
GRADE rerank         "$CARDS/atlas.json"          # rerank vs the Core default
GRADE cascade_judge  "$CARDS/rerank.json"         # cascade_judge vs the prior best (the headline diff)
GRADE cascade_judge  "$CARDS/atlas.json"          # (re-grade) cascade_judge vs the Core default (the promotion gate) -> a 2nd card if you want both diffs
```
`--index-db` enables the **isolated-localize** diagnostic (re-runs `retrieve` on the ORACLE repo, grade-only).
`--compare` appends a per-stage regression section. A `.md` table is written alongside each `card.json`.

---

## 4. Read the scorecard — which numbers decide

Open `$CARDS/cascade_judge.json` (+ the `.md`). For the localize decision look at **`overall.localize`** and the
**`by_bug_kind`** split:

- **`localize.as_run.file@{1,3,5}`** — **THE number for cascade_judge.** As-run = the loop's real localized files
  on the MATCHED repo, WITH the judge. This is what to compare across arms and what maps to the `[proxy]` win.
- **`localize.isolated.file@{1,3,5}`** — the on-oracle-repo diagnostic. **IMPORTANT: for cascade_judge the
  isolated pass is JUDGE-LESS** (the offline grader has no judge creds; the arm reconstructs as
  `cascade_judge(no-judge:cascade-pool)`). So isolated = the cascade **pool recall ceiling**, not the judge —
  do NOT read isolated@1 as cascade_judge's number; it's the recall floor the judge builds on.
- **`by_bug_kind.{crash,functional}.localize.as_run.file@1`** — the split that actually decides promotion (§0).

Cross-arm: compare `atlas` vs `rerank` vs `cascade_judge` on `as_run.file@1` overall and per split; read the
`--compare` regression section for newly-won / newly-lost cases and the $/case delta.

---

## 5. Promotion decision

| Outcome | Verdict |
|---|---|
| `cascade_judge` as-run file@1 **> atlas overall AND ≥ atlas on the crash split**, and **≥ rerank on functional**, cost acceptable | **Promote to Core default localize.** Flip the default (composition root only, no `core/` edit), record `[production]` in `results-log.md`, update `capabilities.md` (Candidate → Core). |
| Lifts only the **functional** split, flat/regressed on crash | **Keep as a reachable Candidate** (opt-in `--localize cascade_judge`), do NOT flip the default. Record the split result. |
| Flat or regressed vs `atlas` | **Do not promote.** Record the null honestly; the `[proxy]` win did not transfer to the GEI regime (likely crash-dominated — FTS code-tokens already localize crashes). Consider the CamelCase-atlas + functional-GEI-subset reads before abandoning. |

Whatever the outcome, tag every number `[production]` and append a dated section to `docs/results-log.md` +
a STATUS entry. If promoting, also run the deferred **A3 match-regression** check on any CamelCase atlas used.

---

## 6. Gotchas & caveats (each caught in review — do not skip)

1. **`--repos` is REQUIRED** (prerequisite #1). Bare-path judge otherwise. (A future robustness fix — an
   atlas-snippet floor in `RerankLocalizeIndex._pool_index_hits` — would remove this dependency; not shipped.)
2. **DOC UNITS gate the CodeWiki edge** (prerequisite #2). No doc units ⇒ source-only judge, not the `[proxy]`
   0.245; label the read accordingly.
3. **CBM does not fire in cascade_judge** (empty `qualified_name` through the `list[str]` pool seam). The
   `[proxy]` baseline was CodeWiki-only too, so it's apples-to-apples — but don't attribute any lift to CBM.
4. **Isolated ≠ judge** for cascade_judge (§4). Read **as-run** for the judged number.
5. **Regime mismatch:** the `[proxy]` win was **functional**; GEI is **crash-heavy**. Judge the promotion on the
   `by_bug_kind` split, not the pooled number (which is dominated by crash mix). If GEI has too few functional
   cases, that split is underpowered — note it, and consider mining a functional-GEI subset.
6. **Off ext4** for the atlas sqlite + runs; source `.env`; never commit/echo GEI paths or creds.

---

## 7. Optional — match-independent isolated-WITH-judge read (apples-to-apples with `[proxy]`)

`gloop grade-run`'s isolated pass is judge-less. To reproduce the `[proxy]` metric (isolated on the oracle repo,
WITH the judge) on GEI — removing match contamination from the as-run number — adapt the `[proxy]` harness
`scratchpad/localize_ab.py`: it hard-codes `WIKI_REPOS` (the 6 OSS repos) as a case filter; replace that filter
with the GEI repo set (or drop it) and point `--datasets $GEI_DATASET --atlas-db $GEI_ATLAS --registry <GEI
registry> --repos $GEI_REPOS --arms rerank_cw_judge,cascade_judge`. This gives the direct file@1 comparison at
the localize ceiling. Treat it as supplementary; the **as-run** grade-run number is the production truth.
