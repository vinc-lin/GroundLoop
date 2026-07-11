# Production Deployment, Validation & Feedback Guide

The **production side** of the two environments — see [`environments.md`](environments.md) for the dev↔production
split and the `[proxy]`/`[production]` labeling convention. This guide covers deploying, validating, and
collecting feedback on GroundLoop in the real ecarx/GEI environment: the full lifecycle from *stand it up* to
*feed production reality back into development*.

Every item is tagged **`[in place]`** (works today) or **`[to build]`** (target operating model, not yet built),
so this doc doubles as a gap list. All production numbers are `[production]` by definition.

> **Note on shape:** GroundLoop is a **batch / CLI pipeline, not a long-running service.** The "system" is
> invoked per run (`gloop run` / `gloop grade-run`); the only standing dependencies are the LiteLLM gateway and
> a reachable `atlas.db`. Read "deploy / start / stop" through that lens.

---

## Part A — Deploy & operate

### 1. Deployment requirements `[in place]` (infra) / `[to build]` (formal preflight)
Confirm all of these are available before a production run:
- **LiteLLM gateway** serving `deepseek-chat` (produce/fix), the `qwen` re-ranker (localize), and `bge-m3`
  (embeddings), with creds. The `component` match arm is **FTS-only and needs NO gateway**; `functional`/
  `semantic` arms and the `--fixer model` fix stage do.
- The real **19-repo `atlas.db`** built and reachable via `KLOOP_ATLAS_DB`, on **real ext4** (not the v9fs
  Windows mount — sqlite over a multi-GB atlas is slow there).
- **`component_affinity.json`** (mined, below) · the **JIRA↔Gerrit oracle** (per case: loop-visible
  `ticket.json.component`; offline `_oracle/oracle.json.owning_repo`).
- **`KLOOP_*`** env (the single config surface) · disk for the multi-GB atlas · `git` + `gh` access.
- Secrets: never commit keys/tokens/LAN IPs/the real `.env` (gitignored; config is env-only).

### 2. Installation & configuration `[in place]`
```bash
uv sync --extra dev                       # base deps + pytest/ruff
set -a; . ./.env; set +a                  # load gateway creds (NOT autoloaded)
gloop doctor --atlas-db $KLOOP_ATLAS_DB    # -> readiness: READY
# build the inputs (offline, zero-cost):
gloop mine-affinity --dataset $FULL_ORACLE --out component_affinity.json
gloop combine-oracle --sources $CRASH_DS $FUNCTIONAL_DS --out combined-406
```
`mine-affinity` tallies `(ticket.component → owning_repo)` over the **full** historical oracle (population
statistics, not per-ticket memory; the eval's leave-one-out removes each scored case's own contribution, so
building over the full corpus does not leak). `combine-oracle` copies (never mutates the sources), unions the
catalogs, and stamps `bug_kind` (crash|functional).
**Record the production config set** before running: atlas SHA, model pins, affinity-table version, dataset ids.

### 3. Startup / shutdown `[in place]`
No daemon. "Start" = ensure the gateway answers and the atlas is READY, then invoke a run. "Stop" = nothing to
stop (batch process exits). Sanity gate before any real run:
```bash
gloop doctor --atlas-db $KLOOP_ATLAS_DB                    # repos:N units:M ; READY
curl -s -o /dev/null -w "%{http_code}\n" "$GATEWAY/embeddings" -H "Authorization: Bearer $KEY" -d '...'  # 200
```

### 4. Deployment verification `[in place]`
After (re)building the atlas/affinity, verify before trusting a run:
- `gloop doctor` → READY (repo + unit counts as expected);
- gateway `/embeddings` + `/chat/completions` → `200`;
- a **1–2-case smoke** through `gloop run --out` → `gloop grade-run` completes and scores.
**Record** the verification result + atlas SHA + model versions + affinity version + operator + date/time.

### 5. Production usage `[in place]`
The workflow: a JIRA **ticket + failure logs** → the 8-stage `run_ticket` (intake → extract → match →
materialize → localize → fix → submit → bind) → the offline `gloop grade-run` scorecard.
- **Inputs:** `ticket.json` (summary, description, JIRA `component`, logs). The loop is **oracle-blind** — it
  never sees the owning repo.
