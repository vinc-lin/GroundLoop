# Claim-Centric Distilled KB — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Invert the KB onto atomic, grounded *claims* — extract candidate claims from the messy Skills,
admit only those that are grounded and (later) measurably effective, inject only validated claims into the
plan-format fix loop, and validate/retain per-claim.

**Architecture:** Distill-first pipeline — extract (LLM proposes) -> ground-check -> measure (candidates
eval-only) -> attribute (archive screen -> LOFO confirm) -> promote/retire (per-claim). Reuses the plan
archive, `accept_grounded`, LOFO, placebo, the predicate compiler, and the lifecycle machinery; `core/`
frozen, atlas schema unchanged.

**Tech Stack:** Python 3.12, `.venv` (uv). Tests: pytest. Lint: ruff (line length 110). No new deps.

**Design spec:** `docs/superpowers/specs/2026-07-07-claim-centric-distilled-kb-design.md` (decisions D1-D6
settled). Supersedes the 07-06 distilled-KB spec.

**Scope note:** Phases A-C are hermetic, TDD, subagent-executable. Phase D is a **gated live runbook** (real
LLM + fix-loop spend; needs the gateway free), run only after A-C land — like the plan-format Phase 3.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `groundloop/kb/claim.py` | `Claim` + `claims.json` store | Create (A1) |
| `groundloop/kb/claim_ground.py` | oracle-blind ground-check (atlas existence + leak) | Create (A2) |
| `groundloop/kb/extract.py` | LLM decompose Skill -> candidate Claims | Create (A3) |
| `groundloop/kb/registry.py` | `ClaimRegistry` (select by predicate + tier floor) | Create (B1) |
| `groundloop/kb/render.py` | `render_claims` (compose by type into the plan) | Create (B2) |
| `groundloop/kb/claim_placebo.py` | per-claim placebo | Create (C1) |
| `groundloop/kb/attribute.py` | screen + `lofo_claims` + per-claim verdict | Create (C2-C4) |
| `groundloop/kb/data/claims.json` | the claim store (machine-updated) | Create |
| `groundloop/fixeval/runner.py` | `fired_claims` + the `--claims` path | Modify (B3/B4) |
| `groundloop/fixeval/archive.py` | `fired_claims` in the payload | Modify (B4) |
| `groundloop/cli/__init__.py` | `kb-extract`, `kb-attribute`, `--claims` | Modify (A3/B3/C4) |

Guardrails (hold at every step): never edit `groundloop/core/`; never alter the atlas SQLite schema; keep
the loop oracle-blind (grounding probes the atlas = code reality fleet-wide, never the oracle; offline grade
is the sole oracle read); commit only when the suite is green + ruff clean; end commit messages with the
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

## Phase A — Claim model + store + ground-check + LLM extraction plumbing

Phase A lays the claim-centric foundation the rest of the plan builds on: the frozen `Claim`, its machine-updated `claims.json` store, the deterministic oracle-blind ground-check that admits a candidate only if its `grounding_refs` resolve in the atlas and it carries no fleet-owner leak, and the `gloop kb-extract` LLM-propose → tolerant-parse → ground-check → write pipeline. The LLM only *proposes*; grounding + (later) measurement *admit*. Nothing here injects into a fix, so Phase A cannot regress the loop; it only produces `tier=candidate` claims that Phase B/C consume.

**Shared-contract anchors used by later phases:** `Claim(id, applies_when, type, content, grounding_refs, provenance, tier, evidence)` in `groundloop/kb/claim.py`; the store at `groundloop/kb/data/claims.json` via `load_claims`/`save_claims` (dict keyed by claim id, mirroring `provenance.py`); `evidence` is the lifecycle-bookkeeping bag (`measured_lift`, `wilson95`, `validating_case_ids`, `fail_count`, `demotions`, `evidence_context`) that Phase C bridges to the reused `kb/lifecycle.apply_verdict` (which reads `.tier`/`.fail_count`/`.demotions`).

**Guardrails (apply to every task below):** never edit `groundloop/core/`; never alter the atlas SQLite schema; keep the loop oracle-blind — grounding probes the atlas (code reality) fleet-wide, never scoped to the predicted/owning repo, and the offline grade stays the sole oracle read; build only what the task specifies (YAGNI); strict TDD (write failing test → run → confirm it fails → implement complete code → run → pass); commit per task with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; full suite green (`.venv/bin/python -m pytest -q`) + ruff clean (`.venv/bin/ruff check groundloop tests`, line length 110) before each commit.

---

### A1 — `Claim` dataclass + `claims.json` load/save

The atomic unit of trust and its persistence layer, modeled verbatim on `kb/provenance.py` (frozen dataclass + `asdict`/JSON round-trip + re-tuple on load). A missing store file is an empty store, not an error. Store keyed by claim id (dict) so Phase B/C reuse it as both a registry source and a lifecycle sidecar.

**Files**
- create `groundloop/kb/claim.py`
- create `tests/kb/test_claim.py`

**Steps**

1. **Write the failing test** `tests/kb/test_claim.py`:

```python
"""Round-trip + defaulting contract for the claim store (Phase A, claim-centric distilled KB).
Mirrors tests/kb/test_provenance.py: save->load equals, tuple fields survive JSON, missing file is an
empty store, unknown keys dropped + id defaulted from the dict key."""
import json

from groundloop.kb.claim import Claim, load_claims, save_claims


def _claim() -> Claim:
    return Claim(
        id="native-null-deref-segv-fix_step-abc12345",
        applies_when={"any_text": ["sigsegv", "segv_maperr"]},
        type="fix_step",
        content="Reject a 0 nativePtr handle at native method entry before dereferencing it.",
        grounding_refs=("GetLongField", "std::weak_ptr::lock"),
        provenance="native-null-deref-segv",
        tier="candidate",
        evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [],
                  "fail_count": 0, "demotions": []},
    )


def test_save_then_load_round_trips_all_fields(tmp_path):
    c = _claim()
    p = tmp_path / "claims.json"
    save_claims(str(p), {c.id: c})
    back = load_claims(str(p))
    assert back == {c.id: c}
    # grounding_refs must survive JSON (list) -> tuple reconstruction, else frozen equality fails
    assert isinstance(back[c.id].grounding_refs, tuple)


def test_missing_file_is_empty_store(tmp_path):
    assert load_claims(str(tmp_path / "nope.json")) == {}


def test_unknown_keys_dropped_and_id_defaulted(tmp_path):
    p = tmp_path / "claims.json"
    p.write_text(json.dumps({
        "c1": {"applies_when": {"any_text": ["anr"]}, "type": "localize_hint",
               "content": "Look in the foreground-service start path.", "grounding_refs": ["startForeground"],
               "provenance": "foreground-service-not-started", "tier": "candidate", "evidence": {},
               "bogus": 123}}))          # id omitted in the body; 'bogus' is unknown
    back = load_claims(str(p))
    assert back["c1"].id == "c1"                          # id defaulted from the dict key
    assert not hasattr(back["c1"], "bogus")              # unknown key dropped
    assert back["c1"].grounding_refs == ("startForeground",)
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_claim.py -q` → `ModuleNotFoundError: groundloop.kb.claim`.

3. **Implement** `groundloop/kb/claim.py` (complete):

```python
"""The atomic Claim — the unit of trust in the claim-centric distilled KB (design spec
docs/superpowers/specs/2026-07-07-claim-centric-distilled-kb-design.md §4). A Claim is a self-contained,
GROUNDED piece of advice carrying its OWN firing predicate (`applies_when`, a [skill.match]-style spec
reusing groundloop/skills/predicate.compile_predicate) — never a whole Skill.

Claims persist in a machine-updated JSON store (`groundloop/kb/data/claims.json`, keyed by claim id —
analogous to kb/provenance.py's sidecar): the retain-loop mutates tier + evidence, while the human-authored
feedstock stays the aaos_kb_seed.toml Skills that extraction (A3) decomposes. The `evidence` dict is the
lifecycle-bookkeeping bag (measured_lift, wilson95, validating_case_ids, fail_count, demotions,
evidence_context); Phase C bridges tier + evidence[fail_count]/[demotions] to the reused
kb/lifecycle.apply_verdict (which reads .tier/.fail_count/.demotions). Phase A only persists it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CLAIMS_PATH = str(Path(__file__).parent / "data" / "claims.json")

# JSON has no tuple — grounding_refs serializes as a list and must be re-tupled on load so frozen-dataclass
# equality (round-trip test + Phase-C diffing) holds. applies_when / evidence stay dicts.
_TUPLE_FIELDS = ("grounding_refs",)


@dataclass(frozen=True)
class Claim:
    id: str
    applies_when: dict            # a [skill.match]-style predicate: WHEN this claim fires
    type: str                     # "localize_hint" | "fix_step" | "api_requirement"
    content: str                  # the ONE thing it advises (this text enters the plan prompt)
    grounding_refs: tuple[str, ...]  # the code entities it asserts exist (checkable in the atlas)
    provenance: str               # the source Skill id it was distilled from (kept; never trusted)
    tier: str                     # "candidate" | "validated" | "canonical" | "retired"
    evidence: dict = field(default_factory=dict)  # lifecycle-bookkeeping bag (see module docstring)


def _to_claim(cid: str, raw: dict) -> Claim:
    """Build a Claim from a raw JSON row: drop unknown keys, default the id from its dict key, re-tuple."""
    known = {f.name for f in fields(Claim)}
    kw = {k: v for k, v in raw.items() if k in known}
    kw.setdefault("id", cid)                       # id is the dict key; tolerate its absence in the body
    for tf in _TUPLE_FIELDS:
        if kw.get(tf) is not None and not isinstance(kw[tf], tuple):
            kw[tf] = tuple(kw[tf])
    return Claim(**kw)


def load_claims(path: str = CLAIMS_PATH) -> dict[str, Claim]:
    """Load the claim store keyed by claim id; a missing file is an empty store (no claims yet), not an
    error — mirrors kb/provenance.load_sidecar."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {cid: _to_claim(cid, row) for cid, row in raw.items()}


def save_claims(path: str, claims: dict[str, Claim]) -> None:
    """Write the store as deterministic (sorted-key, indented) JSON, keyed by the passed keys."""
    out = {cid: asdict(c) for cid, c in claims.items()}
    Path(path).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_claim.py -q`, then the full suite `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check groundloop tests`.

5. **Commit:** `feat(kb): Claim dataclass + claims.json store (Phase A1)` with the co-author trailer.

---

### A2 — `check_claim_grounded` (atlas existence + leak red-test, oracle-blind)

The deterministic disposal gate of §5.2. A candidate is admitted only if it is (a) well-formed (valid `type`, non-empty `content`, a compilable `applies_when`), (b) GROUNDED — every `grounding_ref` resolves fleet-wide in the atlas — and (c) LEAK-SAFE — its `content`/`grounding_refs`/`applies_when` name no fleet-owner token. Existence is probed via an injected `resolver` callable so the gate is hermetic-testable; the production resolver `atlas_resolver(store)` wraps `Store.keyword_search`. Checking *fleet-wide* existence reveals nothing about *which* repo owns the defect → oracle-blind.

**Files**
- create `groundloop/kb/claim_ground.py`
- create `tests/kb/test_claim_ground.py`

**Steps**

1. **Write the failing test** `tests/kb/test_claim_ground.py`:

```python
"""Oracle-blind ground-check for candidate Claims (Phase A2). Hermetic: a fake resolver stands in for the
atlas; the leak red-test runs against the REAL FLEET_OWNER_TOKENS denylist (kb/validate.owner_denylist)."""
from groundloop.kb.claim import Claim
from groundloop.kb.claim_ground import atlas_resolver, check_claim_grounded


def _claim(**over) -> Claim:
    base = dict(id="c-guard", applies_when={"any_text": ["sigsegv"]}, type="fix_step",
                content="Reject a 0 handle at native method entry before dereferencing it.",
                grounding_refs=("GetLongField", "reinterpret_cast"),
                provenance="native-null-deref-segv", tier="candidate", evidence={})
    base.update(over)
    return Claim(**base)


def _resolver(known):
    s = set(known)
    return lambda ref: ref in s


def test_grounded_when_all_refs_resolve_and_no_leak():
    chk = check_claim_grounded(_claim(), _resolver(["GetLongField", "reinterpret_cast"]))
    assert chk.grounded is True
    assert chk.reasons == ()
    assert set(chk.resolved_refs) == {"GetLongField", "reinterpret_cast"}


def test_unresolved_ref_is_not_grounded():
    chk = check_claim_grounded(_claim(), _resolver(["GetLongField"]))     # reinterpret_cast missing
    assert chk.grounded is False
    assert chk.missing_refs == ("reinterpret_cast",)
    assert any(r.startswith("unresolved_refs:") for r in chk.reasons)


def test_owner_token_leak_is_rejected():
    # "exoplayer" is a media3 owner slug in FLEET_OWNER_TOKENS -> a leak even though the ref resolves.
    c = _claim(content="Guard the ExoPlayer native peer handle.", grounding_refs=("GetLongField",))
    chk = check_claim_grounded(c, _resolver(["GetLongField"]))
    assert chk.grounded is False
    assert "exoplayer" in chk.leak_tokens


def test_bad_type_and_empty_content_flagged():
    chk = check_claim_grounded(_claim(type="bogus", content="  "),
                               _resolver(["GetLongField", "reinterpret_cast"]))
    assert chk.grounded is False
    assert any(r.startswith("bad_type:") for r in chk.reasons)
    assert "empty_content" in chk.reasons


def test_empty_grounding_refs_not_grounded():
    chk = check_claim_grounded(_claim(grounding_refs=()), _resolver([]))
    assert chk.grounded is False
    assert "no_grounding_refs" in chk.reasons


def test_atlas_resolver_wraps_keyword_search():
    class FakeStore:                                  # stands in for engines/atlas/store.Store
        def __init__(self, hits): self.hits = set(hits)
        def keyword_search(self, query, k=1, repos=None, kinds=None):
            return [("unit", 0.0)] if query in self.hits else []
    resolve = atlas_resolver(FakeStore({"GetLongField"}))
    assert resolve("GetLongField") is True
    assert resolve("DoesNotExist") is False
    assert resolve("") is False
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_claim_ground.py -q` → `ModuleNotFoundError: groundloop.kb.claim_ground`.

3. **Implement** `groundloop/kb/claim_ground.py` (complete):

