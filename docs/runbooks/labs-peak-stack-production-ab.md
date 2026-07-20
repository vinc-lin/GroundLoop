# Runbook — `[production]` GEI A/B for the labs peak stack (`routing` + `cascade_judge`)

**Purpose:** decide whether the two best-measured experimental arms — `routing` (match) and `cascade_judge`
(localize) — earn **Candidate → Core** as the *production* `gloop run` defaults. Today they are the **labs**
defaults (`--profile labs` / `KLOOP_LABS=1`: `routing` + `cascade_judge` + `plan`), which is a
*defaults-not-validation* change — **the labs switch does not validate anything** (`docs/capabilities.md` §3
Labs-switch row). Both arms are `[proxy]`-strong (routing 0.94; cascade_judge file@1 0.245 / file@5 0.469) but
**neither has a `[production]` read**, and the proxy systematically flatters — the canonical case is the
functional arm at **0.68 `[proxy]` → 0.10 `[production]`** (`docs/environments.md`). This runbook is the read
that resolves it.

**Owner:** you (production env). GEI/406 data is **production-only** — the orchestrator (Claude) cannot reach it.

**Scope:** the whole loop as **one integrated process** (match → localize → fix), graded per stage on the same
cases. `routing` and `cascade_judge` are promoted **independently** (§5): the integrated run measures both at
once, but each stage's default flips only on its own stage's evidence. For the localize-specific prerequisites
and caveats (doc-units gate, isolated≠judge, `--repos` source, `by_bug_kind` split) this runbook **defers to
`docs/runbooks/cascade-judge-production-gate.md`** — read it alongside this one; it supersedes that runbook's
"match arm fixed = component" framing by also varying the match arm.

---

## 0. The decisions this answers

Graded by `gloop grade-run` on GEI, comparing the **labs** stack against the **core** default stack:

1. **`routing` → Core match default** iff its GEI **match recall@1 / recall@3** beats `component` (the current
   Core\* default, ~0.50 / 0.90 `[production]`) on real data, **and** the downstream stages do not regress
   because of a worse match (localize/fix are gated on the matched repo).
2. **`cascade_judge` → Core localize default** iff its GEI **as-run localize file@1** beats `atlas_rerank` (the
   current Provisional-Core default) — **overall AND on the crash split** (GEI is crash-heavy; the judge must not
   hurt the regime where FTS code-tokens already localize well). This is the same gate as
   `cascade-judge-production-gate.md` §0.
3. **Cost / latency per case** is acceptable for the production loop (both arms add LLM-judge / routing spend).

