# Runbook — A1: cheap proof of CamelCase index tokenization (7-repo A/B)

**Purpose:** decide — cheaply, before committing to a full 19-repo GEI re-index — whether **index-time
CamelCase expansion** (`KLOOP_INDEX_CAMELCASE=1`) nets a **positive** lift across **match *and* localize** on
the Tier-1 GEI cases. This is the deferred "CamelCase-atlas read" that both the cascade-judge runbook and the
capabilities registry name as a blocker.

**The mechanism (why this is the real lever), grounded:** the FTS5 table uses the default `unicode61`
tokenizer (`store.py:63-64`, no `tokenize=`), so `CarPlayCoreService` is one opaque token. The **query side
already splits CamelCase** (`_fts_query`, `store.py:158-187`: emits `core`, `service`, …), but the **index side
does not** unless `KLOOP_INDEX_CAMELCASE` is on (`index.py:35`, `settings.index_camelcase=False` by default —
your Tier-1 atlas was built off). So the discriminating subword (`core` vs `integration`) is locked inside the
opaque compound → the CarPlay near-tie (14905/8185) falls back to size/density, and localize noise wins
(13196: `TracingSpConstant` over `ScreenshotUtils` — the query's `screenshot` can't reach the opaque token).
Turning on index expansion makes those subwords real indexed terms that discriminate — at **both** stages.

**Owner:** you (GEI box). The orchestrator cannot re-index or read GEI. **Cost:** two small **symbol-only**
7-repo builds (minutes each — no produce/CodeWiki), then 2× the Tier-1 10-case run.

---

## 0. The decision this answers

CamelCase index tokenization advances to **A2 (full 19-repo re-index)** iff, on the Tier-1 10 cases, the
CamelCase-on 7-repo atlas beats the CamelCase-off 7-repo atlas on **NET lift**:

1. **Match:** the CarPlay near-ties (14905/8185) flip toward the oracle (or at least do not regress), recall@1 up.
2. **Localize:** `file@1`/`file@5` up (noise displaced by real subword matches, e.g. 13196).
3. **Precision cost (the veto):** **no *new* match/localize errors** from subword false-hits that outweigh the
   wins. Index expansion inflates the token space → more cross-repo/cross-file collisions (`store.py:179-180`
   already drops single-char/digit subwords on the query side for exactly this reason). **The verdict is
   wins − new-errors, not wins alone.**

Carve-out: the **Bluetooth→XCClusterService** miss (13363) is a component-affinity/label error — CamelCase will
**not** fix it. Do not count it either way; it belongs to the separate affinity track.

---

## 1. Prerequisites

```bash
cd /mnt/code/GroundLoop            # your GEI checkout
set -a; . ./.env; set +a           # gateway + KLOOP_REGISTRY etc.
export GL_DATA=/home/ecarx/gl-data
export WORK=/var/tmp/cc_a1          # OFF ext4 (v9fs is slow for sqlite) — /var/tmp or /dev/shm
mkdir -p "$WORK"
```

- **A 7-repo subset registry + corpus.** The Tier-1 10 cases span 7 repos — build atlases over **just those 7**
  (small + fast). Make `cc7-atlas.toml` + its sibling `cc7-corpus.toml` (repo url+sha) listing exactly the 7
  Tier-1 repos. **Both CarPlay repos (Core *and* Integration) must be in the 7** or the near-tie can't reproduce.
- **The same `--affinity` artifact** the Tier-1 run used (the component baseline needs it, or `component`
  degrades loudly to flood and the match A/B is meaningless): `export GEI_AFFINITY=$GL_DATA/component_affinity.json`.
- **The Track-C bring-up fixes present** (nested `--repos` guard, `.git`-ignore materialize, jira UTF-8) — else a
  real `--repos` run aborts before localize. (Merged on master `9f4bd51`; rebase your box past `c51e652`.)
- `--repos /mnt/code/GEI-project/repos` resolves (same as Tier-1).

---

## 2. Build the two 7-repo atlases (the *only* variable is the tokenizer)

Identical build both times — **symbol-only** (skips produce; isolates the tokenization variable) — differing
only by the `KLOOP_INDEX_CAMELCASE` env:

```bash
# OFF baseline (matches your current 19-repo atlas's tokenization, on the 7-repo catalog)
KLOOP_INDEX_CAMELCASE=0 gloop build-atlas --registry "$WORK/cc7-atlas.toml" \
    --corpus "$WORK/cc7-corpus.toml" --symbol-only --jobs 3
mv "$(dirname "$WORK/cc7-atlas.toml")/atlas.db" "$WORK/atlas_off.db"   # or point the registry's db path per build

# ON candidate — identical build, CamelCase index expansion on
KLOOP_INDEX_CAMELCASE=1 gloop build-atlas --registry "$WORK/cc7-atlas.toml" \
    --corpus "$WORK/cc7-corpus.toml" --symbol-only --jobs 3 --force
mv "$(dirname "$WORK/cc7-atlas.toml")/atlas.db" "$WORK/atlas_on.db"
```
(Manage the two output DB paths however your registry names them — the key is two DBs, same 7 repos, same
`--symbol-only`, differing only in `KLOOP_INDEX_CAMELCASE`. Sanity check the expansion actually happened:
`sqlite3 "$WORK/atlas_on.db" "SELECT text FROM units WHERE name LIKE '%CarPlay%' LIMIT 1;"` should show the
split subwords appended; the off DB should not.)

