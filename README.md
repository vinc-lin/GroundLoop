# GroundLoop

**A code-driven, model-portable pipeline + benchmark for automated bug-fixing across a large fleet of
Android Automotive (AAOS) in-vehicle repositories.**

GroundLoop closes the loop from a **JIRA defect ticket + failure logs → a code fix across 130+ repos**, with
a traceable JIRA↔commit chain. Its first and hardest job is **ticket→repo matching**: given ticket text and
log signals (exception stacks, class/method/package names, `.so` names), decide *which repo among many owns
the defect* — then localize, fix, and bind the change back to the ticket.

> **Core principle — “grounding over narrative”:** trust only what reality verifies (real matches over a real
> index, deterministic control flow, passing checks); distrust unverifiable LLM prose. A Python orchestrator
> owns control flow, and **the loop never sees the oracle** — grading is a separate offline pass.

Status: **293 tests passing** · Stage-1 match recall@1 **0.60** (signal-rich logs) · localize file_recall
**0.85@1** given the right repo. See [`docs/2026-07-06-first-evaluation.md`](docs/2026-07-06-first-evaluation.md)
for the honest, full scorecard.

---

## How it works

A deterministic 8-stage closed loop (`groundloop/core/workflow.py::run_ticket`):

```
JIRA ticket + failure logs
   │
   ▼
 intake → extract(signals) → MATCH(ticket→repo) → materialize → LOCALIZE(files) → FIX(patch) → submit → bind
                                    ▲                                                                    │
                            the core objective                                        JIRA ↔ commit chain
```

The owning repo is a **predicted output + hidden-oracle field, never a loop input**. A full stage-by-stage
walkthrough with real examples is in **[`docs/workflow.md`](docs/workflow.md)**.

## Results (honest)

| Stage | Metric | Number | Notes |
|---|---|---|---|
| **Match** (Stage-1) | recall@1 | **0.60** (synth logs) / 0.02–0.23 (real logs) | the measured capability + current bottleneck; size-bias favors large repos |
| **Localize** | file_recall@1 / @5 | **0.85 / 0.94** (given the right repo) | strong; not yet scored by the standard harness |
| **Fix** | resolved_rate (proxy) | wired, **gated** | real `ModelPatchEngine`; live A/B needs the gateway + fleet repos |
| **Cost** | $/ticket | **~$0** for match+localize | pure FTS5, no LLM |

The 0.60 headline is on *synthesized* signal-rich logs; real mined prose logs are much harder (0.02 membership,
0.23 semantic). We report both — see the [first evaluation](docs/2026-07-06-first-evaluation.md).

## Architecture

Hexagonal **ports & adapters**:

- **`groundloop/core/`** — **FROZEN**, domain-agnostic: types, the 7 ports (Protocols), and the `run_ticket`
  control plane. Never edited for a feature.
- **`groundloop/adapters/`** — port implementations: hermetic `mock/` substrate + real `index/` (`AtlasIndex`
  FTS5 + `SemanticAtlasIndex` bge-m3), `fix/` (`ModelPatchEngine`), `model/` (`GatewayModel`), `skills/`.
- **`groundloop/engines/`** — migrated as-is: `atlas/` (index store/embed/retrieve), `lore/` (CBM), `produce/`
  (CodeWiki).
- **`groundloop/domains/android_ivi/`** — the domain pack (fleet catalog, `AndroidSignalExtractor`).
- **Type-2 stack** — `eval/` (match benchmark), `fixeval/` (fix-loop benchmark), `mine/` (issue→PR miner),
  `synth/` (failure-log synthesis), `skills/`+`kb/` (dev-experience KB), `build/`, `grade/`.

Behavior is swapped **only at the composition root** (`groundloop/cli/__init__.py`), never in `core/`.

## Quick start

Requires Python **3.12** and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:vinc-lin/GroundLoop.git && cd GroundLoop
uv sync --extra dev --extra produce        # base deps + pytest/ruff + CodeWiki produce (build/dev extra)