```python
"""Deterministic, oracle-blind ground-check for a candidate Claim (design spec §5.2).

A claim is admitted to the store only if it (a) is WELL-FORMED (valid type, non-empty content, a
compilable applies_when predicate — reuse skills/predicate.compile_predicate), (b) is GROUNDED — every
grounding_ref resolves in the atlas (some unit exists for it, fleet-wide) — and (c) is LEAK-SAFE — its
content / grounding_refs / applies_when name NO fleet-owner token (the same FLEET_OWNER_TOKENS red-test the
KB corpus passes, via kb/validate.owner_denylist). Checking FLEET-WIDE existence reveals nothing about WHICH
repo owns the defect, so the gate stays oracle-blind; the atlas is code reality, never the answer.

`resolver(ref) -> bool` decouples the gate from a live atlas so it is hermetic-testable. The production
resolver is `atlas_resolver(store)`, a thin wrapper over Store.keyword_search (queried across ALL repos —
never scoped to the predicted/owning repo).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from groundloop.kb.validate import owner_denylist
from groundloop.skills.predicate import compile_predicate

_VALID_TYPES = ("localize_hint", "fix_step", "api_requirement")


@dataclass(frozen=True)
class GroundCheck:
    grounded: bool
    resolved_refs: tuple[str, ...]
    missing_refs: tuple[str, ...]
    leak_tokens: tuple[str, ...]
    reasons: tuple[str, ...]


def atlas_resolver(store, *, k: int = 1) -> Callable[[str], bool]:
    """A fleet-wide existence probe over the atlas: a ref resolves iff Store.keyword_search returns any
    unit for it, across ALL repos (oracle-blind — never scoped to the predicted/owning repo).

    Implementer-verify (confirmed in engines/atlas/store.py): Store.keyword_search(query, k=20, repos=None,
    kinds=None) -> list[(Unit, rank)]; an empty query is sanitized safely by _fts_query.
    """
    def _resolves(ref: str) -> bool:
        if not ref or not ref.strip():
            return False
        try:
            return bool(store.keyword_search(ref, k=k))
        except Exception:                              # a malformed FTS term must never crash the gate
            return False
    return _resolves


def _leak_haystack(claim) -> str:
    """Lowercased content + grounding_refs + applies_when values — the same surface validate_corpus scans."""
    parts = [claim.content, " ".join(claim.grounding_refs)]
    for v in (claim.applies_when or {}).values():
        if isinstance(v, (list, tuple)):
            parts.append(" ".join(str(x) for x in v))
    return "\n".join(parts).lower()


def check_claim_grounded(claim, resolver: Callable[[str], bool], *,
                         denylist: Optional[set[str]] = None) -> GroundCheck:
    """Dispose one candidate Claim. Grounded iff there are no reasons: well-formed AND every grounding_ref
    resolves AND no fleet-owner leak. `denylist` defaults to the FLEET_OWNER_TOKENS-derived owner_denylist()."""
    deny = owner_denylist() if denylist is None else denylist
    reasons: list[str] = []

    # (a) well-formedness — a claim that can't type-check or can't fire is never grounded/effective.
    if claim.type not in _VALID_TYPES:
        reasons.append(f"bad_type:{claim.type}")
    if not (claim.content or "").strip():
        reasons.append("empty_content")
    if not (claim.id or "").strip():
        reasons.append("empty_id")
    if not claim.applies_when:
        reasons.append("empty_predicate")             # would never fire
    else:
        try:
            compile_predicate(claim.applies_when)     # reuse: closed-vocab keys + eager regex compile
        except ValueError as e:
            reasons.append(f"bad_predicate:{e}")

    # (b) existence — every grounding_ref must resolve fleet-wide in the atlas (else hallucinated).
    resolved: list[str] = []
    missing: list[str] = []
    for ref in claim.grounding_refs:
        (resolved if resolver(ref) else missing).append(ref)
    if not claim.grounding_refs:
        reasons.append("no_grounding_refs")           # cites nothing -> nothing grounded
    if missing:
        reasons.append("unresolved_refs:" + ",".join(missing))

    # (c) leak red-test — no fleet-owner token in content/grounding_refs/applies_when (generic android.*
    #     / androidx.* / sonames are KEPT, exactly as validate_corpus).
    hay = _leak_haystack(claim)
    leak = tuple(tok for tok in sorted(deny) if tok in hay)
    if leak:
        reasons.append("leak:" + ",".join(leak))

    return GroundCheck(grounded=not reasons, resolved_refs=tuple(resolved),
                       missing_refs=tuple(missing), leak_tokens=leak, reasons=tuple(reasons))
```

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_claim_ground.py -q`, then the full suite and ruff.

5. **Commit:** `feat(kb): oracle-blind Claim ground-check — atlas existence + leak red-test (Phase A2)` with the co-author trailer.

---

### A3 — `kb-extract`: Model-driven decomposition → tolerant parse → ground-check → store, + the `gloop kb-extract` CLI

Decompose each feedstock Skill's `Signature:/Localize:/Fix:` prose + `hint_apis` into atomic typed candidate Claims via a Model (LLM PROPOSES), tolerant-parse the output (mirror `fixeval/plan.parse_plan` — never raises), dispose each via `check_claim_grounded` (A2), and merge survivors into `claims.json` at `tier=candidate`. Ids are content-derived + provenance-prefixed (stable, collision-safe across skills). The CLI factors the model + resolver into two module-level seams (`_extract_model` / `_extract_resolver`) so the whole path is hermetic-testable with a scripted `CannedModel` and a fake resolver — no network, no real atlas.

**Files**
- create `groundloop/kb/extract.py`
- create `tests/kb/test_extract.py`
- create `tests/kb/test_cli_kb_extract.py`
- modify `groundloop/cli/__init__.py` (add `_extract_model`, `_extract_resolver`, `_run_kb_extract`, the `kb-extract` subparser, and the dispatch line)

**Steps**

1. **Write the failing module test** `tests/kb/test_extract.py`:

```python
"""LLM-propose decomposition of a feedstock Skill into candidate Claims (Phase A3). Hermetic: a scripted
CannedModel stands in for the LLM; grounding uses a fake resolver. Asserts the tolerant parse never raises,
candidates are typed + content-derived-id'd at tier=candidate, applies_when defaults to the Skill's
[skill.match], and extract_to_store grounds + merges."""
from groundloop.adapters.mock.model import CannedModel
from groundloop.kb.extract import claims_from_skill, extract_to_store, parse_claims

_SKILL = {"id": "native-null-deref-segv", "guidance": "Signature: SIGSEGV.\nFix: guard nativePtr.",
          "hint_apis": ["GetLongField"], "match": {"any_text": ["sigsegv"]}}

_GOOD = ('```json\n{"claims": [{"type": "fix_step", "content": "Guard the 0 nativePtr handle at entry.",'
         ' "grounding_refs": ["GetLongField"], "applies_when": {"any_text": ["sigsegv"]}}]}\n```')


def test_parse_claims_is_tolerant():
    assert parse_claims("") == []
    assert parse_claims("no json here") == []
    assert parse_claims("{ broken json") == []
    parsed = parse_claims(_GOOD)
    assert parsed[0]["type"] == "fix_step"


def test_claims_from_skill_builds_candidates():
    claims = claims_from_skill(_SKILL, CannedModel({"default": _GOOD}))
    assert len(claims) == 1
    c = claims[0]
    assert c.tier == "candidate"
    assert c.type == "fix_step"
    assert c.provenance == "native-null-deref-segv"
    assert c.grounding_refs == ("GetLongField",)
    assert c.applies_when == {"any_text": ["sigsegv"]}
    assert c.id.startswith("native-null-deref-segv-fix_step-")   # content-derived, provenance-prefixed


def test_claims_from_skill_defaults_applies_when_to_skill_match():
    resp = ('{"claims": [{"type": "localize_hint", "content": "Look in the native translation unit.", '
            '"grounding_refs": ["GetLongField"]}]}')                # no applies_when in the proposal
    claims = claims_from_skill(_SKILL, CannedModel({"default": resp}))
    assert claims[0].applies_when == {"any_text": ["sigsegv"]}      # fell back to the Skill's [skill.match]


def test_extract_to_store_grounds_and_merges():
    store, rejected = extract_to_store([_SKILL], CannedModel({"default": _GOOD}),
                                       resolver=lambda ref: ref == "GetLongField")
    assert len(store) == 1 and rejected == []
    (claim,) = store.values()
    assert claim.tier == "candidate"
    # a candidate whose refs don't resolve is REJECTED (not stored)
    store2, rejected2 = extract_to_store([_SKILL], CannedModel({"default": _GOOD}),
                                         resolver=lambda ref: False)
    assert store2 == {} and len(rejected2) == 1
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_extract.py -q` → `ModuleNotFoundError: groundloop.kb.extract`.

3. **Implement** `groundloop/kb/extract.py` (complete):

```python
"""① Extract (design spec §5.1) — LLM-proposed decomposition of a feedstock Skill's prose into atomic,
typed candidate Claims. A batch step (`gloop kb-extract`, A3 CLI) runs a Model over each Skill's
Signature:/Localize:/Fix: guidance + hint_apis + [skill.match], prompting for atomic claims each with a
`content`, a `type`, an `applies_when` predicate (seeded from the Skill's match), and the `grounding_refs`
it names. The LLM is a PROPOSER only; its output is tolerant-parsed (mirror fixeval/plan.parse_plan — never
raises) and every candidate is DISPOSED downstream by kb/claim_ground.check_claim_grounded. A junk
decomposition just yields candidates that fail the gate — noisy, never dangerous.
"""
from __future__ import annotations

import hashlib
import json
import re

from groundloop.kb.claim import Claim
from groundloop.kb.claim_ground import GroundCheck, check_claim_grounded

_JSON_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def _as_list(v) -> list:
    """Coerce a JSON value to a list before iterating; a bare str/dict/etc. -> [] (never char-iterate)."""
    return list(v) if isinstance(v, (list, tuple)) else []


def parse_claims(text: str) -> list[dict]:
    """Tolerant decode of a model's claim decomposition (```json fenced or a bare {...} span). Returns a
    list of raw claim dicts (each with a non-empty content); [] on ANY failure — mirrors
    fixeval/plan.parse_plan and NEVER raises."""
    if not text or not text.strip():
        return []
    m = _JSON_FENCE.search(text)
    raw = m.group(1) if m else text
    if not m:
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1 or j < i:
            return []
        raw = raw[i:j + 1]
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    claims = d.get("claims") if isinstance(d, dict) else d      # tolerate a top-level list of claims
    out: list[dict] = []
    for c in _as_list(claims):
        if isinstance(c, dict) and str(c.get("content", "")).strip():
            out.append(c)
    return out


def _claim_id(skill_id: str, ctype: str, content: str) -> str:
    """Stable, content-derived id, prefixed by the source Skill so claims never collide across Skills."""
    h = hashlib.sha1(content.encode("utf-8")).hexdigest()[:8]
    return f"{skill_id}-{ctype or 'claim'}-{h}"


def _extract_prompt(skill: dict) -> str:
    guidance = skill.get("guidance", "")
    hint_apis = ", ".join(skill.get("hint_apis", ()) or ())
    match = json.dumps(skill.get("match", {}) or {})
    return (
        "Decompose the crash-RCA playbook below into ATOMIC, self-contained claims. Each claim advises "
        "exactly ONE thing and names the concrete code entities (API / symbol / file names) it asserts "
        'exist. Reply ONLY with a JSON object {"claims": [{type, content, grounding_refs, applies_when}]} '
        "where:\n"
        '- type is one of "localize_hint" | "fix_step" | "api_requirement";\n'
        "- content is the single piece of advice (this exact text is injected into a repair prompt);\n"
        "- grounding_refs is a list of the code entities the claim names;\n"
        "- applies_when is a [skill.match]-style predicate for WHEN the claim fires (default: the "
        "playbook's own match below).\n"
        "Name NO product / repo / vendor identifiers — stay generic to the crash signature.\n\n"
        f"Playbook guidance:\n{guidance}\n\n"
        f"Known APIs: {hint_apis}\n"
        f"Playbook match predicate: {match}\n"
    )


def claims_from_skill(skill: dict, model) -> list[Claim]:
    """LLM PROPOSES: decompose one feedstock Skill (a raw dict from kb/validate.load_corpus) into candidate
    Claims at tier=candidate. `applies_when` falls back to the Skill's [skill.match] when the proposal omits
    it. Content-identical claims within a Skill are de-duplicated by their derived id. Never raises."""
    skill_id = skill.get("id", "skill")
    default_match = dict(skill.get("match", {}) or {})
    raw = parse_claims(model.complete(_extract_prompt(skill)) or "")
    out: list[Claim] = []
    seen: set[str] = set()
    for c in raw:
        ctype = str(c.get("type", "")).strip()
        content = str(c.get("content", "")).strip()
        refs = tuple(str(r).strip() for r in _as_list(c.get("grounding_refs")) if str(r).strip())
        aw = c.get("applies_when")
        applies_when = aw if isinstance(aw, dict) and aw else dict(default_match)
        cid = _claim_id(skill_id, ctype, content)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(Claim(id=cid, applies_when=applies_when, type=ctype, content=content,
                         grounding_refs=refs, provenance=skill_id, tier="candidate",
                         evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [],
                                   "fail_count": 0, "demotions": []}))
    return out


def extract_to_store(skills, model, resolver, *, denylist=None,
                     existing=None) -> tuple[dict[str, Claim], list[tuple[Claim, GroundCheck]]]:
    """Decompose every feedstock Skill -> candidate Claims, ground-check each (A2), and MERGE the survivors
    into the store dict at tier=candidate. Returns (admitted_store, rejected[(claim, check)]). Oracle-blind:
    grounding hits the atlas via `resolver`, never the oracle. Unique-id well-formedness is enforced at the
    store layer via setdefault (content-derived ids are stable, so a re-extract keeps the first)."""
    store: dict[str, Claim] = dict(existing or {})
    rejected: list[tuple[Claim, GroundCheck]] = []
    for skill in skills:
        for claim in claims_from_skill(skill, model):
            chk = check_claim_grounded(claim, resolver, denylist=denylist)
            if not chk.grounded:
                rejected.append((claim, chk))
                continue
            store.setdefault(claim.id, claim)
    return store, rejected
```

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_extract.py -q`.

5. **Write the failing CLI test** `tests/kb/test_cli_kb_extract.py`:

```python
"""`gloop kb-extract` composition-root wrapper: LLM-propose (scripted CannedModel) -> tolerant parse ->
ground-check -> claims.json. Hermetic — monkeypatches the model + resolver SEAMS (cli._extract_model /
cli._extract_resolver) so no network / no real atlas is touched; exercises the real extract_to_store +
check_claim_grounded + claims.json write path over a 1-skill feedstock corpus."""
import json

import groundloop.cli as cli
from groundloop.adapters.mock.model import CannedModel
from groundloop.kb.claim import load_claims

_SEED = '''
[[skill]]
id = "native-null-deref-segv"
provenance = "authored"
guidance = """
Signature: SIGSEGV tombstone.
Localize: the native translation unit.
Fix: guard the nativePtr handle.
"""

[skill.match]
any_text = ["sigsegv"]
'''

_RESPONSE = json.dumps({"claims": [
    {"type": "fix_step",
     "content": "Reject a 0 nativePtr handle at native method entry before dereferencing it.",
     "grounding_refs": ["GetLongField"], "applies_when": {"any_text": ["sigsegv"]}}]})


def test_kb_extract_writes_grounded_candidates(tmp_path, monkeypatch):
    seed = tmp_path / "feedstock.toml"
    seed.write_text(_SEED)
    out = tmp_path / "claims.json"

    monkeypatch.setattr(cli, "_extract_model", lambda: CannedModel({"default": _RESPONSE}))
    monkeypatch.setattr(cli, "_extract_resolver", lambda db: (lambda ref: ref == "GetLongField"))

    rc = cli.main(["kb-extract", "--skills-seed", str(seed), "--index-db", "unused.db", "--out", str(out)])
    assert rc == 0
    store = load_claims(str(out))
    assert len(store) == 1
    (claim,) = store.values()
    assert claim.tier == "candidate"
    assert claim.type == "fix_step"
    assert claim.grounding_refs == ("GetLongField",)
    assert claim.provenance == "native-null-deref-segv"


def test_kb_extract_drops_hallucinated_ref(tmp_path, monkeypatch):
    seed = tmp_path / "feedstock.toml"
    seed.write_text(_SEED)
    out = tmp_path / "claims.json"

    monkeypatch.setattr(cli, "_extract_model", lambda: CannedModel({"default": _RESPONSE}))
    monkeypatch.setattr(cli, "_extract_resolver", lambda db: (lambda ref: False))   # nothing resolves

    rc = cli.main(["kb-extract", "--skills-seed", str(seed), "--index-db", "unused.db", "--out", str(out)])
    assert rc == 0
    assert load_claims(str(out)) == {}          # the sole candidate failed grounding -> store empty
```

6. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_cli_kb_extract.py -q` → fails on `argument --command: invalid choice: 'kb-extract'` (subparser not yet registered).

7. **Implement the CLI wiring in** `groundloop/cli/__init__.py`. Add the two seams + handler as module-level functions (place them near the other `_run_*` handlers, e.g. just before `_run_compare`):

```python
def _extract_model():
    """The LLM proposer for kb-extract: live GatewayModel when KLOOP_PRODUCE_API_KEY is set, else a no-op
    CannedModel (hermetic tests monkeypatch this seam to a scripted CannedModel). Mirrors _run_fixeval's
    model gate. Implementer-verify (confirmed in _run_fixeval): GatewayModel(base_url, api_key, model)."""
    import os
    if os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
        from groundloop.adapters.model.gateway import GatewayModel
        from groundloop.config.settings import Settings
        s = Settings.load()
        return GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
    print("gloop kb-extract: no KLOOP_PRODUCE_API_KEY — hermetic canned model (proposes 0 claims).")
    return CannedModel({"default": ""})


def _extract_resolver(index_db: str):
    """The fleet-wide atlas existence probe for the ground-check (hermetic tests monkeypatch this seam)."""
    from groundloop.engines.atlas.store import Store
    from groundloop.kb.claim_ground import atlas_resolver
    return atlas_resolver(Store(index_db))


def _run_kb_extract(args) -> int:
    """Decompose each feedstock Skill's prose into candidate Claims (LLM PROPOSES), ground-check every
    candidate against the atlas (existence) + the leak red-test (oracle-blind), and MERGE survivors into the
    claim store at tier=candidate. The LLM is a proposer only; grounding admits."""
    from groundloop.kb.claim import CLAIMS_PATH, load_claims, save_claims
    from groundloop.kb.extract import extract_to_store
    from groundloop.kb.validate import SEED_PATH as KB_SEED
    from groundloop.kb.validate import load_corpus

    seed = args.skills_seed or KB_SEED
    out = args.out or CLAIMS_PATH
    skills = load_corpus(seed)
    existing = load_claims(out)
    store, rejected = extract_to_store(skills, _extract_model(), _extract_resolver(args.index_db),
                                       existing=existing)
    save_claims(out, store)
    admitted = len(store) - len(existing)
    print(f"kb-extract: {len(skills)} skill(s) -> {admitted} new candidate claim(s), "
          f"{len(rejected)} rejected -> {out}")
    for claim, chk in rejected:
        print(f"  drop {claim.id}: {', '.join(chk.reasons)}")
    return 0
```

Register the subparser inside `build_parser()` (e.g. after the `kb-distill` (`kds`) block):

```python
    kex = sub.add_parser("kb-extract",
                         help="decompose feedstock Skills -> candidate Claims (LLM propose + ground-check)")
    kex.add_argument("--skills-seed", dest="skills_seed", default=None,
                     help="feedstock corpus TOML (default: groundloop/kb/data/aaos_kb_seed.toml)")
    kex.add_argument("--index-db", required=True, help="atlas.db for the grounding existence check")
    kex.add_argument("--out", default=None,
                     help="claim store JSON to merge into (default: groundloop/kb/data/claims.json)")
```

Add the dispatch line inside `main()` (next to the other `kb-*` branches):

```python
    if args.cmd == "kb-extract":
        return _run_kb_extract(args)
```

8. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_cli_kb_extract.py -q`, then the full suite `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check groundloop tests`.

9. **Commit:** `feat(kb): gloop kb-extract — LLM decompose Skills -> grounded candidate Claims (Phase A3)` with the co-author trailer.

**Phase A exit state:** `Claim` + `claims.json` store, the oracle-blind ground-check, and `gloop kb-extract` all land; running `gloop kb-extract --index-db <atlas>` decomposes the 12 feedstock Skills into `tier=candidate` claims filtered by existence + leak. Nothing injects into a fix yet — Phase B wires `ClaimRegistry` + `render_claims` into the plan prompt and records `fired_claims`.

## Phase B — Claim-aware runtime injection

Wires the claim path from Phase A (`Claim` + `claims.json` + `load_claims`) into the live fix loop: a `ClaimRegistry` that selects grounded claims by predicate + tier floor, a `render_claims` preamble grouped by advice type, a composition-root-only `--claims {none,candidate,validated}` fix arm that feeds that preamble into the `PlanningFixEngine` plan prompt, and `fired_claims` attribution feedstock in `FixRecord` + the plan archive. The existing `--skills` path stays byte-identical (back-compat is an explicit test in every task).

**Execution order within Phase B:** B1 → B2 → B3 → B4 (linear; no forward references). B3 names the `selected_claims` local that B4 threads into `FixRecord.fired_claims`.

**Dependency:** Phase A must have shipped `groundloop/kb/claim.py` exposing the frozen `Claim`, `load_claims(path)->dict[str, Claim]` (keyed by claim id — iterate `.values()` for the `Claim`s), and `CLAIMS_PATH` (= `groundloop/kb/data/claims.json`). Every B task carries an implementer-verify note where it leans on a Phase-A or reuse signature.

**Design note carried by all B tasks — the localize/fix boundary (CLAUDE.md gotcha):** claims inject ONLY into the PLAN preamble (fix stage, via `PlanningFixEngine._plan`); they do NOT contribute to the localize `_skill_query`. `localize` runs *before* fix `propose`, so claims are `file_recall@1`-invariant by construction. Grade claim lift on `resolved_rate_strict` / `plan_target_recall@1` / `plan_groundedness` / `fabrication_rate` (via `accept_grounded`), never `file_recall@1`. This is deliberate scoping, not an omission.

**GUARDRAILS (apply to every B task):** never edit `groundloop/core/`; never alter the atlas SQLite schema; keep the loop oracle-blind (selection reads only the loop-visible `SkillCtx` built from signals+ticket+predicted; the offline grade stays the sole oracle read); build only what the task specifies (YAGNI); TDD (write failing test → run → implement → pass → commit); full suite green (`.venv/bin/python -m pytest -q`) + ruff clean (`.venv/bin/ruff check groundloop tests`, line length 110) before each commit; end the commit message with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### B1 — `ClaimRegistry`: load `claims.json` + `select(ctx, tier_floor)` (predicate + tier gate + optional bge-m3 rerank)

**New module:** `groundloop/kb/registry.py`. **New test:** `tests/kb/test_registry.py`.

Mirrors `adapters/skills/mock.MockSkillRegistry.select` (predicate stage → optional embed rerank) but (a) compiles each claim's `applies_when` dict at construction via `compile_predicate`, (b) gates on the tier ladder, and (c) reranks over `claim.content` instead of `skill.guidance`.

**TDD — write these failing first (construct `Claim` inline; `SkillCtx` directly, mirroring `tests/skills/test_mock_registry.py`):**
- `select` fires a claim whose `applies_when={"any_text":["segv"]}` on a ctx whose `text` contains `segv`; a non-matching claim stays silent; empty match → `[]` (→ empty preamble → byte-identical to the none arm).
- **Tier floor:** a `tier="candidate"` claim is EXCLUDED at `tier_floor="validated"` but INCLUDED at `tier_floor="candidate"`; a `tier="validated"` claim is included at both; a `tier="canonical"` claim is included at both.
- **Retired never fires:** a `tier="retired"` claim (a tier outside `TIERS`) is filtered before the `TIERS.index` comparison and never selected, at any floor.
- Predicate-only order is deterministic (same input → same id order across two calls).
- Optional embedder (`StubEmbedder`) rerank is deterministic and capped to `top_k` (mirror `test_optional_embedder_rerank_is_deterministic_and_capped`).

**Real code (`groundloop/kb/registry.py`):**
```python
"""ClaimRegistry — the claim-path analogue of adapters/skills/mock.MockSkillRegistry. `select(ctx,
tier_floor)` = predicate filter (compiled from each claim's applies_when) + a tier-ladder gate
(TIERS-ranked) + an OPTIONAL bge-m3 rerank over claim.content (gated: pass an embedder). Reads ONLY
its claim store + the loop-visible SkillCtx — never the oracle. Candidate claims are eval-only; the
production floor is `validated` (spec §5.3/§5.6)."""
from __future__ import annotations

import math

from groundloop.kb.claim import CLAIMS_PATH, Claim, load_claims
from groundloop.kb.lifecycle import TIERS
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate


def _cos(a: list[float], b: list[float]) -> float:            # mirrors MockSkillRegistry._cos
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class ClaimRegistry:
    def __init__(self, claims: list[Claim], *, embedder=None, top_k: int = 3):
        self.claims = list(claims)
        self.embedder = embedder
        self.top_k = top_k
        # compile each claim's applies_when ONCE (closed-vocab predicate; bad key/regex -> ValueError)
        self._preds = [compile_predicate(c.applies_when) for c in self.claims]
        # embed content ONCE (pinned bge-m3; query==index) — only when an embedder is attached
        self._cvecs = self.embedder.embed([c.content for c in self.claims]) if self.embedder else None

    @classmethod
    def load(cls, path: str = CLAIMS_PATH, *, embedder=None, top_k: int = 3) -> "ClaimRegistry":
        return cls(load_claims(path), embedder=embedder, top_k=top_k)

    def select(self, ctx: SkillCtx, tier_floor: str) -> list[Claim]:
        floor = TIERS.index(tier_floor)                       # ValueError if caller passes a non-TIER
        hits = [(i, c) for i, c in enumerate(self.claims)
                if c.tier in TIERS and TIERS.index(c.tier) >= floor and self._preds[i](ctx)]
        if self.embedder is None or not hits:
            return [c for _, c in hits]                        # hermetic default (predicate + tier only)
        qvec = self.embedder.embed([ctx.text or " ".join(ctx.tokens())])[0]   # bge-m3 rerank (gated)
        scored = sorted(hits, key=lambda p: (-_cos(qvec, self._cvecs[p[0]]), self.claims[p[0]].id))
        return [c for _, c in scored[: self.top_k]]
```

**Implementer-verify (reuse):**
- `groundloop.kb.claim.{Claim,load_claims,CLAIMS_PATH}` — from Phase A. Confirm `Claim` carries `.applies_when: dict`, `.type`, `.content`, `.tier`, `.id`; confirm the store constant is named `CLAIMS_PATH` (adjust import if Phase A named it otherwise) and `load_claims` returns `[]` for a missing/empty store (the honest cold-start — an empty `validated` set selects nothing).
- `skills/predicate.compile_predicate(spec:dict)->Callable[[SkillCtx],bool]` — closed vocab `_VALID` (`always`, `repo_in`, `any_text`/`all_text`, `any_{packages,classes,methods,symbols,libraries,errors}[_regex]`); raises `ValueError` on an unknown key or bad regex at construction. Confirmed present.
- `skills/ctx.SkillCtx` (`.text/.signals/.repo/.tokens()`) — confirmed oracle-blind.
- `kb/lifecycle.TIERS == ("candidate","applied","validated","canonical")` — confirmed; `retired` is intentionally NOT in `TIERS`, which is why the `c.tier in TIERS` guard also excludes retired claims.
- `engines/atlas/embed.StubEmbedder` — offline deterministic vectors for the hermetic rerank test; `embedder.embed(list[str])->list[list[float]]`. Confirm the embed shape.

**Commit:** `feat(kb): ClaimRegistry — predicate + tier-floor select with gated bge-m3 rerank`.

---

### B2 — `render_claims(claims)`: preamble grouped by advice type

**New module:** `groundloop/kb/render.py`. **New test:** `tests/kb/test_render.py`.

Deprecates `skills/base.render_skills` for the claim path (spec §6). Emits a preamble grouped by the 3 advice types, in a fixed `localize_hint → fix_step → api_requirement` order, preserving selection order within each group. Shape mirrors `render_skills` (leading `"\n\n# …"`, `""` on empty) so it concatenates cleanly after a skill preamble and an empty result is byte-identical to no injection.

**TDD — write these failing first (construct `Claim` inline):**
- `render_claims([]) == ""`.
- A `localize_hint` + a `fix_step` claim → output starts with `"\n\n# Grounded claims"`, contains both group headers, and the localize header precedes the fix header (fixed order regardless of input order).
- Only `fix_step` present → only the fix-step group header appears, still led by `"# Grounded claims"`.
- An off-taxonomy `type` (not one of the 3) contributes nothing; if it is the ONLY claim, `render_claims` returns `""` (defensive — the closed taxonomy is enforced at Phase-A ground-check; render must not emit an untyped block).
- Each claim's `content` appears as a bulleted line under its group.

**Real code (`groundloop/kb/render.py`):**
```python
"""render_claims — compose selected Claims into the PLAN-prompt preamble, grouped by advice type.
The claim-path replacement for skills/base.render_skills (spec §6): only a claim's `content` reaches
the prompt (never raw Skill prose). Empty in -> "" (byte-identical to no injection); shape mirrors
render_skills so it concatenates after a skill preamble."""
from __future__ import annotations

from groundloop.kb.claim import Claim

# Fixed render order + human header per advice type (spec §5.3: "known localize hints / fix steps /
# required APIs for this crash class"). Types outside this closed set are dropped (defensive).
_TYPE_HEADS: tuple[tuple[str, str], ...] = (
    ("localize_hint", "Known localize hints for this crash class"),
    ("fix_step", "Known fix steps for this crash class"),
    ("api_requirement", "Required APIs for this crash class"),
)


def render_claims(claims: list[Claim]) -> str:
    if not claims:
        return ""
    blocks: list[str] = []
    for type_key, head in _TYPE_HEADS:
        items = [c for c in claims if c.type == type_key]     # preserves selection order within a group
        if not items:
            continue
        lines = "\n".join(f"- {c.content}" for c in items)
        blocks.append(f"## {head}\n{lines}")
    if not blocks:                                            # only off-taxonomy claims -> no injection
        return ""
    return "\n\n# Grounded claims\n" + "\n\n".join(blocks)
```

**Implementer-verify (reuse):** `groundloop.kb.claim.Claim` (`.type`, `.content`) from Phase A. Confirm `type` values are exactly `"localize_hint"|"fix_step"|"api_requirement"`.

**Commit:** `feat(kb): render_claims — type-grouped claim preamble (deprecates render_skills on the claim path)`.

---

### B3 — Wire the claims path into fixeval: the `--claims {none,candidate,validated}` arm

**Edit:** `groundloop/fixeval/runner.py` (`FixEvalRunner.__init__` + `_one`), `groundloop/cli/__init__.py` (`_run_fixeval` + a new `_load_claims` helper + the `fixeval` subparser). **New tests:** `tests/fixeval/test_runner_claims.py`, `tests/fixeval/test_cli_claims.py`.