An arm that wins **only on the proxy** (loses on GEI) stays a **reachable Candidate + labs default**, and the
`[production]` null is logged honestly (as the `dispatch` arm's `0/10` null was). Winning the labs-default slot
is **not** promotion; only this read is.

---

## 1. Prerequisites — verify BEFORE running

Set once (never echo secrets/URLs/GEI paths):
```bash
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a          # KLOOP_EMBED_BASE_URL (bge-m3), KLOOP_PRODUCE_API_KEY (gateway), KLOOP_REGISTRY
export GEI_DATASET=...            # GEI case dirs (ticket.json + _oracle/oracle.json)
export GEI_ATLAS=...              # the 19-repo production atlas.db (on ext4)
export GEI_CATALOG=...            # catalog.json of GEI repo names
export GEI_REPOS=...              # clone root: <root>/<repo>/<file> must resolve  (REQUIRED — judge source + fix grading)
export GEI_AFFINITY=...           # mined component_affinity.json (the core match baseline needs it) — see step 1
export WORK=/var/tmp/labsab; export RUNS=$WORK/runs; export CARDS=$WORK/cards
mkdir -p "$RUNS" "$CARDS"         # keep everything off v9fs — /var/tmp, /home/vinc, or /dev/shm
```

**Hard prerequisites (a failure here invalidates the read):**

1. **The core baseline needs a mined affinity artifact.** `component` degrades *loudly* to `flood` (~0.10) with
   no `--affinity`/`KLOOP_AFFINITY` — a baseline run without it measures flood, not the real 0.50 core, and the
   routing comparison would be unfair. Mine it first (step 1) and confirm the baseline run records
   `match_arm=component` (not `flood`) in its `manifest.json`.
2. **`--repos` resolves to real source** (both stacks): the `cascade_judge` judge reads source via
   `$GEI_REPOS/<repo>/<file>`, and fix grading needs the checked-out worktrees. `test -f
   "$GEI_REPOS/<repo>/<known/File.kt>" && echo OK`.
3. **The localize prerequisites in `cascade-judge-production-gate.md` §1** all apply to the labs stack's localize
   side — **doc units** (`SELECT COUNT(*) FROM units WHERE kind='doc'` > 0, else source-only judge ≠ the `[proxy]`
   0.245), **bge-m3 vectors** (the cascade semantic tier), **`bug_kind` on the oracle** (`gloop label-bugkind`
   if absent), and `KLOOP_REGISTRY` (the CodeWiki doc→source bridge). Verify them there; do not duplicate here.
4. **`routing` needs no embedder** and no artifact (it is `FaultRoutingIndex` + `FaultSignalExtractor`), so the
   labs match side has no extra gate — but it is **crash-signal-driven**: on prose/functional tickets with no
   crash log it has little to route on (that is the regime where the proxy flattered). The `by_bug_kind` split
   (§4) is what tells you whether routing's `[proxy]` 0.94 was crash-only.
5. **Off ext4, gateway reachable:** `gloop doctor --atlas-db "$GEI_ATLAS"`; confirm `KLOOP_PRODUCE_API_KEY` set.

---

## 1b. Mine the core baseline's affinity artifact
```bash
gloop mine-affinity --dataset "$GEI_DATASET" --out "$GEI_AFFINITY"
```
(Uses `ticket.json` component + `_oracle` owner. For a leak-free number the offline `funceval` path uses `--loo`;
the `gloop run` path here consumes the mined artifact as the production loop would.)

---

## 2. The two runs — core default stack vs labs peak stack

Same dataset / atlas / repos throughout; the **only** difference is the profile (which flips *both* default arms).

```bash
# CORE default stack: component (match) + atlas_rerank (localize) + plan (fix)
gloop run --dataset "$GEI_DATASET" --catalog "$GEI_CATALOG" --index-db "$GEI_ATLAS" \
          --repos "$GEI_REPOS" --work "$WORK/core.work" --changes "$WORK/core.changes" \
          --out "$RUNS/core" --affinity "$GEI_AFFINITY" --fixer plan
#   ^ no --profile / KLOOP_LABS -> the core production defaults

# LABS peak stack: routing (match) + cascade_judge (localize) + plan (fix)
KLOOP_LABS=1 \
gloop run --dataset "$GEI_DATASET" --catalog "$GEI_CATALOG" --index-db "$GEI_ATLAS" \
          --repos "$GEI_REPOS" --work "$WORK/labs.work" --changes "$WORK/labs.changes" \
          --out "$RUNS/labs" --fixer plan
#   ^ KLOOP_LABS=1 fills the None-default arms with routing + cascade_judge; --affinity is ignored by routing
```
Notes: to isolate ONE arm's effect, override the other back to its core default, e.g. labs match only:
`KLOOP_LABS=1 ... --localize atlas_rerank` (routing + atlas_rerank + plan); labs localize only:
`--match-arm component --affinity "$GEI_AFFINITY"` with `KLOOP_LABS=1` (component + cascade_judge + plan). Run
these two extra arms if the integrated diff is ambiguous about which stage moved the number. The manifest records
`profile` + the arm that actually ran, so a labs run can never be misread as a core production run.

---

## 3. Grade + compare (per-stage, as-run + isolated)

```bash
gloop grade-run --runs "$RUNS/core" --dataset "$GEI_DATASET" --index-db "$GEI_ATLAS" \
                --out "$CARDS/core.json"
gloop grade-run --runs "$RUNS/labs" --dataset "$GEI_DATASET" --index-db "$GEI_ATLAS" \
                --out "$CARDS/labs.json" --compare "$CARDS/core.json"
```
`--index-db` enables the **isolated-localize** diagnostic (re-runs `retrieve` on the oracle repo — a localize
ceiling independent of match error). `--compare` appends a per-stage `improved`/`flat`/`regressed` `verdict`
(driven by the quality metrics, never cost), the per-case `regressions` list (cases that fell from a hit), and a
**total**-cost delta (`cost` — divide by |cases| for $/case). A `.md` twin is written beside each card.

---

## 4. Read the scorecard — which numbers decide

Open `$CARDS/labs.json` (+ `.md`) and the `--compare` section:

- **`match.recall@{1,3}`** — the `routing` decision (§0.1). Compare labs vs core overall **and** on
  `by_bug_kind.{crash,functional}` — routing's `[proxy]` 0.94 was crash-heavy; confirm it holds (or at least does
  not regress) on the functional split where the proxy flattered before.