---

## 3. Run the same 10 cases against each atlas — isolate the tokenizer

Use **`--localize atlas`** (plain FTS, **no judge**) so any localize delta is *pure tokenization*, not judge
variance — the judge (atlas_rerank/cascade_judge) layers back on the *winning* tokenization at A2. Match arm =
`component` (as Tier-1).

```bash
RUN () {   # RUN <label> <atlas-db>
  gloop run --dataset "$GL_DATA/dataset-new" --catalog "$GL_DATA/dataset-new/catalog.json" \
            --index-db "$2" --repos /mnt/code/GEI-project/repos \
            --work "$WORK/$1.work" --changes "$WORK/$1.changes" --out "$WORK/$1" \
            --affinity "$GEI_AFFINITY" --match-arm component --localize atlas --fixer plan
}
RUN off "$WORK/atlas_off.db"
RUN on  "$WORK/atlas_on.db"

GRADE () {  # GRADE <label> <atlas-db> [compare-card]
  gloop grade-run --runs "$WORK/$1" --dataset "$GL_DATA/dataset-new" --index-db "$2" \
                  --out "$WORK/$1.card.json" ${3:+--compare "$3"}
}
GRADE off "$WORK/atlas_off.db"
GRADE on  "$WORK/atlas_on.db" "$WORK/off.card.json"     # --compare surfaces newly-lost cases + the verdict
```
Note: match recall on a **7-repo** catalog is *easier* than the 19-repo Tier-1 run, so the *absolute* match
numbers are not comparable to Tier-1 — but the **off-vs-on delta on the same 7 repos is valid**, and the CarPlay
near-tie is within the 7.

---

## 4. Read — is the net lift positive?

Per-stage, off vs on (the `--compare` section on `on.card.json` gives the verdict + `regressions` list):

- **Match:** `overall.match.recall@1` on vs off; and per-case, do **14905 / 8185** flip to `CarPlayCoreService`?
- **Localize:** `overall.localize.as_run["file@1"]`/`["file@5"]` on vs off (with `--localize atlas` as-run ≈
  isolated — no judge). Does **13196** stop surfacing `TracingSpConstant`?
- **Precision (the veto):** scan the `--compare` `regressions` list and any case that was correct off but wrong
  on — those are the subword false-hits. **Net = (cases fixed) − (cases newly broken).**

n=10 caveat stands: this is a **directional** read (±0.13–0.25 per metric). A1 decides *go/no-go on the full
re-index*, not a promotion — promotion is the A2 19-repo `[production]` read.

---

## 5. Decision

| A1 outcome (net, over the 10) | Verdict |
|---|---|
| Match near-ties flip **and** localize file@1 up **and** no worse net precision | **Go to A2:** full 19-repo re-index with `KLOOP_INDEX_CAMELCASE=1`, re-validate the `[production]` floor on it, make it the new pinned atlas (update the reuse contract), then re-layer the judge (atlas_rerank/cascade_judge) on the better tokenization. |
| Wins on one stage, new errors cancel them on the other | **Refine, don't commit:** the subword-noise drop rules (min length / idf floor) need tightening before A2 — tune on the 7-repo set (cheap) first. |
| Flat or net-negative | **Do not re-index.** Record the null; the near-ties need a different lever (affinity tie-break / a discriminating judge prompt), not tokenization. |

Whatever the outcome, tag numbers `[production]` (real GEI data) and log a dated `results-log.md` entry + a
`STATUS.md` note. If Go, A2's full read is the promotable one.

---

## 6. Gotchas
1. **Both CarPlay repos in the 7** or the near-tie can't reproduce (§1).
2. **Only the tokenizer may differ** between the two builds — same repos, same `--symbol-only`, same corpus SHAs.
   Confirm the expansion landed (§2 sqlite check) before trusting a null.
3. **Precision is the veto, not an afterthought** (§0.3) — read the new-errors, not just the fixes.
4. **CamelCase ≠ the Bluetooth fix** (13363 is affinity; separate track).
5. **A2 is a full re-index** — it breaks the current atlas's reuse pin; that cost is only justified if A1 nets positive.
6. **Off ext4**, source `.env`, never commit/echo GEI paths or creds.