Composition-root-only behavior swap: the runner gains a `claims` registry knob + a `claims_tier_floor` string; the CLI maps `--claims candidate/validated` to a registry at the matching floor and `--claims none` to `None`. The claim preamble is concatenated AFTER the skill preamble and fed once through the existing `fixer.with_preamble(...)` (which both `PlanningFixEngine` and `ModelPatchEngine` expose). **Back-compat:** `claims=None` ⇒ the claim preamble is `""` ⇒ the composed preamble equals the skill preamble exactly ⇒ byte-identical to today.

**TDD — write these failing first:**
- **Injection (runner, `--fixer plan` path via the `_Capture`/spy model, mirror `tests/fixeval/test_skill_injection.py`):** a `FixEvalRunner(..., claims=<registry with a fix_step claim that fires>, claims_tier_floor="candidate")` makes the fixer see a prompt containing `"# Grounded claims"` and the claim's `content`.
- **Tier gate through the runner:** the same candidate-tier claim is NOT injected when `claims_tier_floor="validated"` (no `"# Grounded claims"` in any prompt).
- **Localize invariance:** `localize` receives the same `skill_query` regardless of `claims` (claims never feed `_skill_query`) — assert the injected preamble reaches the PLAN prompt but the localize query is unchanged vs `claims=None` (or, minimally, that a claims-only run produces the same `locations` as a none run on the fixture).
- **Back-compat:** `claims=None` with `skills=MockSkillRegistry.load()` reproduces the exact `test_skills_mock_injects_native_playbook` behavior (skill preamble present, no `"# Grounded claims"`); `claims=None, skills=None` → no preamble at all.
- **CLI (mirror `tests/fixeval/test_cli_skills.py`):** `main(["fixeval", *common, "--claims", "candidate", ...]) == 0` and `"--claims", "validated"` both run; `--claims none` (default) leaves the run identical to the pre-B3 baseline. A `_load_claims` unit test: `"none"→(None, <floor>)`, `"candidate"→(ClaimRegistry, "candidate")`, `"validated"→(ClaimRegistry, "validated")` (monkeypatch/point at a tiny `claims.json` fixture so it does not depend on the shipped store).

**Real code — `groundloop/fixeval/runner.py`:**

Add imports and constructor knobs:
```python
from groundloop.kb.registry import ClaimRegistry   # noqa: (used via type only; runtime knob is duck-typed)
from groundloop.kb.render import render_claims
```
```python
    def __init__(self, *, issues, estate, catalog, tau_margin: float, tau_score: float,
                 max_refine: int = 1, skills=None, claims=None, claims_tier_floor: str = "validated"):
        ...
        self.skills = skills                     # a SkillRegistry or None (the `--skills` arm knob)
        self.claims = claims                     # a ClaimRegistry or None (the `--claims` arm knob)
        self.claims_tier_floor = claims_tier_floor   # TIERS floor: `candidate` in eval, `validated` in prod
```

Replace the skill-injection block in `_one` (currently lines ~99–110) with a version that builds ONE ctx, composes both preambles, and keeps the claim path oracle-blind and localize-invariant:
```python
        f = fixer
        skill_query = ""
        fired: tuple = ()
        selected_claims: list = []               # B4 captures ids off this local
        ctx = None
        if self.skills is not None or self.claims is not None:
            ctx = build_ctx(signals, ticket, predicted)       # loop-visible only (oracle-blind)
        skill_pre = ""
        if self.skills is not None:
            selected = self.skills.select(ctx)
            fired = tuple(getattr(s, "id", "") for s in selected)
            skill_pre = render_skills(selected)
            skill_query = _skill_query(selected)              # claims DO NOT feed the localize query
        claim_pre = ""
        if self.claims is not None:
            selected_claims = self.claims.select(ctx, self.claims_tier_floor)
            claim_pre = render_claims(selected_claims)         # PLAN-prompt preamble only
        preamble = skill_pre + claim_pre                       # skills first; each is "" when its arm is off
        if preamble:
            f = fixer.with_preamble(preamble)
```
(The rest of `_one` — `_cost`, `materialize`, `localize(..., skill_query=skill_query)`, `_do_propose`, refine, `pmeta`, the abstain `rec(...)` paths — is unchanged in B3. `fired_claims` recording is added in B4.)

**Real code — `groundloop/cli/__init__.py`:**

New helper beside `_load_skills`:
```python
def _load_claims(kind: str, embedder):
    """Compose the fixeval claim arm. kind: none|candidate|validated.
    none -> (None, "validated"); candidate -> (registry, "candidate") [EVAL floor];
    validated -> (registry, "validated") [PRODUCTION floor]. The registry always loads the full
    claim store (groundloop/kb/data/claims.json); the tier floor is what gates candidates out of prod."""
    if kind == "none":
        return None, "validated"
    from groundloop.kb.registry import ClaimRegistry
    return ClaimRegistry.load(embedder=embedder), kind
```

In `_run_fixeval`: extend the embedder gate to fire for either arm, build the claims arm, and pass both knobs to the runner:
```python
    if (args.skills != "none" or args.claims != "none") and os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        ...   # build GatewayEmbedder exactly as today
    skills = _load_skills(args.skills, args.skills_seed, embedder)
    claims, claims_tier_floor = _load_claims(args.claims, embedder)
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills, claims=claims, claims_tier_floor=claims_tier_floor)
```

New subparser arg on `fx` (the `fixeval` parser), analogous to `--skills`:
```python
    fx.add_argument("--claims", choices=["none", "candidate", "validated"], default="none",
                    help="claim-KB arm (claims.json): none | candidate (EVAL floor — includes "
                         "unvalidated candidates) | validated (PRODUCTION floor — validated+canonical only)")
```

**Implementer-verify (reuse):**
- `adapters/fix/planning.PlanningFixEngine.with_preamble(preamble)->clone` AND `adapters/fix/model_patch.ModelPatchEngine.with_preamble(preamble)->clone` — both confirmed present; `_plan`/`propose` prepend `self.preamble + "\n\n" + prompt`, so a composed skill+claim preamble lands at the top of the plan prompt. Confirmed.
- `skills/ctx.build_ctx(signals,ticket,predicted)->SkillCtx` — confirmed oracle-blind; safe to build once and share between `skills.select` and `claims.select`.
- `MockSkillRegistry.select(ctx)` takes ONE arg; `ClaimRegistry.select(ctx, tier_floor)` takes TWO — do not swap them.
- The env-driven `GatewayEmbedder` block already present in `_run_fixeval` — reuse verbatim; only widen its guard condition.
- Existing `FixEvalRunner` callers that omit `claims` (`kb/ab.py`, `_build_distill_run_fn`) keep working via the `claims=None` default — confirm they are unaffected (default-arg back-compat).

**Commit:** `feat(fixeval): --claims {none,candidate,validated} arm — claim preamble into the plan prompt`.

---

### B4 — `fired_claims` on `FixRecord` + in the archive payload

**Edit:** `groundloop/fixeval/runner.py` (`FixRecord` field + capture in `_one`), `groundloop/fixeval/archive.py` (payload key). **Edit tests:** `tests/fixeval/test_archive.py` (add cases), plus a `FixRecord` default assertion.

Closes the attribution-feedstock loop: the per-claim ids that fired on a case are recorded on the record and persisted next to `fired_skills`, so Phase-C `screen_claims`/`lofo_claims` can read the archive and attribute lift per claim. Mirrors the existing `fired_skills` plumbing exactly.

**TDD — write these failing first (mirror `test_archive_captures_fired_skills` + `test_fixrecord_fired_skills_defaults_empty`):**
- `FixRecord(...)` without `fired_claims` defaults to `()`.
- `archive_plans([rec_with_fired_claims=("c-seg",)])` writes a payload whose `payload["fired_claims"] == ["c-seg"]` (and `fired_skills` still present, independent).
- **Runner end-to-end:** on the B3 injection fixture, the returned `FixRecord.fired_claims` contains the fired claim's id; on a case where no claim fires, `fired_claims == ()`.

**Real code — `groundloop/fixeval/runner.py`:**

Add the field to `FixRecord` (after `fired_skills`):
```python
    fired_skills: tuple[str, ...] = ()
    fired_claims: tuple[str, ...] = ()
```

Capture ids off the B3 `selected_claims` local, and thread through the same three paths `fired_skills` uses:
```python
        fired_claims = tuple(getattr(c, "id", "") for c in selected_claims)   # after selection in _one
```
- localize-abstain early return: add `fired_claims=fired_claims` alongside `fired_skills=fired`.
- `pmeta = dict(plan=plan_dict, groundedness=..., replans=..., fired_skills=fired, fired_claims=fired_claims)`.
- The pre-match `rec(abstain_reason="no_repo_match")` path selects nothing → `fired_claims` defaults to `()` via the `FixRecord` field default (leave it; do not pass it there).

**Real code — `groundloop/fixeval/archive.py`:**

Add one key next to `fired_skills` in the payload dict:
```python
            "fired_skills": list(getattr(r, "fired_skills", [])),
            "fired_claims": list(getattr(r, "fired_claims", [])),
```

**Implementer-verify (reuse):**
- `fixeval/archive.archive_plans(records, out_dir)` — payload is built per record with `getattr(r, "fired_skills", [])`; add the parallel `fired_claims` key the same defensive way (tolerates records predating the field). Confirmed shape.
- `ARCHIVE_SCHEMA` — this is an additive optional key; do NOT bump the schema (readers use `.get`). Confirm no schema-version consumer rejects unknown keys.
- The `rec(**kw)` helper base dict in `_one` omits both `fired_skills` and `fired_claims`, relying on the `FixRecord` defaults — keep that; only the localize-abstain and `pmeta` paths pass `fired_claims` explicitly.

**Commit:** `feat(fixeval): fired_claims on FixRecord + archive payload (per-claim attribution feedstock)`.

## Phase C — Per-claim attribution + lifecycle

Phase C closes the retain-loop: it turns the `fired_claims` plan archive (Phase B) into a per-claim
verdict. A cheap, oracle-blind **archive screen** shortlists promising *and* suspicious candidates; a
budgeted **LOFO-confirm vs a per-claim placebo** (spec §5.4) measures each shortlisted claim causally; the
two-sided **`accept_grounded`** gate + the **`apply_verdict`** ladder promote or retire **one claim at a
time** (spec §5.5, §11 q3). This is the piece the whole-corpus `kb-promote` structurally could not do:
retain claim A and retire claim B independently. Reuses `kb/distill/lofo.py` (the ablation pattern),
`kb/placebo.py` (the placebo pattern), `fixeval/compare.{accept_grounded,compare_metrics,compare}`, and
`kb/lifecycle.{TIERS,apply_verdict}` — repurposed onto claims.

**Shared-contract anchors (already used by Phases A/B — do not rename):** `Claim(id, applies_when, type,
content, grounding_refs, provenance, tier, evidence)` in `groundloop/kb/claim.py`, stored via
`load_claims`/`save_claims` (dict keyed by claim id); `evidence` is the bookkeeping bag (`measured_lift`,
`wilson95`, `validating_case_ids`, `fail_count`, `demotions`, `evidence_context`). The plan archive
(`fixeval/archive.archive_plans`) writes per-case `<case>__<arm>.json` payloads under `<out>/plans/` that
carry `fired_claims` (list of claim ids) + `outcome.groundedness` (the per-case, **oracle-blind** grounded
signal the screen reads). `kb/lifecycle.TIERS == ("candidate","applied","validated","canonical")` (`retired`
is intentionally NOT in `TIERS`); `apply_verdict(rec, passed, *, hysteresis=2)` reads `.tier`/`.fail_count`/
`.demotions` and returns a new record via `dataclasses.replace`. Prod injects tier≥`validated`; eval injects
tier≥`candidate` (via the Phase-B `ClaimRegistry.select(ctx, tier_floor)`).

**Execution order:** C1 → C2 → C3 → C4 (linear). C4's driver consumes C1 (`build_claim_placebo`), C2
(`screen_claims`/`load_archive`), and C3 (`lofo_claims`); all three are standalone reusable primitives.

**GUARDRAILS (apply to every C task):** never edit `groundloop/core/`; never alter the atlas SQLite schema;
keep the loop **oracle-blind** — the SCREEN reads only the archive's oracle-blind per-case `groundedness`
(never an oracle-graded metric, so it needs no new spend and no oracle read); the LOFO-CONFIRM re-runs the
plan-format fix eval whose `grade_fix_all` is the **sole, offline** oracle read (the loop's selection /
injection never see the oracle); build only what the task specifies (YAGNI); strict TDD (write failing test
→ run → confirm it fails → implement complete code → run → pass → commit); full suite green
(`.venv/bin/python -m pytest -q`) + ruff clean (`.venv/bin/ruff check groundloop tests`, line length 110)
before each commit; end every commit message with the trailer
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### C1 — `build_claim_placebo`: one length-matched placebo Claim per candidate

**New module:** `groundloop/kb/claim_placebo.py`. **New test:** `tests/kb/test_claim_placebo.py`.