- **Outputs:** predicted owning repo (top-1 match), localized files, a proposed patch, and a JIRA↔commit bind.
- **Known limits:** the fix stage needs the owner repo **checked out** (`--repos`), else it abstains /
  fabricates (ungradeable); CarPlay Core-vs-Integration is a near-tie; some owner files may be unindexed.

---

## Part B — Validate

### 6. Functional validation `[in place]`
The **10-case + 406-case GEI oracle**, scored offline. Two paths:
```bash
# Stage-1 match efficacy (component arm), leave-one-out (mandatory for a trustworthy number):
gloop funceval --dataset combined-406 --index-db $KLOOP_ATLAS_DB \
  --arms flood,component --affinity component_affinity.json --loo --out card-406.json
# read: attribution.arms.component.by_bug_kind.{crash,functional}  (recall@1/@3, coverage, Φ_c)

# Full per-stage self-scoring over the real loop (match/localize/fix), see §Self-scoring below:
gloop run   --dataset <ds> --catalog <cat> --index-db $KLOOP_ATLAS_DB --match-arm component \
            --affinity component_affinity.json --repos <19-repo-mirror> --fixer model --out run-N
gloop grade-run --runs run-N --dataset <ds> --index-db $KLOOP_ATLAS_DB --out card-N.json
```
**Acceptance gates `[production]`:** `component` recall@3 ≫ `flood` recall@3 (else the affinity table or
`Ticket.component` is empty/mis-joined — a data problem, not a weight problem); and functional recall@1/@3
lands near the production 406 `comp+fusion` target (**≈ 0.50 / 0.90 `[production]`**, under honest `--loo`);
`--loo` always used. *(The first 10-case run scored match recall@1 7/10 `[production]` — see
[`results-log.md`](results-log.md).)*
Per test case, `grade-run` records input/predicted/oracle/pass-fail/stage automatically (the canonical record).
Preserve failed cases (§11).

### 7. Performance validation `[in place]` (cost) / `[to build]` (latency)
Collect per request/workflow, keyed to atlas SHA + config: per-stage latency, model inference time, retrieval
time; **token usage + `$/solved`** (already emitted by fixeval — `cost_total`, `cost_per_solved`); atlas
build/query CPU + memory; timeout + error rate. **GPU-OOM / GPU utilisation is out of scope here** — inference
is gateway-side (deepseek/qwen/bge-m3 run on the gateway host, not the pipeline box). Reject a `[proxy]` or
`[production]` lift that costs too much per solved case (`--cost-budget`).

### 8. Stability validation `[to build]` (formal incident log) / `[in place]` (known traps)
Record: gateway timeouts / 5xx / `000`, atlas / ext4 I/O stalls, CBM restart-loops on huge source files,
orphaned CBM servers across sessions, the v9fs `index.lock` trap, long-running atlas builds. Per incident:
occurrence time, affected stage, impact scope, logs, recovery action, root cause. (Build-time traps + fixes are
catalogued in [`build-setup.md`](build-setup.md).)

---

## Part C — Feedback → development (the loop back to dev)