- **`localize.as_run.file@1`** overall + **`by_bug_kind.crash.localize.as_run.file@1`** — the `cascade_judge`
  decision (§0.2). **Read as-run, not isolated** — the isolated pass is judge-less for `cascade_judge` (it
  reconstructs as `cascade_judge(no-judge:cascade-pool)` = the pool recall ceiling, not the judged number). See
  `cascade-judge-production-gate.md` §4.
- **`fix.resolved_rate_strict.value` / `fix.fabrication_rate`** (the `--compare` section names it `fix.resolved_rate`) — not a stage being promoted here (`plan` is unchanged), but watch it:
  a *worse* match/localize should not silently drag fix down, and a worse fix number under labs is evidence that
  the upstream arms hurt the downstream stage (the integrated point).
- The **`--compare` regression section** — the honest per-stage verdict + per-case `regressions` + total-cost delta.

---

## 5. Promotion decisions (independent per arm)

| Arm | Promote to Core default iff | On promotion |
|---|---|---|
| **`routing`** (match) | GEI `match.recall@1` **> `component`** overall **and** no functional-split collapse, and downstream localize/fix not regressed by match, cost acceptable | flip core match default `component → routing` in `_resolve_arms` (composition root, no `core/` edit); `capabilities.md` Candidate → Core\*; log `[production]` in `results-log.md` |
| **`cascade_judge`** (localize) | GEI `localize.as_run.file@1` **> `atlas_rerank`** overall **AND ≥ on the crash split**, functional not regressed vs `rerank`, cost acceptable (= `cascade-judge-production-gate.md` §5) | flip core localize default `atlas_rerank → cascade_judge`; `capabilities.md` Candidate → Provisional-Core/Core; log `[production]` |

A win on **only one** arm promotes only that one; the other stays the labs default + reachable Candidate. A
proxy-only win (GEI loss) → **do not promote**, keep as labs default + Candidate, and **log the `[production]`
null** with a one-line RCA (most likely: the arm's `[proxy]` win was regime-specific — routing to crash, the
judge to functional prose — and GEI's mix differs). Whatever the outcome, **tag every number `[production]`**,
append a dated `results-log.md` section + a `STATUS.md` entry, and update the `capabilities.md` registry + the
`workflows.md` per-stage map to match the new state.

---

## 6. Gotchas

1. **The labs default is not validation.** Making `routing`/`cascade_judge` the labs default (this change) did
   **not** promote them; they stay Candidate until *this* read. Do not cite the labs default as evidence.
2. **Fair core baseline** needs the mined affinity artifact (prereq #1) — a flood baseline understates core and
   flatters routing.
3. **Attribute the delta to a stage.** The integrated diff can move because match changed the repo *or* localize
   changed the file list. If ambiguous, run the two single-arm overrides in §2 to separate them.
4. **Regime split, not the pooled number** (routing = crash; the judge's `[proxy]` win = functional). Judge both
   on `by_bug_kind`. If a split is underpowered on GEI, say so; consider mining a larger slice for that class.
5. **Off ext4** for the atlas sqlite + runs; source `.env`; never commit/echo GEI paths or creds.