The claim-granular analogue of `kb/placebo.build_placebo` (spec §5.4, "reuse `kb/placebo.py` at claim
granularity"). For each candidate Claim it emits one placebo Claim with the **same `applies_when` + `type`**
(so it fires on the identical cases at the same tier floor), `id = "placebo-" + <id>`, **empty
`grounding_refs`** (it cites nothing), and a **length-matched, deliberately irrelevant** `content` drawn from
owner-token-free filler (leak-safe by construction — mirrors `placebo._FILLER`). It is the null control for
the LOFO-confirm: any lift a real claim shows over its placebo isolates the claim's `content` as the
treatment, ruling out the confound of merely injecting *some* claim on those cases.

**Files**
- create `groundloop/kb/claim_placebo.py`
- create `tests/kb/test_claim_placebo.py`

**Steps**

1. **Write the failing test** `tests/kb/test_claim_placebo.py`:

```python
"""Per-claim placebo control (Phase C1). Mirrors tests for kb/placebo.build_placebo but at Claim
granularity: one placebo Claim per candidate, SAME applies_when + type (fires on the identical cases),
empty grounding_refs, length-matched IRRELEVANT content that is leak-safe vs the real owner denylist."""
from groundloop.kb.claim import Claim
from groundloop.kb.claim_placebo import build_claim_placebo
from groundloop.kb.validate import owner_denylist


def _claim(cid="c-seg", **over) -> Claim:
    base = dict(id=cid, applies_when={"any_text": ["sigsegv", "segv_maperr"]}, type="fix_step",
                content="Reject a 0 nativePtr handle at native method entry before dereferencing it.",
                grounding_refs=("GetLongField",), provenance="native-null-deref-segv",
                tier="candidate", evidence={})
    base.update(over)
    return Claim(**base)


def test_one_placebo_per_claim_same_predicate_and_type():
    src = {"c-seg": _claim()}
    pl = build_claim_placebo(src)
    assert set(pl) == {"placebo-c-seg"}
    p = pl["placebo-c-seg"]
    assert p.id == "placebo-c-seg"
    assert p.applies_when == src["c-seg"].applies_when      # fires on the IDENTICAL cases
    assert p.type == src["c-seg"].type                      # same advice slot (grouped identically)
    assert p.grounding_refs == ()                           # cites nothing
    assert p.tier == "candidate"                            # injectable at the eval floor (same as source)


def test_placebo_content_is_length_matched_and_leak_safe():
    c = _claim(content="Guard the native peer handle before the JNI call resolves the field id here now.")
    p = build_claim_placebo({c.id: c})["placebo-" + c.id]
    assert p.content != c.content                           # different wording (the treatment isolate)
    assert len(p.content) == max(len(c.content), 40)        # exactly length-matched (floored)
    hay = p.content.lower()
    assert not any(tok in hay for tok in owner_denylist())  # no fleet-owner leak


def test_short_content_is_floored_to_forty_chars():
    p = build_claim_placebo({"c": _claim("c", content="tiny")})["placebo-c"]
    assert len(p.content) == 40                             # floor so a 4-char claim still gets real filler


def test_empty_input_is_empty_output():
    assert build_claim_placebo({}) == {}
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_claim_placebo.py -q` →
   `ModuleNotFoundError: groundloop.kb.claim_placebo`.

3. **Implement** `groundloop/kb/claim_placebo.py` (complete):

```python
"""Per-claim placebo control for the claim-attribution retain-loop (design spec §5.4). The Claim-granular
analogue of kb/placebo.build_placebo: one placebo Claim per candidate — SAME applies_when + type (so it
fires on the identical cases at the same tier floor), id prefixed 'placebo-', EMPTY grounding_refs, and a
length-matched, deliberately IRRELEVANT content. It is the null arm of the per-claim LOFO-confirm: any lift
a real claim shows over its placebo isolates the claim's CONTENT as the treatment, ruling out the confound
of merely injecting some claim on those cases. The filler is owner-token-free (leak-safe by construction)."""
from __future__ import annotations

from groundloop.kb.claim import Claim

# Neutral, owner-token-free filler (mirrors kb/placebo._FILLER; verified leak-safe vs FLEET_OWNER_TOKENS in
# the C1 test). Trimmed to the reference content length so treatment and control differ ONLY in wording.
_FILLER = (
    "placebo control text of matched length that conveys no diagnostic or corrective information and "
    "points at nothing in particular so the treatment and control differ solely in the wording injected "
)


def _matched_filler(reference: str, *, floor: int = 40) -> str:
    """Owner-token-free filler cut to EXACTLY max(len(reference), floor) characters."""
    n = max(len(reference), floor)
    reps = (n // len(_FILLER)) + 1
    return (_FILLER * reps)[:n]


def build_claim_placebo(claims: dict[str, Claim]) -> dict[str, Claim]:
    """Return {placebo_id: placebo Claim}, one per input claim. Each placebo copies applies_when + type
    VERBATIM (fires on the identical cases at the same tier floor) under id='placebo-'+<id>, but carries
    empty grounding_refs and length-matched irrelevant content. Mirrors kb/placebo.build_placebo."""
    out: dict[str, Claim] = {}
    for cid, c in claims.items():
        pid = "placebo-" + cid
        out[pid] = Claim(
            id=pid,
            applies_when=dict(c.applies_when or {}),          # verbatim predicate -> same firing set
            type=c.type,                                      # same advice slot (render groups it identically)
            content=_matched_filler(c.content or ""),
            grounding_refs=(),                                # cites nothing
            provenance=f"placebo control paired to claim {cid} (length-matched, irrelevant content)",
            tier=c.tier,                                      # injectable wherever the source claim is
            evidence={},
        )
    return out
```

**Implementer-verify (reuse):**
- `groundloop.kb.claim.Claim` (from Phase A) carries exactly `id, applies_when, type, content,
  grounding_refs, provenance, tier, evidence`; `evidence` has a `default_factory=dict`. Confirmed.
- `groundloop.kb.validate.owner_denylist()` returns the `FLEET_OWNER_TOKENS`-derived denylist set the corpus
  leak red-test uses (referenced by `kb/placebo.py`'s module doc + `kb/claim_ground.py` in Phase A2). The
  test asserts `_FILLER` contains none of it — if a token collides, edit `_FILLER` (keep it generic English).

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_claim_placebo.py -q`, then the full
   suite `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check groundloop tests`.

5. **Commit:** `feat(kb): build_claim_placebo — per-claim length-matched placebo control (Phase C1)` with the
   co-author trailer.

---

### C2 — `screen_claims` + `load_archive`: the cheap, oracle-blind directional screen

**New module:** `groundloop/kb/attribute.py`. **New test:** `tests/kb/test_attribute_screen.py`.

The Stage-1 archive **screen** (spec §5.4, §11 q3 — "to be pinned in the plan with a concrete formula"). It
reads the accumulated plan archive and computes a per-claim directional statistic; the LOFO-confirm (C3/C4)
then spends only on the shortlist. **Correlational only — it prioritizes, never promotes.** It is
**oracle-blind by construction:** it reads the archive's per-case `outcome.groundedness` (the fraction of a
plan's cited entities that resolve in the atlas — code reality, computed with no oracle read), **never** an
oracle-graded metric like `plan_target_recall@1`. So it needs no new fix-loop spend.

**Pinned formula.** For each claim `c` present in the store:
`screen_lift(c) = mean(groundedness over cases where c FIRED) − mean(groundedness over cases where c did NOT
fire)` (the comparable within-archive baseline). A claim with no firing case or no baseline case has no
contrast → skipped (unattributable from this archive). Shortlist = claims with `|screen_lift| ≥ threshold`
(promising **or** suspicious), sorted by `|screen_lift|` desc so a downstream `--max-lofo` cap keeps the
strongest signals. (Refinement, deferred: when the archive also carries a placebo arm run over the same
cases, the matched baseline is "same case in the placebo arm" rather than "any non-firing case" — a strictly
better control; the single-archive formula above is the concrete C2 default.)

**Files**
- create `groundloop/kb/attribute.py`
- create `tests/kb/test_attribute_screen.py`

**Steps**

1. **Write the failing test** `tests/kb/test_attribute_screen.py`:

```python
"""Cheap oracle-blind per-claim archive screen (Phase C2). Fixture archive = plan payloads shaped exactly
like fixeval/archive.archive_plans output (fired_claims + outcome.groundedness). Asserts the pinned
fired-vs-non-fired groundedness-delta formula shortlists BOTH promising and suspicious claims, skips
no-contrast claims, and that load_archive tolerates a missing dir + malformed files."""
import json

from groundloop.kb.attribute import load_archive, screen_claims
from groundloop.kb.claim import Claim


def _payload(case, fired, groundedness):
    return {"schema": 1, "case_id": case, "arm": "membership+logs", "predicted_repo": "r",
            "plan": {"steps": []}, "fired_skills": [], "fired_claims": list(fired),
            "outcome": {"groundedness": groundedness, "replans": 0, "abstained": False,
                        "patch_emitted": True, "patch_applies": True}}


def _claim(cid):
    return Claim(id=cid, applies_when={"any_text": ["x"]}, type="fix_step", content="c",
                 grounding_refs=(), provenance="p", tier="candidate", evidence={})


def test_screen_shortlists_promising_and_suspicious():
    archive = [_payload("a", ["c-good"], 0.9), _payload("b", ["c-good"], 0.8),
               _payload("c", ["c-bad"], 0.1), _payload("d", ["c-bad"], 0.2),
               _payload("e", [], 0.5), _payload("f", [], 0.5)]
    claims = {"c-good": _claim("c-good"), "c-bad": _claim("c-bad")}
    sl = screen_claims(archive, claims, threshold=0.1)
    assert set(sl) == {"c-good", "c-bad"}          # high-lift (promising) AND negative-lift (suspicious)


def test_threshold_filters_weak_signal():
    archive = [_payload("a", ["c1"], 0.55), _payload("b", [], 0.5)]   # lift = +0.05
    assert screen_claims(archive, {"c1": _claim("c1")}, threshold=0.1) == []
    assert screen_claims(archive, {"c1": _claim("c1")}, threshold=0.0) == ["c1"]


def test_no_contrast_claim_is_skipped():
    archive = [_payload("a", ["c1"], 0.9), _payload("b", ["c1"], 0.9)]  # c1 fires everywhere -> no baseline
    assert screen_claims(archive, {"c1": _claim("c1")}, threshold=0.0) == []


def test_load_archive_reads_payloads_and_tolerates_junk(tmp_path):
    d = tmp_path / "plans"
    d.mkdir()
    (d / "a__arm.json").write_text(json.dumps(_payload("a", ["c1"], 0.5)))
    (d / "b__arm.json").write_text(json.dumps(_payload("b", ["c2"], 0.4)))
    (d / "broken.json").write_text("{ not json")
    got = load_archive(str(d))
    assert {p["case_id"] for p in got} == {"a", "b"}       # malformed file skipped, not fatal


def test_load_archive_missing_dir_is_empty():
    assert load_archive("/no/such/plans/dir") == []
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_attribute_screen.py -q` →
   `ModuleNotFoundError: groundloop.kb.attribute`.

3. **Implement** `groundloop/kb/attribute.py` (the C2 slice — C3/C4 append to this same module):

```python
"""Staged per-claim attribution + lifecycle governance (design spec §5.4/§5.5). Three primitives:
  * screen_claims (C2) — a cheap, ORACLE-BLIND directional screen over the plan archive's per-case
    `groundedness` -> a shortlist of promising/suspicious claims (correlational; prioritizes, never
    promotes);
  * lofo_claims (C3) — leave-one-CLAIM-out ablation Δ (mirrors kb/distill/lofo.lofo_fragments);
  * attribute_and_govern (C4) — LOFO-confirm vs the per-claim placebo -> accept_grounded two-sided verdict
    -> apply_verdict per claim (promote/retire), bridged onto the Claim via a small ClaimRecord adapter.
The SCREEN reads only the archive (no oracle, no new spend); the CONFIRM re-runs the plan-format fix eval
whose grade_fix_all is the sole, offline oracle read. The loop stays oracle-blind throughout."""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterable
from pathlib import Path

from groundloop.kb.claim import Claim


def load_archive(plans_dir: str) -> list[dict]:
    """Load every per-case plan payload written by fixeval/archive.archive_plans (<dir>/*.json). A missing
    dir is an empty archive (nothing to attribute yet), not an error; a malformed file is skipped, not
    fatal — mirrors kb/provenance.load_sidecar's tolerance."""
    d = Path(plans_dir)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _case_groundedness(payload: dict) -> float | None:
    """The archive's per-case ORACLE-BLIND grounded signal (fraction of a plan's cited entities that resolve
    in the atlas). None when absent (e.g. an abstain-only case) -> excluded from the mean."""
    g = (payload.get("outcome") or {}).get("groundedness")
    return float(g) if isinstance(g, (int, float)) else None


def screen_claims(archive: Iterable[dict], claims: dict[str, Claim], *,
                  threshold: float = 0.0, min_fired: int = 1) -> list[str]:
    """Cheap oracle-blind directional screen (spec §5.4). Pinned formula, per claim:
        screen_lift = mean(groundedness | claim FIRED) - mean(groundedness | claim did NOT fire).
    Shortlist = claims with |screen_lift| >= threshold (promising OR suspicious), sorted by |screen_lift|
    desc (so a --max-lofo cap keeps the strongest signals). No firing case (< min_fired) or no baseline
    case -> no contrast -> skipped. Correlational only: it PRIORITIZES the LOFO shortlist, never promotes."""
    rows = list(archive)
    scored: list[tuple[float, str]] = []
    for cid in claims:
        fv = [g for g in (_case_groundedness(p) for p in rows
                          if cid in (p.get("fired_claims") or [])) if g is not None]
        bv = [g for g in (_case_groundedness(p) for p in rows
                          if cid not in (p.get("fired_claims") or [])) if g is not None]
        if len(fv) < min_fired or not bv:
            continue
        lift = sum(fv) / len(fv) - sum(bv) / len(bv)
        if abs(lift) >= threshold:
            scored.append((abs(lift), cid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [cid for _, cid in scored]
```

**Implementer-verify (reuse):**
- The archive payload shape is fixed by `fixeval/archive.archive_plans` (Phase B4 added `fired_claims`): each
  file carries `fired_claims: list[str]` and `outcome.groundedness: float`. Confirmed in `archive.py`.
- `groundedness` is oracle-blind — it is the plan-groundedness check (cited entities resolve in the atlas),
  computed with no oracle read, so screening on it keeps C2 oracle-blind (unlike `plan_target_recall@1`,
  which needs the oracle's expected files and therefore never appears in the archive).

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_attribute_screen.py -q`, then the
   full suite and ruff.

5. **Commit:** `feat(kb): screen_claims + load_archive — oracle-blind per-claim archive screen (Phase C2)`
   with the co-author trailer.

---

### C3 — `lofo_claims`: leave-one-CLAIM-out ablation Δ

**Edit:** `groundloop/kb/attribute.py` (append). **New test:** `tests/kb/test_lofo_claims.py`.

The claim-granular analogue of `kb/distill/lofo.lofo_fragments` (spec §5.4, "reuse `kb/distill/lofo.py`").
`lofo_fragments` splits a guidance string into line-fragments and keeps the load-bearing ones; `lofo_claims`
ablates one *claim id* at a time and returns the **per-claim Δ** (a positive Δ means removing the claim
*dropped* the metric → the claim was load-bearing). `run_fn(claim_id_set) -> float` is a closure the driver
(C4) supplies — it re-runs the grounded fix eval with exactly that claim set and returns a grounded scalar
(the offline grade inside it is the sole oracle read). Pure + hermetic-testable with a scripted `run_fn`.

**Files**
- edit `groundloop/kb/attribute.py`
- create `tests/kb/test_lofo_claims.py`

**Steps**

1. **Write the failing test** `tests/kb/test_lofo_claims.py`:

```python
"""Leave-one-CLAIM-out ablation Δ (Phase C3), the claim-granular sibling of kb/distill/lofo.lofo_fragments.
Hermetic: a scripted run_fn (set[str] -> float) stands in for the grounded fix-eval; asserts baseline =
run_fn(full), per-claim Δ = baseline - run_fn(full - {claim}), and id de-dup / order preservation."""
from groundloop.kb.attribute import lofo_claims


def test_lofo_claims_returns_per_claim_delta():
    # scripted lift surface: c1 worth 1.0, c2 worth 0.5, c3 inert. baseline(full) = 1.5.
    def run_fn(s):
        s = set(s)
        return (1.0 if "c1" in s else 0.0) + (0.5 if "c2" in s else 0.0)

    deltas = lofo_claims(["c1", "c2", "c3"], run_fn)
    assert deltas["c1"] == 1.0          # remove c1 -> 0.5 ; Δ = 1.5 - 0.5
    assert deltas["c2"] == 0.5          # remove c2 -> 1.0 ; Δ = 1.5 - 1.0
    assert deltas["c3"] == 0.0          # inert: removing it changes nothing


def test_lofo_claims_dedups_and_preserves_order():
    deltas = lofo_claims(["c1", "c1", "c2"], lambda s: float(len(set(s))))
    assert list(deltas) == ["c1", "c2"]     # de-duplicated, first-seen order preserved
    assert deltas["c1"] == 1.0 and deltas["c2"] == 1.0   # baseline |{c1,c2}|=2, each removal -> 1


def test_lofo_claims_empty_is_empty():
    assert lofo_claims([], lambda s: 1.0) == {}
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_lofo_claims.py -q` →
   `ImportError: cannot import name 'lofo_claims'`.

3. **Implement** — append to `groundloop/kb/attribute.py`:

```python
def lofo_claims(claim_ids: Iterable[str], run_fn: Callable[[frozenset[str]], float]) -> dict[str, float]:
    """Leave-one-CLAIM-out attribution — the claim-granular analogue of kb/distill/lofo.lofo_fragments.
    baseline = run_fn(full_set); for each claim, Δ = baseline - run_fn(full_set without that claim). A
    POSITIVE Δ means removing the claim dropped the metric (the claim was load-bearing). `run_fn(set[str])
    -> float` is a driver-supplied closure that re-runs the grounded fix eval with exactly that claim set
    (grade_fix_all inside it is the sole, offline oracle read). Returns {claim_id: Δ}, first-seen order."""
    ids = list(dict.fromkeys(claim_ids))            # de-dup, preserve first-seen order
    full = frozenset(ids)
    baseline = run_fn(full)
    return {cid: baseline - run_fn(full - {cid}) for cid in ids}
```

**Implementer-verify (reuse):** `kb/distill/lofo.lofo_fragments(guidance, run_fn)` is the mirrored pattern
(baseline `run_fn(full)` then ablate one unit at a time) — confirmed; C3 differs only in that the unit is a
claim id and the return is the full per-claim Δ map (not just the load-bearing subset).

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_lofo_claims.py -q`, then the full
   suite and ruff.

5. **Commit:** `feat(kb): lofo_claims — leave-one-claim-out ablation Δ (Phase C3)` with the co-author trailer.

---

### C4 — per-claim promote/retire governance + the `gloop kb-attribute` driver

**Edit:** `groundloop/kb/attribute.py` (append the `ClaimRecord` bridge + `promote_or_retire` +
`attribute_and_govern`), `groundloop/cli/__init__.py` (add `_build_attribute_run_card_fn` seam +
`_run_kb_attribute` + the `kb-attribute` subparser + the dispatch line). **New tests:**
`tests/kb/test_attribute_govern.py`, `tests/kb/test_cli_kb_attribute.py`.

Closes the retain-loop (spec §5.5). `apply_verdict` needs a record exposing `.tier`/`.fail_count`/
`.demotions`, but a `Claim` carries `fail_count`/`demotions` inside its `evidence` bag — so a tiny frozen
`ClaimRecord` **bridge** (exactly the 4 fields `apply_verdict` touches) lets the reused ladder drive a
per-claim verdict, then folds the result back onto the `Claim` (tier + evidence). The 4-rung `TIERS` bottoms
out at `candidate` (clamped), so `apply_verdict` alone never retires; `promote_or_retire` adds the terminal
step — a demoting fail **at the bottom rung** ends the claim's life (`tier="retired"`, which is intentionally
outside `TIERS`, so the Phase-B `ClaimRegistry` never fires it again). `attribute_and_govern` orchestrates
per shortlisted claim: build its placebo (C1) → LOFO Δ (C3) **and** the placebo-swap comparison
(`accept_grounded`) → promote iff **both** controls pass. The `gloop kb-attribute` CLI is **GATED on a plan
archive** (no `plans/` → exit 0 before any spend).

**Files**
- edit `groundloop/kb/attribute.py`
- edit `groundloop/cli/__init__.py`
- create `tests/kb/test_attribute_govern.py`
- create `tests/kb/test_cli_kb_attribute.py`

**Steps**

1. **Write the failing governance test** `tests/kb/test_attribute_govern.py`:

```python
"""Per-claim promote/retire bridge + attribute_and_govern (Phase C4). Hermetic: a scripted run_card_fn
(set[str] -> arm-scorecard dict) stands in for the grounded fix-eval; the ClaimRecord bridge drives the
REUSED kb/lifecycle ladder; a demoting fail at the bottom rung retires the claim (terminal)."""
from groundloop.kb.attribute import attribute_and_govern, promote_or_retire
from groundloop.kb.claim import Claim


def _claim(cid="c1", tier="candidate", ev=None):
    return Claim(id=cid, applies_when={"any_text": ["x"]}, type="fix_step", content=f"advice {cid}",
                 grounding_refs=("GetLongField",), provenance="p", tier=tier, evidence=ev or {})


# --- the ClaimRecord bridge onto the reused apply_verdict ladder ---
def test_promote_advances_one_rung_and_resets_fail():
    c = promote_or_retire(_claim(tier="candidate", ev={"fail_count": 1}), True)
    assert c.tier == "applied" and c.evidence["fail_count"] == 0


def test_two_promotions_reach_validated():
    c = promote_or_retire(_claim(tier="candidate"), True)   # -> applied
    c = promote_or_retire(c, True)                          # -> validated (the PRODUCTION floor)
    assert c.tier == "validated"


def test_single_fail_holds_tier_but_counts():
    c = promote_or_retire(_claim(tier="validated"), False)
    assert c.tier == "validated" and c.evidence["fail_count"] == 1


def test_persistent_fail_demotes_non_bottom_tier():
    c = _claim(tier="validated")
    c = promote_or_retire(c, False)     # streak 1 -> hold
    c = promote_or_retire(c, False)     # streak 2 -> demote validated->applied
    assert c.tier == "applied" and c.evidence["demotions"] == ["validated->applied"]


def test_persistent_fail_at_candidate_retires():
    c = _claim(tier="candidate")
    c = promote_or_retire(c, False)     # streak 1 -> hold
    c = promote_or_retire(c, False)     # streak 2 at the bottom rung -> retired
    assert c.tier == "retired" and c.evidence["demotions"][-1] == "candidate->retired"


def test_retired_is_terminal():
    assert promote_or_retire(_claim(tier="retired"), True).tier == "retired"   # a pass must NOT resurrect it


# --- attribute_and_govern: screen shortlist -> confirm -> per-claim verdict ---
def _card(ptr, *, fab=0.0, gnd=0.9, rss=0.5):
    return {"plan_target_recall@1": {"value": ptr, "n": 5}, "resolved_rate_strict": {"value": rss, "n": 5},
            "fabrication_rate": {"value": fab, "n": 3}, "plan_groundedness": {"value": gnd, "n": 5},
            "cost_per_solved": {"value": 1.0, "n": 5}, "resolved_by_case": {}}


def test_govern_promotes_a_load_bearing_claim():
    claims = {"c1": _claim("c1"), "c2": _claim("c2")}

    def run_card_fn(ids):                       # c1 lifts plan_target_recall; its placebo does not
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.8 if good else 0.4)

    updated = attribute_and_govern(claims, ["c1"], run_card_fn)
    assert updated["c1"].tier == "applied"                       # promoted one rung
    assert updated["c1"].evidence["measured_lift"]["lofo_delta"] > 0
    assert updated["c2"].tier == "candidate"                     # untouched (not shortlisted)


def test_govern_rejects_a_claim_that_raises_fabrication():
    claims = {"c1": _claim("c1")}

    def run_card_fn(ids):                       # c1 lifts recall BUT raises fabrication -> honesty side fails
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.8 if good else 0.4, fab=0.3 if good else 0.0)

    assert attribute_and_govern(claims, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held, not promoted


def test_govern_retires_placebo_equivalent_claim_on_second_fail():
    claims = {"c1": _claim("c1", ev={"fail_count": 1})}          # already one fail on the ladder

    def run_card_fn(ids):                       # flat: c1 no better than its placebo -> no lift
        return _card(0.5)

    assert attribute_and_govern(claims, ["c1"], run_card_fn)["c1"].tier == "retired"
```

2. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_attribute_govern.py -q` →
   `ImportError: cannot import name 'attribute_and_govern'`.

3. **Implement** — append the bridge + governance to `groundloop/kb/attribute.py`:

```python
from groundloop.fixeval.compare import accept_grounded, compare, compare_metrics   # top-of-file imports
from groundloop.kb.claim_placebo import build_claim_placebo
from groundloop.kb.lifecycle import TIERS, apply_verdict


@dataclasses.dataclass(frozen=True)
class ClaimRecord:
    """The minimal record kb/lifecycle.apply_verdict reads/replaces — a bridge so the REUSED tier ladder
    can govern a Claim whose fail_count/demotions live inside its evidence bag."""
    id: str
    tier: str
    fail_count: int = 0
    demotions: tuple[str, ...] = ()


def to_record(claim: Claim) -> ClaimRecord:
    ev = claim.evidence or {}
    return ClaimRecord(id=claim.id, tier=claim.tier, fail_count=int(ev.get("fail_count", 0)),
                       demotions=tuple(ev.get("demotions", ())))


def promote_or_retire(claim: Claim, passed: bool, *, hysteresis: int = 2,
                      measured_lift: dict | None = None, wilson95=None,
                      validating_case_ids: Iterable[str] | None = None) -> Claim:
    """Fold one per-claim verdict into the tier ladder and return the updated (new) Claim. `passed` ->
    apply_verdict promotes one rung + resets the streak; a failing streak reaching `hysteresis` demotes one
    rung, EXCEPT at the bottom rung (candidate) where it RETIRES the claim (terminal — 'retired' is outside
    TIERS, so the Phase-B ClaimRegistry never fires it again). Writes tier + evidence (fail_count, demotions,
    and optional measured_lift/wilson95/validating_case_ids) back onto the frozen Claim."""
    if claim.tier not in TIERS:                       # retired (or any non-TIER) is terminal
        return claim
    rec = to_record(claim)
    retiring = (not passed and rec.tier == TIERS[0] and rec.fail_count + 1 >= hysteresis)
    if retiring:
        new_tier, new_fail = "retired", 0
        new_demotions = rec.demotions + (f"{rec.tier}->retired",)
    else:
        nr = apply_verdict(rec, passed, hysteresis=hysteresis)
        new_tier, new_fail, new_demotions = nr.tier, nr.fail_count, nr.demotions
    ev = dict(claim.evidence or {})
    ev["fail_count"] = new_fail
    ev["demotions"] = list(new_demotions)
    if measured_lift is not None:
        ev["measured_lift"] = measured_lift
    if wilson95 is not None:
        ev["wilson95"] = wilson95
    if validating_case_ids is not None:
        ev["validating_case_ids"] = list(validating_case_ids)
    return dataclasses.replace(claim, tier=new_tier, evidence=ev)


def _metric_value(card: dict, key: str) -> float:
    m = card.get(key)
    v = m.get("value") if isinstance(m, dict) else m
    return float(v) if isinstance(v, (int, float)) else 0.0


def attribute_and_govern(claims: dict[str, Claim], shortlist: Iterable[str],
                         run_card_fn: Callable[[frozenset[str]], dict], *,
                         primary: str = "plan_target_recall@1", cost_budget: float | None = None,
                         hysteresis: int = 2) -> dict[str, Claim]:
    """Confirm each shortlisted candidate causally, then govern its tier — one claim at a time (spec §5.5).
    `run_card_fn(claim_id_set) -> eval-arm scorecard dict` re-runs the grounded fix eval with EXACTLY that
    claim set injected (candidates + their per-claim placebos, resolved by the driver's pool) and returns
    the arm's grounded metrics; grade_fix_all inside it is the sole, offline oracle read. Per claim:
      * LOFO Δ (C3) over the active shortlist — the claim must be load-bearing (Δ > 0);
      * placebo-swap comparison — the claim arm (head) vs the arm with the claim replaced by its
        length-matched placebo (base, same firing set) -> accept_grounded's two-sided grounded gate;
    promote iff BOTH pass; else fail -> promote_or_retire records the streak/retirement. Returns the full
    updated store (non-shortlisted claims pass through unchanged)."""
    valid = [cid for cid in dict.fromkeys(shortlist) if cid in claims]
    active = frozenset(valid)
    placebos = build_claim_placebo({cid: claims[cid] for cid in valid})     # C1: one placebo per candidate

    def metric_fn(s: frozenset[str]) -> float:
        return _metric_value(run_card_fn(frozenset(s)), primary)

    deltas = lofo_claims(valid, metric_fn)                                  # C3: leave-one-claim-out Δ
    updated = dict(claims)
    for cid in valid:
        pid = "placebo-" + cid
        assert pid in placebos                                             # C1 built one per shortlisted claim
        head = run_card_fn(active)                                         # claim present
        base = run_card_fn((active - {cid}) | {pid})                       # claim swapped for its placebo
        metrics_cmp = compare_metrics(base, head)
        resolved_cmp = compare(base.get("resolved_by_case", {}), head.get("resolved_by_case", {}))
        verdict = accept_grounded(metrics_cmp, resolved_cmp, cost_budget=cost_budget)
        passed = bool(verdict["accepted"]) and deltas.get(cid, 0.0) > 0    # load-bearing AND two-sided-clean
        updated[cid] = promote_or_retire(
            claims[cid], passed, hysteresis=hysteresis,
            measured_lift={"lofo_delta": deltas.get(cid, 0.0),
                           primary: metrics_cmp.get(primary, {}).get("delta")})
    return updated
```

4. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_attribute_govern.py -q`.

5. **Write the failing CLI test** `tests/kb/test_cli_kb_attribute.py`:

```python
"""`gloop kb-attribute` driver (Phase C4). Hermetic: GATED on a plan archive (no plans/ -> exit 0 before any
spend); the fix-eval seam cli._build_attribute_run_card_fn is monkeypatched to a scripted run_card_fn (no
atlas / no model), so the real load_archive -> screen_claims -> attribute_and_govern -> save_claims path
runs end-to-end over fixture claims.json + a fixture archive."""
import json

import groundloop.cli as cli
from groundloop.kb.claim import Claim, load_claims, save_claims


def _payload(case, fired, groundedness):
    return {"schema": 1, "case_id": case, "arm": "membership+logs", "predicted_repo": "r",
            "plan": {"steps": []}, "fired_skills": [], "fired_claims": list(fired),
            "outcome": {"groundedness": groundedness, "replans": 0, "abstained": False,
                        "patch_emitted": True, "patch_applies": True}}


def test_kb_attribute_gated_on_archive(tmp_path, capsys):
    rc = cli.main(["kb-attribute", "--archive", str(tmp_path / "plans"), "--dataset", str(tmp_path),
                   "--index-db", "unused.db", "--repos", str(tmp_path)])
    assert rc == 0                                          # exits cleanly with NO archive present
    assert "no plan archive" in capsys.readouterr().out


def test_kb_attribute_promotes_via_seam(tmp_path, monkeypatch):
    store = tmp_path / "claims.json"
    save_claims(str(store), {"c1": Claim(id="c1", applies_when={"any_text": ["x"]}, type="fix_step",
                                         content="advice", grounding_refs=("GetLongField",),
                                         provenance="p", tier="candidate", evidence={})})
    d = tmp_path / "plans"
    d.mkdir()
    (d / "a__arm.json").write_text(json.dumps(_payload("a", ["c1"], 0.9)))    # c1 fired, high groundedness
    (d / "b__arm.json").write_text(json.dumps(_payload("b", [], 0.3)))       # baseline, low groundedness

    def fake_seam(args, claims_arg):
        def run_card_fn(ids):
            good = "c1" in set(ids) and "placebo-c1" not in set(ids)
            return {"plan_target_recall@1": {"value": 0.8 if good else 0.4, "n": 5},
                    "resolved_rate_strict": {"value": 0.5, "n": 5}, "fabrication_rate": {"value": 0.0, "n": 3},
                    "plan_groundedness": {"value": 0.9, "n": 5}, "cost_per_solved": {"value": 1.0, "n": 5},
                    "resolved_by_case": {}}
        return run_card_fn

    monkeypatch.setattr(cli, "_build_attribute_run_card_fn", fake_seam)
    rc = cli.main(["kb-attribute", "--archive", str(d), "--dataset", str(tmp_path), "--index-db", "unused.db",
                   "--repos", str(tmp_path), "--claims-store", str(store), "--screen-threshold", "0.1"])
    assert rc == 0
    assert load_claims(str(store))["c1"].tier == "applied"    # screened in, confirmed, promoted one rung
```

6. **Run it and confirm it fails:** `.venv/bin/python -m pytest tests/kb/test_cli_kb_attribute.py -q` →
   fails on `argument cmd: invalid choice: 'kb-attribute'` (subparser not yet registered).

7. **Implement the CLI wiring in** `groundloop/cli/__init__.py`. Add the fix-eval seam + handler as
   module-level functions (place them near `_build_distill_run_fn` / before `_run_compare`):

```python
def _build_attribute_run_card_fn(args, claims):
    """Return `run_card_fn(claim_id_set) -> eval-arm scorecard dict`: re-runs the plan-format fix eval with
    EXACTLY the passed claim ids (candidates AND their per-claim placebos) injected via a ClaimRegistry at
    the candidate (EVAL) floor, and returns the eval arm of grade_fix_all (the offline grade = sole oracle
    read). Mirrors _build_distill_run_fn. Hermetic tests monkeypatch THIS symbol to a scripted stub."""
    import json
    import os
    from pathlib import Path

    from groundloop.adapters.estate import GitFixtureEstate
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.core.types import RepoRef
    from groundloop.eval.arms import build_arms
    from groundloop.eval.dataset import load_cases, load_eval_oracle
    from groundloop.fixeval.runner import FixEvalRunner
    from groundloop.fixeval.scorecard import grade_fix_all
    from groundloop.kb.ab import _make_fixer
    from groundloop.kb.claim_placebo import build_claim_placebo
    from groundloop.kb.registry import ClaimRegistry

    catalog_path = args.catalog or os.path.join(args.dataset, "catalog.json")
    catalog = [RepoRef(r["name"]) for r in json.loads(Path(catalog_path).read_text())]
    cases = load_cases(args.dataset)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — sole oracle read
    eval_arm = getattr(args, "eval_arm", None) or "membership+logs"

    embedder = None
    if os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)

    pool = dict(claims)
    pool.update(build_claim_placebo(claims))         # candidates + one placebo each, keyed by id

    def run_card_fn(claim_ids):
        selected = [pool[i] for i in claim_ids if i in pool]
        registry = ClaimRegistry(selected, embedder=embedder)
        estate = GitFixtureEstate(args.repos, args.dataset + "/_work-attr")
        runner = FixEvalRunner(issues=MockJira(args.dataset), estate=estate, catalog=catalog,
                               tau_margin=0.0, tau_score=0.0,
                               claims=registry, claims_tier_floor="candidate")
        records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)),
                             fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        return card["arms"][eval_arm]

    return run_card_fn


