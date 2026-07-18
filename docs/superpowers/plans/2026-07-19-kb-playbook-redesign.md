# KB Playbook Redesign — Implementation Plan (Cycle 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the dev-experience KB as a self-improving crash-RCA playbook system — a multi-field `KnowledgePlaybook` unit, a bounded top-k=2 retriever, a two-signal learning loop (mint on `patch_applies` → `candidate`, promote via the offline retain-loop → `validated`, inject `validated`-only), wired into `gloop run` — with `groundloop/core/` and the atlas schema at zero-diff.

**Architecture:** The current KB (`groundloop/kb/`) already has the machinery — registry, per-ref grounding, lifecycle tiers, LOFO/placebo governance, A/B — all operating on an atomic `Knowledge{id, applies_when, type, content, grounding_refs, provenance, tier, evidence}`. This plan (a) reshapes the *unit* to a multi-field RCA record (drop `type`/`content`, add `signature/localize/fix/required_apis`), (b) replaces the LLM `kb-extract` with a deterministic feedstock parser that seeds the 12 playbooks, (c) adds a `mint` step that writes a grounded candidate from a clean-applying fix (deduped by crash-class), and (d) adds a composition-root `KnowledgeInjectingFixEngine` decorator so `gloop run`'s fixer consults `validated` playbooks. Efficacy is production-gated; the bar is unit-proven + wired + hermetically testable.