This is the reason production exists in the loop: it is the **oracle of record** and the source of the next
eval slice / regression seed / design lever. See [`environments.md`](environments.md#the-develop-against-feedback-loop).

### 9. Usage data collection `[to build]`
Count tickets processed, per-arm; completion / abstention rates (Φ_c already captures answered-vs-abstained);
active period; task category (crash|functional). **No PII** — real JIRA tickets carry customer/vehicle data;
obey the repo secret-hygiene rule (never persist keys/IPs/customer identifiers into collected data).

### 10. Quality feedback collection `[in place]` (metrics) / `[to build]` (human overlay)
Map each generic quality dimension onto a metric GroundLoop already produces:

| quality dimension | GroundLoop metric |
|---|---|
| correct (right repo) | match `recall@1` |
| hallucination | **`fabrication_rate`** (a clean-applying patch on an unanswerable case) |
| correct retrieval | `file_recall@k` (localize) |
| complete / actionable | `resolved_rate_strict` (patch touches expected files + required APIs) |
| trustworthy / honest | honest-abstention (Φ_c reward for abstaining when it can't) |

Human overlay `[to build]`: per production result, capture user **acceptance / correction / rejection** of the
predicted repo + patch, and flag missing/incorrect info, outdated knowledge, incorrect tool/execution.

### 11. Failure-case collection `[in place]` (auto record) / `[to build]` (triage store)
Every important failure is captured as the **canonical record** (below) and **preserved as a regression seed**.
This formalizes what the first 10-case run did by hand (`results-log.md` → 2026-07-11 entry): e.g. a
label≠owner disagreement (Bluetooth-tagged, fixed in the cluster repo) or a coverage gap (the oracle file not
in the atlas). Failed cases become proxy regression fixtures + design levers.

### 12. Knowledge-gap collection `[to build]`
Record: unindexed owner files (e.g. `CpAccessibilityManager.kt`) and unindexed repos (e.g.
`XCUSBMediaService`) → feed an atlas rebuild; component→owner disagreements → feed the affinity table / a
ticket-text override signal; retrieval pool-recall misses → feed per-file aggregation. Per gap: affected
workflow, frequency, impact, source, recommended correction, owner.

### 13. User feedback collection `[to build]`
Engineer-facing: satisfaction, trust in the suggested repo/patch, time saved, manual effort reduced, repeated
problems, frequently-edited patch outputs, requested functions. Tie each to a specific workflow / production case.

### 14. Development-feedback data `[to build]`
The standing process: preserve representative **success / failure / difficult / low-confidence / high-latency /
high-cost / expert-intervention** cases, review them regularly, and convert each into one of: an **eval dataset
slice**, a **regression test** (proxy fixture), a **KB / knowledge update**, a **prompt or retrieval
improvement**, **model-training data**, a **workflow improvement**, or a **roadmap requirement**. This is the
concrete mechanism that closes production back onto the dev box (`environments.md` loop).

### 15. Feedback submission format `[in place]` (schema) / `[to build]` (collection tooling)
Every failure case (§11) and feedback record (§13) uses the **canonical record**; `*` = auto-emitted by
`grade-run`:
```
record_id · date · env=[production] · reporter · stage(match|localize|fix)
ticket_id* · predicted_repo* · oracle_repo* · signals* · expected_vs_actual*
category · severity · frequency · impact · logs · root_cause · workaround
suggested_improvement · owner · target_version · status
```

### 16. Review process `[to build]`
Review production feedback on a regular cadence. Categorize each issue as: deployment · configuration ·
performance · stability · model · retrieval · knowledge · workflow · user-experience · feature-request.
High-severity → handled immediately; recurring → prioritized by **severity × frequency ÷ development-cost**
(business impact + user impact weighted).

### 17. Release tracking `[to build]`
Every production deploy records: release date, **atlas SHA**, **model pins**, **affinity-table version**,
config version, change summary, known issues, **rollback procedure** (revert to the prior atlas + affinity —
both are versioned artifacts), and the validation result. Feedback + failure cases are linked to the release
version they were observed on.

### 18. Success criteria `[in place]` (checkable) / `[to build]` (thresholds + monitoring)
A production deploy is successful when:
- the gateway + atlas are READY and the 1–2-case smoke + `grade-run` pass;
- match / localize are within the agreed thresholds **vs the last release** (no regression);
- no unresolved critical issue;
- feedback records (§11/§15) can be collected;
- rollback is possible (prior atlas + affinity retained).

---

## Leak-safety (enforced in code — do not weaken)
- **Runtime is oracle-blind:** the deployed `gloop run` reads only `Ticket.component` + the full affinity table
  (no LOO, no oracle at inference — correct for production).
- **Eval avoids train/test leak:** `--loo` (grader-side; subtracts the case's own contribution). **Never report
  the 406 number without `--loo`.**
- **Grading is a separate offline pass:** `gloop grade-run` is the sole oracle reader; the loop never sees it.

## Gated follow-ups (only if the 406 says so)
- **Unlock the crash track:** index `XCUSBMediaService` (+ other missing repos) → build the crash dataset →
  score the `routing` crash arm on real crashes (currently blocked by index coverage, not the matcher).
- **CarPlay Core-vs-Integration disambiguation:** only if the 406 shows CarPlay ambiguity is a broad problem.
- **Within-component recall@1** ceiling → a non-size-biased base (the bge-m3 functional text arm).
- **Component-arm abstention `tau`** recalibration for the RRF+affinity margin scale (recall@1/@3 unaffected).