def _run_kb_attribute(args) -> int:
    """Staged per-claim attribution + governance (spec §5.4/§5.5). GATED on a plan archive: no plans/ ->
    exit 0 (nothing to attribute). screen (archive, oracle-blind) -> shortlist (capped by --max-lofo) ->
    LOFO-confirm vs per-claim placebo -> accept_grounded -> apply_verdict per claim; writes tier + evidence
    back to claims.json. Oracle-blind loop; grade_fix_all inside the run-card seam is the sole oracle read."""
    from collections import Counter

    from groundloop.kb.attribute import attribute_and_govern, load_archive, screen_claims
    from groundloop.kb.claim import CLAIMS_PATH, load_claims, save_claims

    payloads = load_archive(args.archive)
    if not payloads:
        print(f"kb-attribute: no plan archive at {args.archive} — nothing to attribute "
              f"(run `gloop fixeval --claims candidate` first)")
        return 0

    store_path = args.claims_store or CLAIMS_PATH
    claims = load_claims(store_path)
    shortlist = screen_claims(payloads, claims, threshold=args.screen_threshold)
    if args.max_lofo and len(shortlist) > args.max_lofo:
        shortlist = shortlist[: args.max_lofo]
    if not shortlist:
        print(f"kb-attribute: screened {len(payloads)} plan(s) -> 0 shortlisted "
              f"(no claim cleared |screen_lift| >= {args.screen_threshold})")
        return 0

    run_card_fn = _build_attribute_run_card_fn(args, claims)
    updated = attribute_and_govern(claims, shortlist, run_card_fn, cost_budget=args.cost_budget)
    save_claims(store_path, updated)

    print(f"kb-attribute: screened {len(payloads)} plan(s) -> shortlist {len(shortlist)} -> {store_path}")
    print("  tiers:", dict(Counter(c.tier for c in updated.values())))
    for cid in shortlist:
        c = updated[cid]
        print(f"  {cid}: {c.tier}  (lofo_delta={c.evidence.get('measured_lift', {}).get('lofo_delta')})")
    return 0