**Tech Stack:** Python 3.12, `uv` `.venv`, `pytest`, `ruff` (line-length 110). Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`.

**Hard constraints:** never edit `groundloop/core/`; never alter the atlas SQLite schema (`engines/atlas/store.py`); preserve oracle-blindness (mint reads no oracle; grounding is existence-only; promotion's oracle read is the *offline* pass), anti-leak (grounding never admits owner tokens), deterministic control flow (`run_ticket` untouched — injection is a composition-root decorator). Suite green + ruff clean after every task.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `groundloop/kb/knowledge.py` | the `KnowledgePlaybook` record + JSON store I/O | reshape `Knowledge` → `KnowledgePlaybook` (multi-field), adjust `_TUPLE_FIELDS` |
| `groundloop/kb/render.py` | render selected playbooks into the fix-prompt preamble | `render_knowledge` → `render_playbooks` (one block per playbook) |
| `groundloop/kb/knowledge_ground.py` | per-field oracle-blind grounding | adapt well-formedness to the playbook shape; keep ref-resolution + leak red-test |
| `groundloop/kb/seed.py` *(new)* | deterministic feedstock parser (Skill TOML → playbook) | new: `playbook_from_skill`, `seed_to_store` |
| `groundloop/kb/extract.py` | old LLM-decompose path | **retire** (delete module + its CLI/tests) — replaced by `seed.py` |
| `groundloop/kb/registry.py` | `PlaybookRegistry.select` (predicate → rerank → top-k) | rerank over `signature`; default `top_k=2`; rename Knowledge→playbook |
| `groundloop/kb/mint.py` *(new)* | mint a candidate playbook from a clean-applying fix | new: `mint_playbook` (dedupe-by-crash-class) |
| `groundloop/kb/attribute.py` | LOFO/placebo/promote retain-loop | retarget iteration to playbooks (mostly field-name updates) |
| `groundloop/kb/ab.py` | `kb-ab` arms none/kb/placebo | retarget to playbooks |
| `groundloop/kb/knowledge_placebo.py` | length-matched decoy | adapt to the playbook shape |
| `groundloop/adapters/fix/knowledge_inject.py` *(new)* | `KnowledgeInjectingFixEngine` decorator (FixEngine port) | new |
| `groundloop/cli/__init__.py` | compose the decorator + `--kb-*` flags in the `run` handler; retire `kb-extract`, add `kb-seed` | modify |
| `groundloop/config/settings.py` | `KLOOP_KB_STORE` / `KLOOP_KB_TOPK` env surface | add 2 fields |
| `docs/capabilities.md` | KB Dormant → Candidate (active, wired, opt-in) | modify |
| `groundloop/core/**`, `engines/atlas/store.py` | **zero-diff** | — |

**Data model — the target `KnowledgePlaybook`** (used by every task; defined in Task 1):
```python
@dataclass(frozen=True)
class KnowledgePlaybook:
    id: str
    applies_when: dict                 # [skill.match]-style predicate — WHEN it fires
    signature: str                     # the crash fingerprint (prose)
    localize: tuple[str, ...]          # where to look
    fix: tuple[str, ...]               # fix steps
    required_apis: tuple[str, ...]     # APIs the fix uses
    grounding_refs: tuple[str, ...]    # every code entity named — each must resolve in the atlas
    provenance: str                    # "<skill-id>" (seed) | "minted:<ticket_id>"
    tier: str                          # candidate | applied | validated | canonical | retired
    evidence: dict = field(default_factory=dict)   # {measured_lift, wilson95, validating_case_ids, fail_count, demotions}
```

---

## Phase A — Representation, grounding, seed

### Task 1: Reshape `Knowledge` → `KnowledgePlaybook`

**Files:**
- Modify: `groundloop/kb/knowledge.py`
- Test: `tests/kb/test_knowledge.py`

- [ ] **Step 1: Write the failing round-trip test** — replace the `_knowledge()` factory + tests in `tests/kb/test_knowledge.py` to build a `KnowledgePlaybook`:
```python
from groundloop.kb.knowledge import KnowledgePlaybook, load_knowledge, save_knowledge

def _playbook() -> KnowledgePlaybook:
    return KnowledgePlaybook(
        id="fragment-view-after-destroy-npe",
        applies_when={"any_text": ["onDestroyView"], "any_errors": ["NullPointerException"]},
        signature="NPE on a view/binding; stack through Fragment.onDestroyView; a callback fires after teardown",
        localize=("onDestroyView", "retained listener/handler/coroutine fields"),
        fix=("null out the ViewBinding in onDestroyView", "cancel the async callback post-teardown"),
        required_apis=("onDestroyView", "Job.cancel"),
        grounding_refs=("onDestroyView", "Job.cancel"),
        provenance="fragment-view-after-destroy-npe",
        tier="candidate",
        evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [], "fail_count": 0, "demotions": []},
    )

def test_save_then_load_round_trips_all_fields(tmp_path):
    k = _playbook()
    p = tmp_path / "knowledge.json"
    save_knowledge(str(p), {k.id: k})
    back = load_knowledge(str(p))
    assert back == {k.id: k}
    for tf in ("localize", "fix", "required_apis", "grounding_refs"):
        assert isinstance(getattr(back[k.id], tf), tuple)   # JSON lists re-tupled for frozen equality
```
(Also update `test_missing_file_is_empty_store` — unchanged — and rewrite `test_unknown_keys_dropped_and_id_defaulted` to use the new fields.)

- [ ] **Step 2: Run it — expect FAIL** (`ImportError: cannot import name 'KnowledgePlaybook'`)

Run: `.venv/bin/python -m pytest tests/kb/test_knowledge.py -q`

- [ ] **Step 3: Implement in `groundloop/kb/knowledge.py`** — replace the `Knowledge` dataclass with `KnowledgePlaybook` (keep the module's store-I/O functions; rename `Knowledge` type references):
```python
_TUPLE_FIELDS = ("localize", "fix", "required_apis", "grounding_refs")

@dataclass(frozen=True)
class KnowledgePlaybook:
    id: str
    applies_when: dict
    signature: str
    localize: tuple[str, ...]
    fix: tuple[str, ...]
    required_apis: tuple[str, ...]
    grounding_refs: tuple[str, ...]
    provenance: str
    tier: str
    evidence: dict = field(default_factory=dict)
```
Update `_to_knowledge` → `_to_playbook` (same body, `fields(KnowledgePlaybook)`, loop over the 4 `_TUPLE_FIELDS`), and `load_knowledge`/`save_knowledge` to build/serialize `KnowledgePlaybook`. Keep `KNOWLEDGE_PATH`. Keep the function names `load_knowledge`/`save_knowledge` (many callers import them). Add a module alias `Knowledge = KnowledgePlaybook` **only if** a grep shows external importers still using `Knowledge` that you won't touch this phase — otherwise update them (Tasks 2–9 update the KB internals; check `grep -rn "import Knowledge\b\|Knowledge(" groundloop tests`).

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/kb/test_knowledge.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/kb/knowledge.py tests/kb/test_knowledge.py
git commit -m "feat(kb): reshape Knowledge -> KnowledgePlaybook (multi-field crash-RCA record)"
```

### Task 2: `render_playbooks`

**Files:**
- Modify: `groundloop/kb/render.py`
- Test: `tests/kb/test_render.py`

- [ ] **Step 1: Write the failing test** — replace `tests/kb/test_render.py`'s factory + tests:
```python
from groundloop.kb.render import render_playbooks
from groundloop.kb.knowledge import KnowledgePlaybook

def _pb(pid, **over):
    base = dict(id=pid, applies_when={"any_text": ["x"]}, signature="sig one\n## Injected\nsig two",
                localize=("look here",), fix=("do this",), required_apis=("Api.call",),
                grounding_refs=("Api.call",), provenance="p", tier="validated", evidence={})
    base.update(over)
    return KnowledgePlaybook(**base)

def test_renders_one_block_per_playbook_bounded_and_injection_safe():
    out = render_playbooks([_pb("fragment-npe")])
    assert out.startswith("\n\n# Grounded playbooks")
    assert "# Crash playbook: fragment-npe" in out
    assert "Signature: sig one ## Injected sig two" in out   # multi-line collapsed to one line
    assert "Look at: look here" in out and "Fix: do this" in out and "APIs: Api.call" in out
    assert out.count("# Grounded playbooks") == 1

def test_empty_is_empty_string():
    assert render_playbooks([]) == ""
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/kb/test_render.py -q`

- [ ] **Step 3: Implement `groundloop/kb/render.py`** — replace `render_knowledge` with `render_playbooks`:
```python
def _line(label: str, val) -> str:
    if isinstance(val, (list, tuple)):
        val = "; ".join(val)
    return f"{label}: {' '.join(str(val).split())}"          # whitespace-collapse (no header smuggling)

def render_playbooks(items) -> str:
    if not items:
        return ""
    blocks = []
    for k in items:
        lines = [f"# Crash playbook: {k.id}", _line("Signature", k.signature),
                 _line("Look at", k.localize), _line("Fix", k.fix), _line("APIs", k.required_apis)]
        blocks.append("\n".join(lines))
    return "\n\n# Grounded playbooks\n" + "\n\n".join(blocks)
```

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/kb/test_render.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/kb/render.py tests/kb/test_render.py
git commit -m "feat(kb): render_playbooks - one bounded, injection-safe block per playbook"
```

### Task 3: Adapt grounding to the playbook shape

**Files:**
- Modify: `groundloop/kb/knowledge_ground.py`
- Test: `tests/kb/test_knowledge_ground.py`

Rationale: `check_knowledge_grounded` currently validates `type ∈ _VALID_TYPES` + non-empty `content`. The playbook has no `type`/`content` — well-formedness becomes non-empty `signature` + a compilable `applies_when`; ref-resolution + leak red-test stay. `_leak_haystack` must scan the new prose fields.

- [ ] **Step 1: Update the grounding test** — in `tests/kb/test_knowledge_ground.py`, change `_knowledge(**over)` to build a `KnowledgePlaybook` (signature instead of type/content), keep the `_resolver` fake and the real-Store fixture. Add:
```python
def test_grounded_when_refs_resolve_and_wellformed():
    chk = check_knowledge_grounded(_playbook(), _resolver(["onDestroyView", "Job.cancel"]))
    assert chk.grounded is True and chk.reasons == ()

def test_ungrounded_when_a_ref_is_missing():
    chk = check_knowledge_grounded(_playbook(), _resolver(["onDestroyView"]))   # Job.cancel missing
    assert chk.grounded is False and any(r.startswith("unresolved_refs") for r in chk.reasons)

def test_empty_signature_is_not_wellformed():
    chk = check_knowledge_grounded(_playbook(signature=""), _resolver(["onDestroyView", "Job.cancel"]))
    assert chk.grounded is False and "empty_signature" in chk.reasons
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/kb/test_knowledge_ground.py -q`

- [ ] **Step 3: Implement** in `groundloop/kb/knowledge_ground.py` — in `check_knowledge_grounded`, replace the well-formedness block (the `type`/`content` checks) with:
```python
    if not (knowledge.signature or "").strip():
        reasons.append("empty_signature")
    if not (knowledge.id or "").strip():
        reasons.append("empty_id")
    if not knowledge.applies_when:
        reasons.append("empty_predicate")
    else:
        try:
            compile_predicate(knowledge.applies_when)
        except ValueError as e:
            reasons.append(f"bad_predicate:{e}")
```
Delete the `_VALID_TYPES` reference. Update `_leak_haystack` to lowercase `signature + " ".join(localize) + " ".join(fix) + " ".join(required_apis) + " ".join(grounding_refs)` + the `applies_when` values. Leave `atlas_resolver`, `_bounded`, the ref-resolution loop, and the leak red-test unchanged.

- [ ] **Step 4: Run — expect PASS** (run the whole kb ground + knowledge suite)

Run: `.venv/bin/python -m pytest tests/kb/test_knowledge_ground.py tests/kb/test_knowledge.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/kb/knowledge_ground.py tests/kb/test_knowledge_ground.py
git commit -m "feat(kb): ground-check the playbook shape (signature well-formedness; per-ref resolution + leak red-test unchanged)"
```

### Task 4: Deterministic feedstock parser + seed the 12 playbooks

**Files:**
- Create: `groundloop/kb/seed.py`
- Delete: `groundloop/kb/extract.py`, `tests/kb/test_extract.py`, `tests/kb/test_cli_kb_extract.py` (retire the LLM path)
- Test: `tests/kb/test_seed.py` (new), `tests/kb/test_feedstock.py` (keep/adjust)

Rationale: the 12 feedstock Skills' `guidance` already carries `Signature:`/`Localize:`/`Fix:` (validator-enforced, `validate.py:_REQUIRED_CLAUSES`). Parse those clauses into a `KnowledgePlaybook` — no LLM. `applies_when` = the skill's `[skill.match]`; `required_apis`/`grounding_refs` = the skill's `hint_apis`.

- [ ] **Step 1: Write the failing test** — `tests/kb/test_seed.py`:
```python
from groundloop.kb.seed import playbook_from_skill, seed_to_store
from groundloop.kb.validate import load_corpus, SEED_PATH

def test_parses_a_feedstock_skill_into_a_playbook():
    skill = next(s for s in load_corpus(SEED_PATH) if s["id"] == "fragment-view-after-destroy-npe")
    pb = playbook_from_skill(skill)
    assert pb.id == "fragment-view-after-destroy-npe" and pb.tier == "candidate"
    assert pb.signature.startswith("A ") or len(pb.signature) > 0
    assert pb.localize and pb.fix and pb.required_apis == tuple(skill["hint_apis"])
    assert pb.grounding_refs == tuple(skill["hint_apis"])
    assert pb.applies_when == skill["match"]

def test_seed_to_store_grounds_and_admits(monkeypatch):
    resolver = lambda ref: True                     # accept all refs (hermetic)
    skills = load_corpus(SEED_PATH)
    store, rejected = seed_to_store(skills, resolver)
    assert len(store) == 12 and not rejected        # all 12 admitted under an all-true resolver
    assert all(pb.tier == "candidate" for pb in store.values())
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/kb/test_seed.py -q`

- [ ] **Step 3: Implement `groundloop/kb/seed.py`**:
```python
"""Deterministic feedstock parser (replaces the retired LLM kb-extract). Splits a Skill's guidance
Signature:/Localize:/Fix: clauses into a KnowledgePlaybook, grounds it, and seeds the candidate store."""
from __future__ import annotations

from groundloop.kb.knowledge import KnowledgePlaybook
from groundloop.kb.knowledge_ground import GroundCheck, check_knowledge_grounded

_SEED_EVIDENCE = {"measured_lift": {}, "wilson95": None, "validating_case_ids": [], "fail_count": 0, "demotions": []}

def _clause(guidance: str, label: str) -> str:
    """The text of one 'Label: ...' clause (one line in the feedstock), else ''."""
    for line in guidance.splitlines():
        s = line.strip()
        if s.startswith(label):
            return s[len(label):].strip()
    return ""

def playbook_from_skill(skill: dict) -> KnowledgePlaybook:
    g = skill.get("guidance", "")
    apis = tuple(str(a).strip() for a in (skill.get("hint_apis") or ()) if str(a).strip())
    return KnowledgePlaybook(
        id=str(skill.get("id", "")),
        applies_when=dict(skill.get("match", {}) or {}),
        signature=_clause(g, "Signature:"),
        localize=(_clause(g, "Localize:"),) if _clause(g, "Localize:") else (),
        fix=(_clause(g, "Fix:"),) if _clause(g, "Fix:") else (),
        required_apis=apis,
        grounding_refs=apis,                         # the concrete code entities the playbook names
        provenance=str(skill.get("id", "")),
        tier="candidate",
        evidence=dict(_SEED_EVIDENCE),
    )

def seed_to_store(skills, resolver, *, denylist=None, existing=None):
    """Parse+ground every feedstock Skill; merge survivors at tier=candidate (setdefault, idempotent)."""
    store = dict(existing or {})
    rejected: list[tuple[KnowledgePlaybook, GroundCheck]] = []
    for skill in skills:
        pb = playbook_from_skill(skill)
        chk = check_knowledge_grounded(pb, resolver, denylist=denylist)
        if not chk.grounded:
            rejected.append((pb, chk))
            continue
        store.setdefault(pb.id, pb)
    return store, rejected
```

- [ ] **Step 4: Delete the retired LLM path**
```bash
git rm groundloop/kb/extract.py tests/kb/test_extract.py tests/kb/test_cli_kb_extract.py
```
Then `grep -rn "kb.extract\|extract_to_store\|knowledge_from_skill\|kb-extract" groundloop tests` and remove any remaining import/CLI reference (the `kb-extract` subcommand in `cli/__init__.py` — see Task 12).

- [ ] **Step 5: Run — expect PASS** (and confirm nothing imports the deleted module)

Run: `.venv/bin/python -m pytest tests/kb/test_seed.py tests/kb/test_feedstock.py -q`

- [ ] **Step 6: Commit**
```bash
git add groundloop/kb/seed.py tests/kb/test_seed.py
git commit -m "feat(kb): deterministic feedstock parser + 12-playbook seed (retire LLM kb-extract)"
```

---

## Phase B — The bounded retriever

### Task 5: `PlaybookRegistry.select` — predicate → rerank(signature) → top-k=2

**Files:**
- Modify: `groundloop/kb/registry.py`
- Test: `tests/kb/test_registry.py`

- [ ] **Step 1: Update the registry test** — in `tests/kb/test_registry.py`, build `KnowledgePlaybook`s (via a `_pb` factory) and assert: predicate filter fires only matching playbooks; `tier_floor="validated"` drops `candidate`s; `top_k=2` caps the result; rerank orders by `signature` relevance when an embedder is passed. Add:
```python
def test_select_respects_tier_floor_and_top_k():
    reg = PlaybookRegistry([_pb("a", tier="validated"), _pb("b", tier="validated"),
                            _pb("c", tier="candidate")], top_k=2)
    ctx = _ctx_matching_all()
    out = reg.select(ctx, "validated")
    assert {p.id for p in out} <= {"a", "b"} and len(out) <= 2      # candidate excluded, capped at 2
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/kb/test_registry.py -q`

- [ ] **Step 3: Implement** in `groundloop/kb/registry.py` — rename `KnowledgeRegistry` → `PlaybookRegistry`; default `top_k=2`; in `select`, rerank over `k.signature` (was `k.content`); keep the predicate filter + `TIERS`-floor gate + the `_cos` bge-m3 rerank + `load(path, *, embedder=None, top_k=2)`. Keep the load/select signatures (`select(ctx, tier_floor)`). Add `KnowledgeRegistry = PlaybookRegistry` alias only if an untouched external caller needs it (grep first).

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/kb/test_registry.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/kb/registry.py tests/kb/test_registry.py
git commit -m "feat(kb): PlaybookRegistry.select - predicate filter, signature rerank, bounded top-k=2, validated floor"
```

---

## Phase C — The learning loop

### Task 6: `mint_playbook` — clean-applying fix → grounded candidate (dedupe by crash-class)

**Files:**
- Create: `groundloop/kb/mint.py`
- Test: `tests/kb/test_mint.py` (new)

Rationale: oracle-blind. Trigger = `patch_applies`. Extract fields from the loop's own artifacts (`signals`, `locations`, the patch diff). Dedupe id = a crash-class fingerprint (predicate + top signal tokens) so same-class fixes merge.

- [ ] **Step 1: Write the failing test** — `tests/kb/test_mint.py`:
```python
from groundloop.kb.mint import mint_playbook, crash_class_id
from groundloop.core.types import Signals

def _signals():
    return Signals(errors=("NullPointerException",), methods=("onDestroyView",), classes=("MyFragment",))

def test_mint_from_clean_apply_writes_a_grounded_candidate():
    resolver = lambda ref: True
    pb = mint_playbook(ticket_id="T-1", signals=_signals(),
                       locations=["MyFragment.kt"], patch_diff="+++ b/MyFragment.kt\n+binding = null\n",
                       resolver=resolver)
    assert pb is not None and pb.tier == "candidate" and pb.provenance == "minted:T-1"
    assert pb.localize == ("MyFragment.kt",)

def test_same_crash_class_gets_the_same_id():
    a = crash_class_id(_signals()); b = crash_class_id(_signals())
    assert a == b                                    # dedupe key stable across identical signals

def test_ungrounded_mint_is_dropped():
    pb = mint_playbook(ticket_id="T-2", signals=_signals(), locations=["X.kt"],
                       patch_diff="+++ b/X.kt\n+foo()\n", resolver=lambda ref: False)   # nothing resolves
    assert pb is None
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/kb/test_mint.py -q`

- [ ] **Step 3: Implement `groundloop/kb/mint.py`**:
```python
"""Mint a candidate KnowledgePlaybook from a clean-applying fix (oracle-blind). Trigger: patch_applies.
Fields come from the loop's own artifacts (signals/locations/diff); refs must ground; id = crash-class
fingerprint so same-class fixes dedupe."""
from __future__ import annotations

import hashlib
import re

from groundloop.kb.knowledge import KnowledgePlaybook
from groundloop.kb.knowledge_ground import check_knowledge_grounded

_MINT_EVIDENCE = {"measured_lift": {}, "wilson95": None, "validating_case_ids": [], "fail_count": 0, "demotions": []}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.:]{2,}")

def _sig_tokens(signals) -> list[str]:
    toks: list[str] = []
    for fam in ("errors", "classes", "methods", "symbols", "libraries"):
        toks += [str(t) for t in getattr(signals, fam, ()) or ()]
    return toks

def crash_class_id(signals) -> str:
    """Stable fingerprint of the crash class = sorted signal tokens hashed. Same class -> same id -> dedupe."""
    key = "|".join(sorted(set(_sig_tokens(signals))))
    return "minted-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]

def _apis_from_diff(diff: str) -> tuple[str, ...]:
    added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    return tuple(sorted(set(_IDENT.findall(added))))

def mint_playbook(*, ticket_id: str, signals, locations, patch_diff: str, resolver, denylist=None):
    toks = _sig_tokens(signals)
    apis = _apis_from_diff(patch_diff)
    refs = tuple(sorted(set(apis) | {str(m) for m in getattr(signals, "methods", ()) or ()}))
    pb = KnowledgePlaybook(
        id=crash_class_id(signals),
        applies_when={"any_text": [t.lower() for t in toks]} if toks else {},
        signature=" ".join(toks) or "(unlabelled crash)",
        localize=tuple(locations),
        fix=(f"touched: {', '.join(apis)}",) if apis else (),
        required_apis=apis,
        grounding_refs=refs,
        provenance=f"minted:{ticket_id}",
        tier="candidate",
        evidence=dict(_MINT_EVIDENCE),
    )
    chk = check_knowledge_grounded(pb, resolver, denylist=denylist)
    return pb if chk.grounded else None
```

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/kb/test_mint.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/kb/mint.py tests/kb/test_mint.py
git commit -m "feat(kb): mint_playbook - grounded candidate from a clean-applying fix, deduped by crash-class"
```

### Task 7: Retarget the retain-loop + A/B + placebo to playbooks

**Files:**
- Modify: `groundloop/kb/attribute.py`, `groundloop/kb/ab.py`, `groundloop/kb/knowledge_placebo.py`
- Test: `tests/kb/test_attribute_govern.py`, `tests/kb/test_ab.py`, `tests/kb/test_kb_ab_retarget.py`, `tests/kb/test_knowledge_placebo.py`, `tests/kb/test_lofo_knowledge.py`

Rationale: these iterate over the store generically (id/applies_when/tier/evidence). The playbook keeps all four, so most changes are the `content`/`type` references in the placebo builder + any render call. Keep the `resolved_rate_strict` LOFO default (landed Cycle 1) and the `accept_grounded` gate.

- [ ] **Step 1: Update tests** — in each listed test file, swap `Knowledge(...)` factories for `KnowledgePlaybook(...)` (signature/localize/fix instead of type/content). Keep the governance assertions (LOFO Δ, placebo swap, promote/retire, the mutation-verified accept-gate test from Cycle 1). For `knowledge_placebo`, assert the decoy is a `KnowledgePlaybook` with a length-matched irrelevant `signature`+`fix` and the same firing set.

- [ ] **Step 2: Run — expect FAILs** across the listed files.

Run: `.venv/bin/python -m pytest tests/kb/test_attribute_govern.py tests/kb/test_ab.py tests/kb/test_knowledge_placebo.py tests/kb/test_lofo_knowledge.py tests/kb/test_kb_ab_retarget.py -q`

- [ ] **Step 3: Implement** — in `knowledge_placebo.py`, build the decoy `KnowledgePlaybook` (length-match `signature`+`fix` prose to the real one, keep `applies_when`); in `attribute.py`/`ab.py`, update any reference to `.content`/`.type` (e.g. `_case_signal` reads only `evidence`/firing, not content — verify) and any `render_knowledge`→`render_playbooks` call. Do NOT change the LOFO metric default or the gate.

- [ ] **Step 4: Run — expect PASS** (full kb suite)

Run: `.venv/bin/python -m pytest tests/kb/ -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/kb/attribute.py groundloop/kb/ab.py groundloop/kb/knowledge_placebo.py tests/kb/
git commit -m "feat(kb): retarget retain-loop + A/B + placebo from atoms to playbooks (metric default unchanged)"
```

---

## Phase D — Wiring into `gloop run`

### Task 8: `KnowledgeInjectingFixEngine` decorator

**Files:**
- Create: `groundloop/adapters/fix/knowledge_inject.py`
- Test: `tests/fixeval/test_knowledge_inject.py` (new)

Rationale: `run_ticket` (frozen) calls `fixer.propose(worktree, ticket, locations)` with no signals. The decorator wraps the real fixer, gets signals from the shared `RecordingExtractor.last_signals` (populated before `propose`), builds `ctx`, selects `validated` playbooks, and injects via the inner `with_preamble`. Guards a fixer without `with_preamble` (canned).

- [ ] **Step 1: Write the failing test** — `tests/fixeval/test_knowledge_inject.py`, mirroring the `_Fixer` spy shape from `tests/fixeval/test_skills_inject.py`:
```python
from groundloop.adapters.fix.knowledge_inject import KnowledgeInjectingFixEngine
from groundloop.core.types import Ticket, WorkTree, RepoRef, Patch

class _Fixer:
    def __init__(self, preamble=""): self.preamble = preamble; self.model = None
    def with_preamble(self, p): return _Fixer(p)
    def propose(self, wt, ticket, locations): return Patch(diff=f"[{self.preamble}]", files=())

class _Rec:                       # a stand-in RecordingExtractor
    def __init__(self, sig): self.last_signals = sig

class _Reg:
    def __init__(self, pbs): self.pbs = pbs
    def select(self, ctx, floor): return self.pbs

def test_injects_selected_validated_playbooks_via_with_preamble():
    from groundloop.kb.knowledge import KnowledgePlaybook
    pb = KnowledgePlaybook(id="p", applies_when={"any_text": ["x"]}, signature="sig", localize=("l",),
                           fix=("f",), required_apis=("A.b",), grounding_refs=("A.b",), provenance="p",
                           tier="validated", evidence={})
    dec = KnowledgeInjectingFixEngine(_Fixer(), registry=_Reg([pb]), extractor_rec=_Rec(_some_signals()),
                                      tier_floor="validated")
    patch = dec.propose(WorkTree(RepoRef("engineering"), "/w"), _ticket(), ["Main.kt"])
    assert "# Grounded playbooks" in patch.diff        # the inner fixer received the rendered preamble

def test_empty_selection_is_passthrough():
    dec = KnowledgeInjectingFixEngine(_Fixer(), registry=_Reg([]), extractor_rec=_Rec(_some_signals()),
                                      tier_floor="validated")
    patch = dec.propose(WorkTree(RepoRef("engineering"), "/w"), _ticket(), ["Main.kt"])
    assert patch.diff == "[]"                          # no preamble -> inner fixer unchanged
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/fixeval/test_knowledge_inject.py -q`

- [ ] **Step 3: Implement `groundloop/adapters/fix/knowledge_inject.py`**:
```python
"""Composition-root FixEngine decorator: consult validated playbooks and inject them into the fixer's
prompt. run_ticket (frozen) passes only (worktree, ticket, locations); we read the per-ticket signals from
the shared RecordingExtractor and build the selection ctx. Fail-safe: no signals / empty selection / a
fixer without with_preamble -> the inner fixer runs unchanged."""
from __future__ import annotations

from groundloop.kb.render import render_playbooks
from groundloop.skills.ctx import build_ctx

class KnowledgeInjectingFixEngine:
    def __init__(self, inner, *, registry, extractor_rec, tier_floor: str = "validated"):
        self.inner = inner
        self.registry = registry
        self.extractor_rec = extractor_rec
        self.tier_floor = tier_floor
        self.model = getattr(inner, "model", None)      # keep cost accounting working

    def with_preamble(self, preamble):                  # forward for plan-path callers
        return self.inner.with_preamble(preamble)

    def propose(self, worktree, ticket, locations):
        signals = getattr(self.extractor_rec, "last_signals", None)
        preamble = ""
        if signals is not None and hasattr(self.inner, "with_preamble"):
            ctx = build_ctx(signals, ticket, worktree.repo.name)
            preamble = render_playbooks(self.registry.select(ctx, self.tier_floor))
        fixer = self.inner.with_preamble(preamble) if preamble else self.inner
        return fixer.propose(worktree, ticket, locations)
```
(If `inner` exposes `propose_with_plan`, forward it too via a passthrough method so the plan path keeps working when this decorator is used outside batch — mirror the `with_preamble` forward.)

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/fixeval/test_knowledge_inject.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/adapters/fix/knowledge_inject.py tests/fixeval/test_knowledge_inject.py
git commit -m "feat(fix): KnowledgeInjectingFixEngine - composition-root playbook injection (frozen core)"
```

### Task 9: Config surface — `KLOOP_KB_STORE` / `KLOOP_KB_TOPK`

**Files:**
- Modify: `groundloop/config/settings.py`
- Test: `tests/test_settings.py` (or the existing settings test)

- [ ] **Step 1: Write the failing test** — assert the two new fields load from env with defaults:
```python
def test_kb_settings_load_with_defaults():
    from groundloop.config.settings import Settings
    s = Settings.load({"KLOOP_KB_STORE": "/tmp/kb.json", "KLOOP_KB_TOPK": "2"})
    assert s.kb_store == "/tmp/kb.json" and s.kb_topk == 2
    d = Settings.load({})
    assert d.kb_store == "" and d.kb_topk == 2       # default topk=2, no store
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/test_settings.py::test_kb_settings_load_with_defaults -q`

- [ ] **Step 3: Implement** in `groundloop/config/settings.py` — add two frozen fields + their `load` lines (reuse `_pos_float` for the int):
```python
    kb_store: str = ""
    kb_topk: int = 2
```
```python
            kb_store=e.get("KLOOP_KB_STORE", ""),
            kb_topk=int(_pos_float(e.get("KLOOP_KB_TOPK"), 2.0)),
```

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/config/settings.py tests/test_settings.py
git commit -m "feat(config): KLOOP_KB_STORE / KLOOP_KB_TOPK settings for the wired KB"
```

### Task 10: Compose the decorator (+ optional mint hook) in the `run` handler

**Files:**
- Modify: `groundloop/cli/__init__.py` (the `run` parser lines ~828-887 + the batch composition block ~1491-1535)
- Modify: `groundloop/run/batch.py` (optional mint hook)
- Test: `tests/run/test_batch.py` (mint hook), `tests/run/test_cli_run_kb.py` (new, decorator wiring)

- [ ] **Step 1: Write the failing tests.**
  (a) In `tests/run/test_batch.py`, add a mint-hook test mirroring the existing harness (`_StubIndex`, `_dataset`, `MockGerrit`): pass a `mint=` callable to `run_dataset` and assert it's called once per clean-applying case with `(ticket_id, signals, locations, patch_diff)`.
  (b) In `tests/run/test_cli_run_kb.py`, drive `main(["run", ...])` with `--kb-store <seeded.json>` + `--repos` and assert the composed fixer is a `KnowledgeInjectingFixEngine` (spy the composition, or assert a run-record whose fix reflects an injected preamble). Keep it hermetic (canned model path via `KLOOP_DEV`/a stub fixer).

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/python -m pytest tests/run/test_batch.py -k mint tests/run/test_cli_run_kb.py -q`

- [ ] **Step 3: Implement.**
  - `run/batch.py`: add a `mint=None` param to `run_dataset`; after `applies` is computed (line 34), `if mint is not None and applies: mint(case.case_id, sig, list(rec.locations), rec.patch.diff)`. No `core/` edit.
  - `cli/__init__.py` `run` parser: add `--kb-store` (default `""`, else `KLOOP_KB_STORE`), `--kb-topk` (int, default from settings), `--knowledge {none,validated}` (default `none`).
  - `cli/__init__.py` batch block (after `fixer, cost_model = _build_run_fixer(...)`, ~line 1514): if a kb store is configured, load `PlaybookRegistry.load(store, embedder=_build_embedder(), top_k=kb_topk)` and wrap `fixer = KnowledgeInjectingFixEngine(fixer, registry=reg, extractor_rec=extractor, tier_floor="validated")`; build a `mint = lambda tid, sig, locs, diff: _persist_mint(store, tid, sig, locs, diff, resolver=atlas_resolver(Store(index_db)))` and pass `mint=mint` to `run_dataset`. Fail-safe/opt-in: absent `--kb-store`, byte-identical to today (no decorator, no mint).

- [ ] **Step 4: Run — expect PASS** (batch + cli-run-kb + full run suite)

Run: `.venv/bin/python -m pytest tests/run/ tests/fixeval/test_knowledge_inject.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/cli/__init__.py groundloop/run/batch.py tests/run/test_batch.py tests/run/test_cli_run_kb.py
git commit -m "feat(run): wire the KB into gloop run - validated-playbook injection + opt-in mint hook"
```

### Task 11: `gloop kb-seed` CLI + retire `kb-extract`

**Files:**
- Modify: `groundloop/cli/__init__.py`
- Test: `tests/kb/test_cli_kb_seed.py` (new)

- [ ] **Step 1: Write the failing test** — `main(["kb-seed", "--index-db", <atlas>, "--out", <store>])` parses the feedstock, grounds against the atlas, writes the store, and prints the admitted count. Mirror the old `test_cli_kb_extract.py` shape but with no model (deterministic).

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement** — add a `kb-seed` subparser + `_run_kb_seed(args)` that calls `load_corpus(SEED_PATH)` → `seed_to_store(skills, atlas_resolver(Store(args.index_db)))` → `save_knowledge(args.out, store)`. Remove the `kb-extract` subparser + `_run_kb_extract` (retired in Task 4).

- [ ] **Step 4: Run — expect PASS**

Run: `.venv/bin/python -m pytest tests/kb/test_cli_kb_seed.py -q`

- [ ] **Step 5: Commit**
```bash
git add groundloop/cli/__init__.py tests/kb/test_cli_kb_seed.py
git commit -m "feat(cli): gloop kb-seed (deterministic feedstock -> grounded candidate store); retire kb-extract"
```

### Task 12: Governance — KB Dormant → Candidate

**Files:**
- Modify: `docs/capabilities.md`

- [ ] **Step 1:** Move the `**Dev-experience KB**` entry from the `### Dormant` subsection back into `### Candidate`, retitled to reflect the redesign: *active, wired into `gloop run` (opt-in `--kb-store`, `validated`-only injection), self-improving (mint→retain-loop), `[production]`-gated on a `resolved_rate` A/B*. Update the Dormant subsection count `(1)` → `(0)` (or remove the subsection if empty) and the Candidate count accordingly. Cite this plan + the spec.

- [ ] **Step 2: Verify** — `grep -n "KB" docs/capabilities.md` reads consistently (Candidate, wired, opt-in, production-gated; no lingering "Dormant" for the KB).

- [ ] **Step 3: Commit**
```bash
git add docs/capabilities.md
git commit -m "docs(capabilities): KB Dormant -> Candidate (redesigned, wired, opt-in, production-gated)"
```

---

## Self-Review

**Spec coverage** (against `2026-07-19-kb-playbook-redesign-design.md`):
- §3 the record → Task 1. §3 grounding → Task 3. §4 retriever (k=2, signature, validated floor) → Task 5.
- §5a mint (applies-trigger, dedupe-by-class, oracle-blind, grounded) → Task 6. §5b promote (per-playbook LOFO/placebo) → Task 7.
- §6 wiring (decorator, batch mint hook, opt-in, frozen core) → Tasks 8–10. §8 seed (12 playbooks, parse-not-shred) → Task 4 + Task 11.
- §7 fail-safe (grounding + validated-only + Bug Plan Mode) → enforced by Tasks 3/5/8 (Bug Plan Mode is the unchanged inner fixer). §8 governance → Task 12. Config → Task 9.
- §2 non-goals (no efficacy read, production-acceptance deferred) → not built (correct).

**Placeholder scan:** every code step shows real code; each has a verify command. `_ctx_matching_all`/`_some_signals`/`_ticket`/`_persist_mint` are named helpers the implementer writes in-task by mirroring the cited existing patterns (`tests/fixeval/test_skills_inject.py` `_Fixer`, `tests/run/test_batch.py` `_dataset`, `skills/ctx.build_ctx`) — flagged, not left vague.

**Type consistency:** `KnowledgePlaybook` fields are identical across Tasks 1/2/3/5/6/7/8. `select(ctx, tier_floor)`, `render_playbooks(items)`, `check_knowledge_grounded(pb, resolver, denylist=)`, `mint_playbook(*, ticket_id, signals, locations, patch_diff, resolver, denylist=)` are used consistently. `KnowledgeRegistry`→`PlaybookRegistry` rename is centralized in Task 5 (grep-guarded).

**Risk notes:** Task 4 deletes modules — run a repo-wide grep for importers first. Task 7 touches several governance tests at once — do the test edits and impl together. Task 10 is the integration keystone — keep the KB path strictly opt-in so an unconfigured `gloop run` stays byte-identical. Do Phases A→B→C→D in order (each depends on the prior).
