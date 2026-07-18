# KB Playbook Redesign — Design (Cycle 2)

> **Date:** 2026-07-19 · **Status:** design deliverable (Cycle 2 of the first-principles review's Phase-2 menu,
> item #6 — the "ceiling bet"). Feeds an implementation plan next.
> **Provenance:** the first-principles review (`docs/superpowers/specs/2026-07-18-first-principles-review.md` §7)
> relabeled the dev-experience KB **Dormant** — concept valuable (the productization of charter §7's +40–60pp
> cross-repo lever), current implementation weak/0-signal. This redesign rebuilds the machinery along three
> axes and wires it into `gloop run`. **Efficacy is explicitly production-gated** (see §9); the bar for this
> cycle is *unit-proven, wired, and hermetically testable*, not a measured lift.

## 1. The problem this fixes

The current KB (grounded map, 2026-07-18) is a fully-built but **empty, eval-only** distillation lane:
`knowledge.json` does not exist, `render_knowledge([]) == ""`, and **`gloop run` (production) is entirely
KB-blind** — the KB only executes under `gloop fixeval`/`kb-ab`. Its three weaknesses:

1. **Injection** — historically a firehose (raw Skills into the localize query cost Δ−0.10 file@1; wholesale
   `guidance` into the planner hurt 0.51→0.22). *Partly already mitigated for `Knowledge`* (fix-prompt-only,
   atomic bullets) — the remaining gap is a **bounded, relevance-ranked retriever** and **production wiring**.
2. **Representation** — the lane deliberately **shreds** rich crash-RCA playbooks into atomic single-claim
   shards, and shards are exactly what validated **0/60**. The unit should keep the RCA coherent.
3. **Learning** — nothing mints new knowledge from the loop's own fixes; the feedstock is hand-authored and
   static. There is no `fix → knowledge → better next fix` loop.

## 2. Goal & non-goals

**Goal (this cycle):** build the redesigned machinery — a **bounded retriever**, a **Structured RCA record**
representation, and a **two-signal learning loop** — and **wire it into `gloop run`'s fix path**, all with
`groundloop/core/` and the atlas SQLite schema at **zero-diff**, unit-proven on the hermetic Type-1 surface.

**Non-goals (explicitly deferred / production-gated):**
- A *measured* `resolved_rate` lift from injecting playbooks (unmeasurable on the dev box — synth floors
  resolution at 0; §9).
- The **production-acceptance** mint/promote signal — a forward dependency on the live Gerrit/JIRA bind that
  is still mocked (§6, §9).
- Multi-domain playbooks; a non-AAOS crash taxonomy (YAGNI).

## 3. The unit — `KnowledgePlaybook`

Reshapes today's atomic `Knowledge` (`groundloop/kb/knowledge.py`) into one typed record per crash class:

```python
@dataclass(frozen=True)
class KnowledgePlaybook:
    id: str
    applies_when: dict                 # a [skill.match]-style predicate (compile_predicate) — WHEN it fires
    signature: str                     # the crash fingerprint (prose; ungrounded, but names grounded symbols)
    localize: tuple[str, ...]          # where to look (file/symbol hints)
    fix: tuple[str, ...]               # ordered fix steps
    required_apis: tuple[str, ...]     # APIs the fix uses
    grounding_refs: tuple[str, ...]    # every code entity the record names — each MUST resolve in the atlas
    tier: str                          # "candidate" | "validated" | "canonical" | "retired"
    provenance: str                    # source: a feedstock Skill id, or "minted:<ticket_id>"
    evidence: dict = field(default_factory=dict)   # {measured_lift, wilson95, validating_case_ids, fail_count}
```

- **Coherence:** one crash class = one record (fixes the 0/60 atomization). The RCA triple
  (signature/localize/fix) + APIs travels and is governed as a unit.
- **Grounding (oracle-blind):** every symbol named in `localize`/`fix`/`required_apis`/`grounding_refs` must
  resolve in the atlas — reuse `kb/knowledge_ground.check_knowledge_grounded` + `atlas_resolver`
  (`Store.keyword_search` recall → whole-identifier regex post-filter), applied **per field**. Grounding
  proves **existence, never ownership** (leak-safe: no `FLEET_OWNER_TOKENS`), so the gate stays oracle-blind.
  `signature` prose is not grounded; the symbols it references are.
- **Tier ladder:** `candidate → applied → validated → canonical` (+`retired` sink), via
  `kb/lifecycle.py` (hysteresis=2). *(Note: reconcile the stale `knowledge.py` docstring tier list with
  `lifecycle.TIERS` during migration.)*

## 4. Axis 1 — the bounded retriever (using a playbook)

`PlaybookRegistry.select(ctx, tier_floor) -> list[KnowledgePlaybook]` (evolves `kb/registry.py`):
1. **Filter:** the declarative `applies_when` predicate (`skills/predicate.compile_predicate`) selects the
   firing set for a ticket, oracle-blind, off `build_ctx(signals, ticket, repo)` (structured signals + a
   lowercased text haystack over summary/description/logs).
2. **Rank:** rerank the firing set by relevance to the ticket (the existing optional bge-m3 rerank over
   `signature`; falls back to predicate-order when no embedder).
3. **Bound:** take **top-k = 2** (default `KLOOP_KB_TOPK`, config surface) under a hard token budget; drop the
   rest. This is the "retriever, not firehose."
4. **Render:** `render_playbooks(selected)` → one compact structured block per playbook (headed
   `# Crash playbook: <id>` / `Signature:` / `Look at:` / `Fix:` / `APIs:`), whitespace-collapsed so a
   multi-line field can't smuggle a `##` header (as `render.py` already guards).

**`tier_floor`:** `validated` in production, `candidate` in eval — mirrors the current `_load_knowledge`
(`cli/__init__.py`) `none|candidate|validated` mapping.

## 5. Axis 3 — the two-signal learning loop

### 5a. Mint (in-loop, oracle-blind) — create a `candidate`
`mint_playbook(run_record, signals, ...) -> KnowledgePlaybook | None`:
- **Trigger:** the proposed patch **applies cleanly** (`patch_applies`, computed oracle-blind against the
  materialized worktree — already available in `run/batch.py` and `fixeval`). No oracle read.
- **Extraction (from the loop's own artifacts, all oracle-free):** `signals` → `signature` + `applies_when`;
  `locations` → `localize`; the patch's touched symbols → `fix`; the APIs the patch **actually invokes**
  (parsed from the diff — NOT the oracle's `required_apis`, which the loop may not read) → `required_apis`;
  all named symbols → `grounding_refs`.
- **Ground:** run the per-field ground-check; if any ref fails to resolve, **drop the mint** (never store an
  ungrounded playbook).
- **Dedupe by crash-class:** the record `id` is derived from the crash-class fingerprint (predicate +
  signature signals), so re-seeing the same class **merges/updates** rather than duplicating (idempotent
  `store.setdefault`, as `extract.py` already does). A flood of same-class clean fixes yields one candidate,
  not many.
- **Admit** at `tier="candidate"`, `provenance="minted:<ticket_id>"`.

### 5b. Promote (offline, oracle permitted) — `candidate → validated`
Reuse the retain-loop (`kb/attribute.py`), adapted from per-atom to **per-playbook**:
- **Screen (oracle-blind):** correlational `screen_lift` over the plan archive (`fired_knowledge`).
- **LOFO (leave-one-playbook-out):** `Δ = baseline − run_fn(full − {playbook})`; positive ⇒ load-bearing.
- **Placebo:** each candidate vs a length-matched irrelevant twin (`kb/knowledge_placebo.py`), same firing set.
- **Gate:** `accept_grounded` (`fixeval/compare.py`) — `pos_ok = Δresolved_rate_strict>0` (the just-corrected
  default, `attribute.py:146`), `honesty_ok = Δfabrication≤0 ∧ Δgroundedness≥0`. Clears → promote via
  `lifecycle.apply_verdict`; repeated fails at the bottom rung → `retired`.
- This pass runs **offline** (`gloop kb-attribute`, reading `load_eval_oracle`) — the oracle is legitimately
  available there; it is **not** the loop. In production, promotion will *also* be driven by real
  merge-acceptance once the live bind exists (§6).

## 6. Wiring into `gloop run` (frozen-core-safe)

`run_ticket` is **frozen** and calls `fixer.propose(worktree, ticket, locations)` — the fixer receives the
`ticket` but not the extracted `signals`. Injection is therefore **not** a `run_ticket` edit; it is a
**composition-root decorator**:

```
KnowledgeInjectingFixEngine(inner_fixer, registry, extractor, tier_floor="validated")
    .propose(worktree, ticket, locations):
        signals   = extractor.extract(ticket.logs, ticket)          # re-derive ctx (cheap; ticket carries logs)
        ctx       = build_ctx(signals, ticket, repo)                # repo from the worktree/chosen ref (§11)
        selected  = registry.select(ctx, tier_floor)                # validated-floor, top-k=2
        preamble  = render_playbooks(selected)
        return (inner_fixer.with_preamble(preamble) if preamble else inner_fixer).propose(worktree, ticket, locations)
```

- Satisfies the `FixEngine` port; composed at `cli/__init__.py`'s `run` handler when a playbook store is
  configured. `core/` + atlas schema **zero-diff**. `fixeval` keeps its existing in-runner selection, so eval
  and production share the same `PlaybookRegistry` + `render_playbooks`.
- **Minting hook:** the batch driver (`run/batch.py`) calls `mint_playbook(...)` after each case when
  `patch_applies` and a mint store is configured — oracle-blind, off the run-record it already builds.
- **Opt-in / fail-closed:** injection and minting are enabled by explicit config (a store path + tier);
  absent config, `gloop run` is byte-identical to today (KB-blind). Never a silent default until a
  `[production]` read (governance below).

## 7. Fail-safe & invariants

**Injecting a playbook cannot cause a bad fix** — three independent guards:
1. **Grounding** — every injected symbol provably exists in the atlas (no fabricated references).
2. **`validated`-only in production** — only resolution-proven playbooks inject; `candidate`s are quarantined.
3. **Bug Plan Mode** — the production fixer (`PlanningFixEngine`) keeps its in-world gate: it re-checks the
   executed diff against the localized scope and **abstains rather than fabricate**. A playbook can *inform*
   the plan; it cannot force an out-of-scope or ungrounded patch.

**Fixed invariants preserved:** oracle-blindness (mint is in-loop/blind; grounding is existence-only;
promotion's oracle read is the *offline* pass, never the loop) · anti-leak (grounding never reads owner
tokens) · deterministic control flow (`run_ticket` untouched; the decorator is deterministic Python).

## 8. Seeding & migration

- **Seed:** parse the **12 feedstock playbooks** (`groundloop/kb/data/aaos_kb_seed.toml` — each already has
  `Signature:`/`Localize:`/`Fix:`+`hint_apis`+a `[skill.match]` predicate) into `KnowledgePlaybook` records at
  `tier="candidate"`, grounding each. **Extraction is parse-and-ground, not LLM-shred.** The store starts
  populated with 12 candidates; none inject in production until promoted to `validated`.
- **Migrate:** reshape `Knowledge`→`KnowledgePlaybook` (`kb/knowledge.py`); `render_knowledge`→
  `render_playbooks` (`kb/render.py`); `kb/extract.py` → the feedstock parser (LLM decomposition path retired);
  `kb/attribute.py` LOFO → per-playbook; add `mint_playbook` (`kb/mint.py`, new) + the
  `KnowledgeInjectingFixEngine` decorator (`adapters/fix/knowledge_inject.py`, new) + the batch mint hook.
  `kb/ab.py` retargets to playbooks. Retire the atomic-claim taxonomy (`type ∈ {localize_hint, fix_step,
  api_requirement}` on a single `content`).
- **Governance:** the KB moves **Dormant → Candidate** (active, wired, run-reachable, opt-in) — record in
  `capabilities.md`. It is **not** a default (that needs a `[production]` read).

## 9. What's built vs deferred

- **Built + unit-proven + wired (this cycle):** the record + per-field grounding · the bounded retriever
  (k=2) · `mint_playbook` (applies-triggered, dedup-by-class, grounded) · per-playbook retain-loop · the
  `gloop run` decorator + batch mint hook · the 12-playbook seed.
- **Hermetically testable now (Type-1, no oracle/network):** mint fires on a canned clean-applying fix and
  produces a grounded candidate; a fabricated ref is rejected; the retriever selects top-2 by predicate;
  the decorator injects into a fake fixer via `with_preamble`; an empty store ⇒ `gloop run` byte-identical.
- **Production-gated (deferred):** *does injecting `validated` playbooks raise `resolved_rate`* — the
  scheduled `[production]` A/B (KB-on vs KB-off on real AAOS crash+fix tickets). The **production-acceptance**
  mint/promote signal awaits the live Gerrit/JIRA bind.

## 10. Module touch-map (feeds the plan)

| Module | Change |
|---|---|
| `groundloop/kb/knowledge.py` | `Knowledge` → `KnowledgePlaybook` (multi-field record + store I/O) |
| `groundloop/kb/render.py` | `render_knowledge` → `render_playbooks` (compact block per playbook) |
| `groundloop/kb/registry.py` | `PlaybookRegistry.select` — predicate filter → bge-m3 rerank → top-k=2 |
| `groundloop/kb/mint.py` *(new)* | `mint_playbook` — applies-trigger, extract, ground, dedupe-by-class |
| `groundloop/kb/extract.py` | LLM-shred retired → feedstock **parser** (`Signature/Localize/Fix` → record) |
| `groundloop/kb/attribute.py` | LOFO/placebo/promote adapted **per-playbook** |
| `groundloop/kb/ab.py` | retarget arms to playbooks |
| `groundloop/adapters/fix/knowledge_inject.py` *(new)* | `KnowledgeInjectingFixEngine` decorator (FixEngine port) |
| `groundloop/run/batch.py` | mint hook after each clean-applying case (opt-in) |
| `groundloop/cli/__init__.py` | compose the decorator + mint store in the `run` handler; `--kb-*` flags |
| `docs/capabilities.md` | KB Dormant → Candidate (active, wired, opt-in, `[production]`-gated) |
| `groundloop/core/**`, atlas schema | **zero-diff** |

## 11. Open questions for the plan

- Exact `mint_playbook` extraction of `fix` steps from a diff (touched-symbol list vs a bounded LLM summary of
  the hunk — the former stays fully grounded/deterministic; prefer it, LLM only if needed).
- The crash-class fingerprint used for the dedupe `id` (predicate hash + top signal tokens).
- `--kb-*` CLI surface + config keys (`KLOOP_KB_STORE`, `KLOOP_KB_TOPK`, tier floor).
- Whether the decorator re-extracts signals or receives a cached `Signals` via a composition-root sidecar
  (re-extract is simplest and frozen-core-safe; confirm cost is negligible).