```

Register the subparser inside `build_parser()` (e.g. after the `kb-distill` (`kds`) block):

```python
    kat = sub.add_parser("kb-attribute",
                         help="staged per-claim attribution: archive screen -> LOFO confirm vs placebo -> "
                              "promote/retire (per-claim governance of claims.json)")
    kat.add_argument("--archive", required=True,
                     help="plan archive dir (<out>/plans from `gloop fixeval --claims candidate`)")
    kat.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    kat.add_argument("--catalog", default="", help="catalog.json (default: <dataset>/catalog.json)")
    kat.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    kat.add_argument("--repos", required=True, help="fixtures/repos root for @base materialization")
    kat.add_argument("--claims-store", dest="claims_store", default=None,
                     help="claim store JSON to govern (default: groundloop/kb/data/claims.json)")
    kat.add_argument("--screen-threshold", dest="screen_threshold", type=float, default=0.0,
                     help="|screen_lift| shortlist threshold (default 0.0 = shortlist any claim with contrast)")
    kat.add_argument("--max-lofo", dest="max_lofo", type=int, default=20,
                     help="cap the LOFO-confirm shortlist (bounds the real fix-loop spend)")
    kat.add_argument("--cost-budget", dest="cost_budget", type=float, default=None,
                     help="reject a claim if Δcost_per_solved exceeds this (default: advisory only)")
```

Add the dispatch line inside `main()` (next to the other `kb-*` branches):

```python
    if args.cmd == "kb-attribute":
        return _run_kb_attribute(args)
```

8. **Run and confirm green:** `.venv/bin/python -m pytest tests/kb/test_cli_kb_attribute.py -q`, then the
   full suite `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check groundloop tests`.

9. **Commit:** `feat(kb): gloop kb-attribute — per-claim screen->LOFO-confirm->promote/retire (Phase C4)`
   with the co-author trailer.

**Implementer-verify (C4 reuse):**
- `kb/lifecycle.apply_verdict(rec, passed, *, hysteresis=2)` mutates only `.tier`/`.fail_count`/`.demotions`
  via `dataclasses.replace` — `ClaimRecord` exposes exactly those (+ `id`); `prev_tier` clamps at
  `candidate`, which is why `promote_or_retire` adds the terminal retire at the bottom rung. Confirmed.
- `fixeval/compare.compare_metrics(base_arm, head_arm)` reads `{metric: {"value": ...}}` entries (unwraps via
  its `_val`) and diffs the `_GROUNDED` set incl. `plan_target_recall@1`, `resolved_rate_strict`,
  `plan_groundedness`, `fabrication_rate`, `cost_per_solved`; `accept_grounded(metrics_cmp, resolved_cmp,
  *, cost_budget=None)` = POS (Δplan_target_recall@1>0 OR Δresolved_rate_strict>0) ∧ HONESTY (Δfabrication≤0
  ∧ Δplan_groundedness≥0). Confirmed — so `run_card_fn` must return an arm dict shaped like
  `card["arms"][eval_arm]` (metrics wrapped `{"value","n"}` + a `resolved_by_case` dict). Confirmed shape in
  `fixeval/scorecard.grade_fix_all`.
- `ClaimRegistry(claims, *, embedder=None)` + `.select(ctx, tier_floor)` and the runner knobs
  `FixEvalRunner(..., claims=<registry>, claims_tier_floor="candidate")` are Phase-B deliverables — confirm
  the constructor/keyword names match Phase B (adjust the seam if Phase B named them otherwise). The placebo
  Claims carry `tier == source.tier == "candidate"`, so they fire at the `candidate` floor exactly like the
  real candidates.
- `_make_fixer` (`kb/ab.py`) + `build_arms`/`load_cases`/`load_eval_oracle`/`GitFixtureEstate`/`AtlasIndex`/
  `MockJira` — reused verbatim from `_build_distill_run_fn`; `grade_fix_all(records, oracle_by_case=...)` is
  the offline grade (sole oracle read). Confirmed.

**Phase C exit state:** `build_claim_placebo`, `screen_claims`/`load_archive`, `lofo_claims`, the
`ClaimRecord` bridge + `promote_or_retire` + `attribute_and_govern`, and the `gloop kb-attribute` driver all
land, each hermetic-tested (scripted `run_fn`/`run_card_fn`, fixture archive, fixture `claims.json`). Given a
`fired_claims` archive, `gloop kb-attribute` screens (oracle-blind) → shortlists → LOFO-confirms each vs its
per-claim placebo → promotes/retires per claim in `claims.json` via `accept_grounded` + `apply_verdict`. The
whole-corpus verdict is replaced by per-claim governance: claim A retained, claim B retired, independently.
Phase D (the gated live runbook) mints and validates the real claim KB on the live substrate using exactly
these primitives.

## Phase D — Live runbook (gated)

This phase has **no code** — Phases A–C shipped the claim model, `ClaimRegistry`/`render_claims`, the `--claims` arm, `gloop kb-extract`, `gloop kb-attribute`, and their hermetic (Type‑1) tests. Phase D is the **acceptance runbook** that *mints and validates the claim KB on the live substrate*: it decomposes the 12 authored Skills into candidate claims, grounds them against the real atlas, measures them through the plan‑format fix loop, and lets the per‑claim retain‑loop promote/retire — then proves the surviving **validated** set beats the raw‑Skill placebo and is smaller/cleaner (spec §8).

Real gateway + real fleet repos. **Source `.env`, run off ext4, use the plain‑dir corpora** (CLAUDE.md / `docs/type2-eval-setup.md`). Never skip the `.env` source or every arm silently degrades to the canned model. Do **not** commit results or churned tiers here — the write‑up + store sync land in the final write‑up step. Guardrails hold throughout: `core/` untouched, atlas schema unchanged, the loop stays oracle‑blind (grounding reads the **atlas** = code reality, not the oracle; the offline grade is the sole oracle read).

### D.1 Type‑1 acceptance gate (hermetic; final confirm before any spend)

- [ ] `.venv/bin/python -m pytest -q` → **all green** (whole suite incl. the new `tests/kb/` claim/extract/ground/registry/render/attribute/placebo tests + the `--claims` arm + `fired_claims` archive tests). This proves hermetically, at **zero gateway cost**, that: `parse`‑style extraction never raises, ground‑check drops hallucinated/leaky refs, `ClaimRegistry.select(ctx, tier_floor)` respects the tier floor, `render_claims` groups by type, `lofo_claims` + `claim_placebo` ablate correctly, and `apply_verdict` moves tiers per the ladder.
- [ ] `.venv/bin/ruff check groundloop tests` → clean (line length 110).

Only proceed to live spend once both are green.

### D.2 Preconditions, env, and the gateway‑free spend gate

The extract (D.3), archive accumulation (D.4), and LOFO‑confirm (D.5) are **real, contended** LiteLLM spend that shares one gateway with any concurrent atlas build / `gloop eval`. Gate on the gateway being **free and healthy** before each spending step — the same discipline as the plan‑format Phase 3 embed gate, plus a contention check.

```bash
cd /mnt/x/code/GroundLoop && set -a; . ./.env; set +a

# --- health gate (prints 200 when up, 000 when the GPU/Ollama host is down) ---
curl -s -o /dev/null -w "embed:%{http_code}\n" --max-time 20 "${KLOOP_EMBED_BASE_URL%/}/embeddings" \
  -H "Authorization: Bearer $KLOOP_EMBED_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","input":"hi"}'
.venv/bin/gloop doctor --atlas-db /home/vinc/gl-eval/atlas-9.db   # expect repos:9 units:475415 ; gateways 200

# --- gateway-free contention gate: refuse to spend if another gloop job is hammering the gateway ---
gw_busy() { pgrep -fa 'gloop (fixeval|eval|kb-extract|kb-attribute|kb-ab|kb-distill|index|build-atlas)' \
             | grep -v grep | grep -v $$ ; }
if gw_busy; then echo "GATEWAY BUSY — another eval/build is running; do NOT start Phase D"; else echo "gateway free"; fi
```

Paths + working store (all outputs on **ext4**, never the v9fs mount):

```bash
ATLAS=/home/vinc/gl-eval/atlas-9.db
SUB=/home/vinc/gl-eval/dataset-neg-synth-sub          # 278 cases: 128 neg + 150 pos
REPOS=/home/vinc/gl-eval/corpora-fast                 # EXT4 copy of the fleet repos (stage once:
                                                      # cp -a /mnt/x/code/corpora-local/* $REPOS/). REQUIRED:
                                                      # GitFixtureEstate re-copies the whole repo PER CASE, so
                                                      # v9fs corpora-local makes fixeval minutes/case — see
                                                      # docs/type2-atlas-build-findings.md Finding 10.
SEED=groundloop/kb/data/aaos_kb_seed.toml             # the 12 authored Skills (feedstock, never injected raw)
OUT=/home/vinc/gl-eval/claim-run ; mkdir -p "$OUT"
CLAIMS=$OUT/claims.json                               # WORKING store (repo default groundloop/kb/data/claims.json
                                                      # is synced only at the end, iff the validated set passes D.6)
```

- [ ] **Negatives guard (fabrication measurable).** Refuse to spend if the dataset carries no unanswerable tickets — otherwise `fabrication_rate` is undefined and the honesty side of the gate is blind (mirror the `type2_run.sh` `n_unanswerable >= 1` guard):

```bash
.venv/bin/python - <<PY
import json, glob, os
neg = sum(1 for f in glob.glob(os.path.join("$SUB","**","ticket.json"), recursive=True)
          if not json.load(open(f)).get("is_answerable", True))