# Hermetic verification — no network, no LLM, no atlas needed:
.venv/bin/python -m pytest -q              # 293 passed
.venv/bin/ruff check groundloop tests
.venv/bin/gloop --help                     # run, index, doctor, produce, build-atlas, mine, eval, fixeval, compare
```

To build the index/oracle and run the benchmark against real data, follow the
**[Deployment & Migration User Guide](docs/user-guide.md)**.

CLI commands:
```
gloop run        # one ticket end-to-end (intake→bind)
gloop index      # build the atlas (fleet index) from a registry
gloop mine       # harvest issue→merged-PR cases + hidden oracle (needs `gh` auth)
gloop eval       # Stage-1 match benchmark → scorecard + per-case predictions
gloop fixeval    # downstream fix-loop benchmark (--skills none|mock|kb|placebo)
gloop compare    # two-sided Δ between two fix scorecards
gloop doctor     # readiness check (atlas.db, embed gateway, CBM)
```

## Repository layout

```
groundloop/
  core/        FROZEN control plane + ports (never edit for a feature)
  adapters/    mock + real port implementations (index, fix, model, skills, estate)
  engines/     migrated: atlas (index), lore (CBM), produce (CodeWiki)
  domains/     android_ivi domain pack (signal extractor, fleet, owner tokens)
  eval/        Stage-1 match eval harness + scorecard
  fixeval/     downstream fix-loop eval + compare
  mine/        GitHub issue→PR miner (positives + typed honest-refusal negatives)
  synth/       AAOS failure-log synthesis
  skills/ kb/  dev-experience KB primitive + leak-safe feedstock corpus
  build/ grade/ config/  atlas build, offline grader, KLOOP_* settings
tests/         Type-1 hermetic + gated Type-2 live tests
docs/          single source of truth (see below)
```

## Documentation

`docs/` is the single source of truth:

- **[charter.md](docs/charter.md)** — mission, requirements, the four stages, metrics, glossary.
- **[architecture.md](docs/architecture.md)** — hexagonal ports & adapters, the control plane.
- **[workflow.md](docs/workflow.md)** — how the loop works, stage by stage, with examples.
- **[user-guide.md](docs/user-guide.md)** — setup, building the oracle, and per-stage deployment for a real environment.
- **[type2-evaluation.md](docs/type2-evaluation.md)** — the canonical evaluation (dataset, arms, scorecard).
- **[2026-07-06-first-evaluation.md](docs/2026-07-06-first-evaluation.md)** — first cross-stage evaluation with real numbers.
- **[roadmap.md](docs/roadmap.md)** · **[downstream-fix-loop.md](docs/downstream-fix-loop.md)** · **[engines.md](docs/engines.md)** · **[skill-kb-migration.md](docs/skill-kb-migration.md)**
- Ops: **[m1-index-build.md](docs/m1-index-build.md)** · **[type2-eval-setup.md](docs/type2-eval-setup.md)** · **[type2-atlas-build-findings.md](docs/type2-atlas-build-findings.md)**

## Testing

Two surfaces (see [`docs/groundloop-testing-strategy.md`](docs/groundloop-testing-strategy.md)):

- **Type-1 (hermetic)** — no network / no real LLM; runs on every change (`pytest -q`).
- **Type-2 (live eval)** — real models + a real `atlas.db`; `skipif`-gated on `KLOOP_*` env. Setup in
  [`docs/type2-eval-setup.md`](docs/type2-eval-setup.md).

## What’s built vs. seams

Match, localize, and the fix engine are built and measured. To run against **production** JIRA/Gerrit you must
still implement a real `IssueSource` (JIRA) and `ChangeSink` (Gerrit/PR) adapter and wire a live fleet estate —
those, plus a few scaling items, are the honest open seams listed in
[user-guide §10](docs/user-guide.md#10-known-seams--limitations).

---

*GroundLoop is developed with an emphasis on grounded, reproducible evaluation — every headline number traces
to a real run over a real index. Contributions should keep `core/` frozen, the SQLite schema unchanged, and the
loop oracle-blind.*