print("unanswerable:", neg); assert neg >= 1, "no negatives -> fabrication unmeasurable; abort"
PY
```

### D.3 Extract → ground‑check (12 Skills → candidate claims)

`gloop kb-extract` runs the **live LLM as a proposer** (`GatewayModel.complete`) over each of the 12 Skills' `Signature:/Localize:/Fix:` prose + `hint_apis`, emitting atomic typed candidate `Claim`s (`localize_hint` / `fix_step` / `api_requirement`), each with an `applies_when` predicate seeded from the Skill's `[skill.match]` and the `grounding_refs` it names. The **deterministic, oracle‑blind ground‑check runs inside the same command** (`claim_ground.check_claim_grounded`): every `grounding_ref` must resolve in the atlas via `store.keyword_search`, and the leak red‑test drops any claim whose `content`/`refs`/`applies_when` name a `FLEET_OWNER_TOKENS` token. Survivors persist at `tier=candidate`. Cheap: ~12 LLM calls (one per Skill) + free atlas reads — this is the cheap front step, not the spend sink.

```bash
[ -z "$(gw_busy)" ] || { echo "gateway busy; abort"; exit 1; }
.venv/bin/gloop kb-extract --skills-seed $SEED --index-db $ATLAS --out $CLAIMS
# kb-extract flags (Phase A): --skills-seed <feedstock.toml>, --index-db <atlas>, --out <claims.json>.
#   The --out IS the claim store it merges into (there is NO --claims-store on extract); the ground-check
#   + leak red-test run inside this command and survivors persist at tier=candidate.
```

- [ ] Report the extraction ledger and inspect the survivors (drops are expected and healthy — a bad decomposition just produces candidates that fail the gate, spec §10):

```bash
.venv/bin/python - <<PY
from collections import Counter
from groundloop.kb.claim import load_claims
cs = load_claims("$CLAIMS")                           # load_claims -> dict[str, Claim]; iterate .values()
print("candidates:", len(cs), "by type:", dict(Counter(c.type for c in cs.values())))
print("provenance (source Skill) coverage:", len({c.provenance for c in cs.values()}), "of 12 Skills")
PY
# The kb-extract stdout ledger reports admitted/rejected counts + each dropped claim's reasons.
```

Sanity floor: extraction should net **more than 12** grounded candidates (atomic claims per Skill) but drop a nonzero hallucinated/leaky slice. If it nets ~0 grounded, stop — the atlas or the extract prompt is wrong, not the KB.

### D.4 Accumulate the archive — plan‑format fix eval with `--claims candidate`

Run the fix loop under the plan fixer with the **eval floor** (`--claims candidate` → `ClaimRegistry.select(ctx, tier_floor="candidate")`). Selected claims' `content` is composed by `render_claims` into the **plan prompt** (`PlanningFixEngine.with_preamble`); each planned case records its **`fired_claims`** into the archive under `$OUT/plans/` — the per‑claim attribution feedstock. Injection is oracle‑blind exactly as the `--skills` path.

> **KB/claim gotcha (grade on the right metric).** `localize` runs *before* the plan `propose`, so claims fire only in the plan/fix stage → **`file_recall@1` is claim‑invariant**. Grade claim lift on the grounded plan/resolution signal (`plan_target_recall@1`, `resolved_rate_strict`, `plan_groundedness`, `fabrication_rate`) — exactly what `accept_grounded` keys on — **never `file_recall@1`**.

```bash
[ -z "$(gw_busy)" ] || { echo "gateway busy; abort"; exit 1; }
# Round-1 window (W1): accumulate the fired_claims archive with candidate claims injected.
.venv/bin/gloop fixeval --dataset $SUB --catalog $SUB/catalog.json --index-db $ATLAS --repos $REPOS \
  --fixer plan --max-replan 1 --claims candidate --claims-store $CLAIMS \
  --out $OUT/fix-plan-claims-cand.W1.json          # writes $OUT/plans/*.json carrying fired_claims
```

Cost/time: `--fixer plan` is ~2–3× `direct`'s model calls (plan + execute + ≤`max_replan` re‑plans; abstentions are free); the candidate arm injects the full candidate set, so expect the low‑hours range over 278 cases on deepseek‑chat. **Run detached; snapshot as it lands.** Do not launch if `gw_busy`.

### D.5 Attribute → per‑claim promote / retire (`gloop kb-attribute`)

`gloop kb-attribute` runs the **staged** attribution (spec §5.4) over the accumulated archive:

1. **Screen (cheap, no new spend):** `attribute.screen_claims(archive, claims)` computes a directional per‑claim signal on the grounded metrics (fired vs matched‑baseline) → a shortlist of promising *and* suspicious claims. Correlational only — it prioritizes, never promotes.
2. **Confirm (causal, budgeted spend):** for each shortlisted claim, `attribute.lofo_claims` runs **leave‑one‑CLAIM‑out** ablation on that claim's *firing* cases against its **per‑claim placebo** (`claim_placebo.build_placebo` — one placebo Claim per candidate, **same `applies_when`** so it fires on the same cases, length‑matched irrelevant `content`). Yields a per‑claim Δlift + Wilson‑95 CI. Cost scales with the *shortlist*, not the 12‑Skill decomposition — gate + budget it.
3. **Verdict + governance:** per claim, `fixeval/compare.accept_grounded` (POS = Δ`plan_target_recall@1`>0 OR Δ`resolved_rate_strict`>0 ; HONESTY = Δ`fabrication_rate`≤0 AND Δ`plan_groundedness`≥0 ; Wilson‑LB>0) → `lifecycle.apply_verdict(rec, passed, hysteresis=2)` advances/retires **one claim at a time**, writing `tier` + `evidence` (measured_lift, wilson95, validating_case_ids, fail_streak) back to the store.

```bash
[ -z "$(gw_busy)" ] || { echo "gateway busy; abort"; exit 1; }
.venv/bin/gloop kb-attribute --archive $OUT/plans --dataset $SUB --catalog $SUB/catalog.json \
  --index-db $ATLAS --repos $REPOS --claims-store $CLAIMS --screen-threshold 0.0 \
  --max-lofo 20 --cost-budget 0.02
# kb-attribute flags (Phase C): --archive <plans dir>, --dataset, --catalog, --index-db, --repos,
#   --claims-store <claims.json it governs IN PLACE>, --screen-threshold (shortlist), --max-lofo
#   (shortlist cap), --cost-budget. There is NO --out: it mutates tier + evidence back into --claims-store
#   and prints the tier ledger to stdout.
```

**Promotion arithmetic (do not skip — this is why one pass is not enough).** The ladder is the **4‑rung** `TIERS=(candidate, applied, validated, canonical)`, and `apply_verdict` advances **exactly one rung per passing verdict**. So a `candidate` that clears the grounded gate once reaches only **`applied`** — the EVAL floor, *not* the PRODUCTION floor. Reaching **`validated`** (what production injects, `tier_floor="validated"`) requires the claim to clear the gate **twice, on independent windows** — a built‑in double‑confirm against overfitting. Run a second round on a disjoint case window:

```bash
# Round-2 window (W2): a DISJOINT slice so the promotion is double-confirmed on unseen cases.
#   fixeval has NO --shard flag — materialize a second disjoint dataset dir $SUB_W2 (split $SUB into
#   $SUB_W1 for W1 above and $SUB_W2 here) and point --dataset/--catalog at it; disjoint windows beat
#   re-running the same cases. The archive under $OUT/plans accumulates across both windows.
[ -z "$(gw_busy)" ] || { echo "gateway busy; abort"; exit 1; }
.venv/bin/gloop fixeval --dataset $SUB_W2 --catalog $SUB_W2/catalog.json --index-db $ATLAS --repos $REPOS \
  --fixer plan --max-replan 1 --claims candidate --claims-store $CLAIMS \
  --out $OUT/fix-plan-claims-cand.W2.json
.venv/bin/gloop kb-attribute --archive $OUT/plans --dataset $SUB_W2 --catalog $SUB_W2/catalog.json \
  --index-db $ATLAS --repos $REPOS --claims-store $CLAIMS --screen-threshold 0.0 \
  --max-lofo 20 --cost-budget 0.02
# After W2: claims that passed BOTH windows are tier=validated; a persistent fail (streak >= hysteresis 2)
# is tier-demoted toward retired. Inspect the ladder (load_claims -> dict; iterate .values()):
.venv/bin/python - <<PY
from collections import Counter
from groundloop.kb.claim import load_claims
print("tiers:", dict(Counter(c.tier for c in load_claims("$CLAIMS").values())))
PY
```

### D.6 Inspect the validated set + compare vs the raw‑Skill placebo (spec §8)

Now measure the **validated** claim set (production floor) against the **raw‑Skill placebo** (the existing length‑matched control, `kb/placebo.build_placebo` → `placebo.toml`, injected via `--skills placebo`) and against the **raw 12 Skills** (`--skills kb`) on the grounded signal — same gateway‑free gate before each arm.

```bash
[ -z "$(gw_busy)" ] || { echo "gateway busy; abort"; exit 1; }
for arm in "--claims validated --claims-store $CLAIMS:claims-validated" \
           "--skills placebo:skills-placebo" \
           "--skills kb:skills-kb"; do
  flags="${arm%%:*}"; name="${arm##*:}"
  .venv/bin/gloop fixeval --dataset $SUB --catalog $SUB/catalog.json --index-db $ATLAS --repos $REPOS \
    --fixer plan --max-replan 1 $flags --out $OUT/fix-plan-$name.json
done

# Grounded two-sided verdict (accept_grounded), surfaced by `gloop compare`:
.venv/bin/gloop compare --base $OUT/fix-plan-skills-placebo.json --head $OUT/fix-plan-claims-validated.json \
  --out $OUT/cmp-validated-vs-placebo.json   # §8 EFFECTIVENESS: validated must BEAT the raw-Skill placebo
.venv/bin/gloop compare --base $OUT/fix-plan-skills-kb.json      --head $OUT/fix-plan-claims-validated.json \
  --out $OUT/cmp-validated-vs-rawskills.json # §8 COMPRESSION check: retain/beat raw lift at a smaller footprint
```

**Metrics collected per arm** (all in the scorecard JSON; the grounded ones drive the verdict):

| Metric | Source key | What it tells us |
|--------|-----------|------------------|
| Plan correctness | `plan_target_recall@1/5`, `plan_api_match` | did claim‑guided planning name the RIGHT files/APIs (claim‑sensitive; localize's `file_recall@1` is claim‑invariant) |
| Plan groundedness | `plan_groundedness` | did claims *reduce* hallucinated citations (oracle‑blind) |
| Resolution (hardened) | `resolved_rate_strict` | patch edits the right file + calls the API on a real code line |
| Honesty | `fabrication_rate` (over the 128 negatives) | clean patch on an unanswerable ticket — claims must not raise it |
| Coverage | `abstain_rate`, `fix_coverage` | over/under‑abstention |
| Claim footprint | `count(tier≥validated)`, `render_claims` chars | compression vs the 12 raw Skills (§8 "smaller/cleaner") |
| Cost | `cost_total`, `cost_per_solved` | $ per grounded solve |

- [ ] **Footprint / compression (the §8 "smaller‑cleaner" signal):**

```bash
.venv/bin/python - <<PY
from groundloop.kb.claim import load_claims
from groundloop.kb.render import render_claims
from groundloop.adapters.skills.mock import load_skills
from groundloop.skills.base import render_skills
val = [c for c in load_claims("$CLAIMS").values() if c.tier in ("validated", "canonical")]
skills = load_skills("$SEED")
print("validated claims :", len(val), "| render_claims chars:", len(render_claims(val)))
print("raw Skills       :", len(skills), "| render_skills chars:", len(render_skills(skills)))
PY
```

**Success criteria (Phase D exit — spec §8):**
- [ ] **Effectiveness:** `cmp-validated-vs-placebo.json` → `grounded_verdict.accepted == true` — the validated set **beats the raw‑Skill placebo** (POS on Δ`plan_target_recall@1` or Δ`resolved_rate_strict`, with Δ`fabrication_rate`≤0 **and** Δ`plan_groundedness`≥0).
- [ ] **Per‑claim rigor:** every `tier≥validated` claim carries `evidence.wilson95` lower‑bound > 0 and Δ`fabrication`≤0 in its store record (written by D.5).
- [ ] **Compression:** the validated set is **smaller/cleaner** than the 12 raw Skills — `render_claims(validated)` char/claim footprint materially below `render_skills(12)`, while `cmp-validated-vs-rawskills.json` shows the grounded lift **retained or improved** (distillation removed the messy/invalid parts, spec §8).

### D.7 Honest‑negative handling + write‑up

- [ ] **A null result is a valid result.** If the validated set is **empty** (no claim cleared the gate on two windows) or `cmp-validated-vs-placebo.json` shows `accepted:false` (validated ties/loses to a length‑matched control), **that is the project's core finding surfacing** — authored/distilled cold‑start knowledge does not beat placebo on a trustworthy metric. Record it verbatim; do **not** massage, and do **not** promote claims by hand to force a positive.
- [ ] **Retirements are logged, not hidden.** Claims that fail the gate ride the ladder down (`fail_streak ≥ 2 → demote/retire`); report the retired count + the top retired claims with their negative `measured_lift`. Honest refusal handling: the 128 negatives feed `fabrication_rate`; a claim that lifts `plan_target_recall@1` but raises fabrication is **rejected by the honesty side** and must not reach `validated`.
- [ ] **Cold‑start caveat (spec §10).** Production starts with an **empty** `tier≥validated` set and grows only as claims earn promotion — the claim KB adds nothing to real fixes on day 1, by design. State the day‑1 footprint plainly in the write‑up.
- [ ] **Sync + write‑up.** Only if D.6 passes: sync the accepted `validated`/`canonical` tiers from `$CLAIMS` back to the repo store `groundloop/kb/data/claims.json`, then write `docs/2026-07-07-claim-kb-evaluation.md`: the extraction ledger (proposed/grounded/dropped), the per‑claim promote/retire table with Wilson CIs, the validated‑vs‑placebo and validated‑vs‑raw‑Skills `grounded_verdict`s, the compression numbers, and the honest caveats (proxy‑not‑tests; file‑grain context; advisory exclusions; candidate cold‑start). Confirm the full suite green + ruff clean, update `docs/STATUS.md` and the memory, and commit the write‑up (results only — the code already landed in Phases A–C) with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

## Verification (end-to-end acceptance)

1. **Phase A** — `claims.json` round-trips; `check_claim_grounded` drops claims whose refs don't resolve in
   the atlas and leak-tainted claims; `gloop kb-extract` (hermetic, CannedModel) writes only grounded
   candidates.
2. **Phase B** — `gloop fixeval --claims candidate` selects claims at the tier floor, feeds `render_claims`
   into the plan prompt, records `fired_claims`; the `--skills`/`direct` paths stay behaviorally unchanged;
   production floor = `validated`.
3. **Phase C** — `screen_claims` shortlists from a fixture archive; `lofo_claims` attributes per-claim Δ;
   `gloop kb-attribute` promotes/retires per claim in `claims.json` via `accept_grounded` + `apply_verdict`.
4. **Phase D (gated)** — the live runbook yields a validated claim set; success = it beats the raw-Skill
   placebo on the grounded metrics AND is smaller/cleaner (a clean negative is a valid result).
5. **Invariants** — no diff under `groundloop/core/`; atlas schema unchanged; full suite green + ruff clean
   before each commit; oracle-blind throughout.

## Self-review (assembly)

- **Cross-phase type consistency:** `Claim`, `claims.json`, `ClaimRegistry`, `render_claims`, `fired_claims`,
  `check_claim_grounded`, `lofo_claims`, `accept_grounded`, `apply_verdict`, `--claims`, `kb-extract`,
  `kb-attribute` used identically across phases (grep-verified at assembly).
- **Reuse honored:** predicate compiler, lifecycle ladder (candidate->applied->validated->canonical), LOFO,
  placebo, `accept_grounded`, the plan archive — reused, not reimplemented.
