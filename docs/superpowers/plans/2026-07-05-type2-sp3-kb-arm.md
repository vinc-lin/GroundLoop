# SP3 — Dev-Experience KB (Skills) as a Measured Arm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** Stand up a retrievable development-experience **knowledge base** (Skills), seeded with *real*
GroundLoop RCA/ops playbooks, wired as a **measured arm** on the SP2 fix-loop eval — and prove it helps
grounded fixing on positives **without** eroding honest refusal on negatives, plus a migration guide +
parity self-test so the real (post-migration) Skills drop in unchanged.

**Architecture:** A new **non-core** `groundloop/skills/` package migrates the `bfl` `Skill` primitive
(`Skill` / `SkillRegistry` Protocol / `NullSkillRegistry` / `render_skills`) and adds an oracle-blind
`SkillCtx` + a **declarative→compiled predicate** (`applies_to` lives as data, not code). A
`MockSkillRegistry` (adapter) loads a TOML seed of real playbooks; `select(ctx)` = predicate filter
(hermetic default) + an optional bge-m3 rerank (gated). Skills inject **post-match** at the fix stage as
a rendered *preamble* on `ModelPatchEngine` (the frozen `FixEngine.propose` signature is untouched); the
`FixEvalRunner` — which already holds the arm's `Signals` — builds the ctx, selects, and renders. The arm
is realized as **two `gloop fixeval` runs** (`--skills none` vs `--skills mock`) diffed by an extended
`gloop compare` that emits Δfile_recall / Δfabrication_rate / Δcost and an accept/reject verdict.

**Tech Stack:** Python 3.12, `.venv` (uv), `tomllib` (stdlib), `pytest`/`ruff` (line 110). Reuses the SP2
`groundloop/fixeval/` harness, `groundloop/eval/` arms/dataset, `groundloop/engines/atlas/embed.py`
(bge-m3 `GatewayEmbedder` / `StubEmbedder`). Source primitive: `/mnt/x/code/loop-agent/bfl/skills/base.py`.

**Provenance:** spec §3 of `docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md`
(the unified SP1→SP2→SP3 design); extends `docs/type2-evaluation.md` + `docs/downstream-fix-loop.md`
(`RunConfig.skills` is a *measured arm, never a trusted input*, `downstream-fix-loop.md:189`). Design
verified by an adversarial probe workflow (5/6 probes; divergences resolved inline in this plan).

---

## Guardrails (apply to every task)

- **Never edit `groundloop/core/`.** `FixEngine.propose(worktree, ticket, locations) -> Patch` is FROZEN;
  skills ride as `ModelPatchEngine` adapter state (a preamble), never a new `propose` argument. No SQLite
  schema change.
- **Oracle-blindness:** the registry and `build_ctx` read only loop-visible inputs (the seed data file;
  `ticket` fields; the arm's `Signals`; the predicted repo). They NEVER read `_oracle/`. Grading
  (`groundloop/fixeval/scorecard.py`) stays the sole offline oracle read.
- **Data, not code:** `applies_to` is compiled from a **closed-vocabulary declarative `match` spec** in the
  seed. No `eval`/`exec`, no serialized lambdas (that would be an arbitrary-code + leak-review hole).
- **Hermetic default:** `select` is predicate-only with **no network** in Type-1. The bge-m3 rerank is an
  **optional** `embedder`-gated add (StubEmbedder offline for determinism tests; `GatewayEmbedder`
  `skipif`-gated live). Embedder pinned `bge-m3`, query==index (reuse contract).
- **Measured arm, not a trusted input:** the arm = two runs compared. `skills=none` MUST be byte-identical
  to today's fix loop (empty preamble ⇒ unchanged prompt) so the Δ is cleanly attributable.
- **Green + ruff-clean before every commit.** Run `.venv/bin/python -m pytest -q > /tmp/pt.log 2>&1; echo $?`
  and gate the commit on the real exit code (never `pytest | tail`, which masks it). Ruff line length 110.
- End every commit message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

**New — `groundloop/skills/` (non-core library):**
- `groundloop/skills/__init__.py` — package marker.
- `groundloop/skills/base.py` — migrated `Skill` (+ `signals`, `provenance`), `SkillRegistry` Protocol,
  `NullSkillRegistry`, `render_skills`.
- `groundloop/skills/ctx.py` — `SkillCtx` + oracle-blind `build_ctx`.
- `groundloop/skills/predicate.py` — `compile_predicate` (closed vocab → closure, fail-fast).

**New — `groundloop/adapters/skills/` (adapter):**
- `groundloop/adapters/skills/__init__.py`
- `groundloop/adapters/skills/mock.py` — `MockSkillRegistry` + `load_skills`.
- `groundloop/adapters/skills/migrate.py` — `migrate_markdown_skills` + `triggers_to_spec` (author-facing).
- `groundloop/adapters/skills/data/aaos_playbooks.toml` — the real-data seed.

**Modified (non-core only):**
- `groundloop/adapters/fix/model_patch.py` — `preamble` ctor arg + `with_preamble` + prepend.
- `groundloop/fixeval/runner.py` — `skills=None` param + post-match select/render/inject in `_one`.
- `groundloop/fixeval/compare.py` — `compare_metrics` + `accept` (pure add; `compare` unchanged).
- `groundloop/cli/__init__.py` — `--skills` on `fixeval`; delta/verdict surface in `compare`.

**New tests:** `tests/skills/` (unit) + `tests/fixeval/test_skill_*.py` (integration) +
`tests/e2e/test_skills_live.py` (gated). **Fixtures:** `tests/fixtures/skills/`.
**Docs:** `docs/skill-kb-migration.md`.

---

## Phase A — KB primitive, ctx, predicate, mock registry (hermetic core)

### Task 1: Migrate the `Skill` primitive

**Files:**
- Create: `groundloop/skills/__init__.py` (empty)
- Create: `groundloop/skills/base.py`
- Test: `tests/skills/__init__.py` (empty), `tests/skills/test_base.py`

- [ ] **Step 1: Write the failing test** — `tests/skills/test_base.py`

```python
from groundloop.skills.base import Skill, NullSkillRegistry, render_skills


def _skill(sid):
    return Skill(id=sid, applies_to=lambda ctx: True, guidance=f"do {sid}",
                 signals=("x",), provenance="test")


def test_render_skills_emits_playbook_header():
    out = render_skills([_skill("a"), _skill("b")])
    assert out.startswith("\n\n# Applicable playbooks")
    assert "## Skill: a" in out and "do a" in out and "## Skill: b" in out


def test_render_skills_empty_is_empty_string():
    assert render_skills([]) == ""


def test_null_registry_selects_nothing():
    assert NullSkillRegistry().select(object()) == []


def test_skill_carries_new_provenance_and_signals_fields():
    s = _skill("a")
    assert s.signals == ("x",) and s.provenance == "test" and s.hint_apis == ()
```

- [ ] **Step 2: Run it, verify it fails** — `.venv/bin/python -m pytest tests/skills/test_base.py -q`
  Expected: FAIL (`ModuleNotFoundError: groundloop.skills`).

- [ ] **Step 3: Implement** — `groundloop/skills/base.py` (migrated from
  `/mnt/x/code/loop-agent/bfl/skills/base.py`; adds `signals` + `provenance` per spec §3.1; drops bfl's
  `tools`; `render_skills` kept verbatim):

```python
"""Dev-experience KB primitive — migrated as-is from loop-agent/bfl/skills/base.py, extended with the
spec §3.1 `signals` (retrieval tags) and `provenance` (KB traceability) fields. NOT a core port: this is
an engine-internal Protocol (like engines/atlas/embed.Embedder), swapped at the composition root."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Skill:
    id: str
    applies_to: Callable[[object], bool]   # predicate on a SkillCtx (compiled from declarative data)
    guidance: str                          # the playbook text (real dev experience)
    hint_apis: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()          # retrieval keys / tags (spec §3.1)
    provenance: str = ""                   # source doc/commit, for KB traceability (spec §3.1)


class SkillRegistry(Protocol):
    def select(self, ctx) -> list[Skill]: ...


class NullSkillRegistry:
    """The `skills=none` arm: a true no-op so the fix loop is byte-identical to pre-SP3."""
    def select(self, ctx) -> list[Skill]:
        return []


def render_skills(skills: list[Skill]) -> str:
    if not skills:
        return ""
    blocks = [f"## Skill: {s.id}\n{s.guidance}" for s in skills]
    return "\n\n# Applicable playbooks\n" + "\n\n".join(blocks)
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_base.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add groundloop/skills/__init__.py groundloop/skills/base.py tests/skills/
git commit -m "feat(skills): migrate Skill primitive + render_skills (SP3-T1)"
```

---

### Task 2: `SkillCtx` + oracle-blind `build_ctx`

**Files:**
- Create: `groundloop/skills/ctx.py`
- Test: `tests/skills/test_ctx.py`

- [ ] **Step 1: Write the failing test** — `tests/skills/test_ctx.py`

```python
from groundloop.core.types import Signals, Ticket, LogAttachment
from groundloop.skills.ctx import SkillCtx, build_ctx


def test_build_ctx_lowercases_and_concatenates_ticket_and_logs():
    sig = Signals(libraries=("libffmpeg.so",), errors=("UnsatisfiedLinkError",))
    tk = Ticket(id="GP-352", summary="App CRASHES on GL thread", description="Attaching the logcat.",
                logs=(LogAttachment(path="l", kind="logcat",
                                    content="No implementation found for nativeCreateHandler()"),))
    ctx = build_ctx(sig, tk, "android-gpuimage-plus")
    assert ctx.repo == "android-gpuimage-plus"
    assert ctx.signals is sig
    # text is one lowercased haystack over summary + description + every log's content
    assert "app crashes on gl thread" in ctx.text
    assert "attaching the logcat." in ctx.text
    assert "nativecreatehandler" in ctx.text


def test_build_ctx_is_oracle_blind_by_construction():
    # build_ctx takes only loop-visible values; it must not accept or read an oracle
    tk = Ticket(id="t", summary="s", description="d")
    ctx = build_ctx(Signals(), tk, None)
    assert ctx.repo is None and ctx.text == "s\nd"
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/skills/test_ctx.py -q`
  Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — `groundloop/skills/ctx.py`

```python
"""The oracle-blind context a Skill predicate evaluates against. Built ONLY from loop-visible inputs:
the arm's extracted Signals (structured) + a raw lowercased haystack over the ticket + its logs. NEVER
reads _oracle/. The raw `text` haystack matters because AndroidSignalExtractor's error pattern only
captures *Error/*Exception and misses SIGSEGV/native/.so/JNI cues — native playbooks key on `text`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from groundloop.core.types import Signals, Ticket


@dataclass(frozen=True)
class SkillCtx:
    signals: Signals           # structured, arm-extracted
    repo: Optional[str]        # the predicted owning repo (loop prediction, not the oracle)
    text: str                  # lowercased haystack: summary + description + all log content

    def tokens(self) -> tuple[str, ...]:
        return self.signals.tokens()


def build_ctx(signals: Signals, ticket: Ticket, repo: Optional[str]) -> SkillCtx:
    parts = [ticket.summary, ticket.description, *(a.content for a in ticket.logs)]
    text = "\n".join(p for p in parts if p).lower()
    return SkillCtx(signals=signals, repo=repo, text=text)
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_ctx.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add groundloop/skills/ctx.py tests/skills/test_ctx.py
git commit -m "feat(skills): oracle-blind SkillCtx + build_ctx (SP3-T2)"
```

---

### Task 3: Declarative→compiled predicate

**Files:**
- Create: `groundloop/skills/predicate.py`
- Test: `tests/skills/test_predicate.py`

**Semantics:** a `match` block is a set of **clauses OR'd together** (the skill applies if ANY clause
fires); within a single key's list, elements are OR'd; `all_text` is the AND escape hatch. An **empty**
spec → never fires. Unknown keys → `ValueError` at compile. Every `*_regex` is compiled eagerly (a bad
pattern fails at load, not mid-select). Closed vocabulary only — no code in data.

- [ ] **Step 1: Write the failing test** — `tests/skills/test_predicate.py`

```python
import pytest

from groundloop.core.types import Signals
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate


def _ctx(text="", **sig):
    return SkillCtx(signals=Signals(**sig), repo="r", text=text.lower())


def test_unknown_key_raises_at_compile():
    with pytest.raises(ValueError):
        compile_predicate({"any_bogus": ["x"]})


def test_bad_regex_raises_at_compile():
    with pytest.raises(ValueError):
        compile_predicate({"any_text_regex": ["("]})   # unbalanced


def test_empty_spec_never_fires():
    assert compile_predicate({})(_ctx("anything")) is False


def test_any_text_substring_or():
    p = compile_predicate({"any_text": ["unsatisfiedlinkerror", "sigsegv"]})
    assert p(_ctx("...java.lang.UnsatisfiedLinkError: no impl...")) is True
    assert p(_ctx("live preview freezes")) is False


def test_all_text_conjunction():
    p = compile_predicate({"all_text": ["load", "library"]})
    assert p(_ctx("load library for cge failed")) is True
    assert p(_ctx("load only")) is False


def test_any_text_regex_over_haystack():
    p = compile_predicate({"any_text_regex": [r"lib\w+\.so"]})
    assert p(_ctx("couldn't find \"libffmpeg.so\"")) is True
    assert p(_ctx("no native lib here")) is False


def test_family_membership_substring():
    p = compile_predicate({"any_libraries": [".so"]})
    assert p(_ctx("", libraries=("libffmpeg.so",))) is True
    assert p(_ctx("", libraries=())) is False


def test_repo_in():
    p = compile_predicate({"repo_in": ["android-gpuimage-plus"]})
    assert p(SkillCtx(Signals(), "android-gpuimage-plus", "")) is True
    assert p(SkillCtx(Signals(), "organicmaps", "")) is False


def test_clauses_are_or_across_keys():
    p = compile_predicate({"any_text": ["nomatch"], "any_text_regex": [r"lib\w+\.so"]})
    assert p(_ctx("libffmpeg.so")) is True     # second clause fires though first does not


def test_deterministic():
    p = compile_predicate({"any_text": ["crash"]})
    c = _ctx("crash")
    assert p(c) is True and p(c) is True
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/skills/test_predicate.py -q`
  Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — `groundloop/skills/predicate.py`

```python
"""Compile a Skill's declarative `match` spec (from the seed TOML) into a pure predicate closure.
Closed vocabulary only (unknown key -> ValueError); regexes compiled eagerly (bad pattern -> ValueError
at load). No eval/exec, no serialized code: the seed stays reviewable data. A block's clauses are OR'd
(the skill applies if ANY fires); an empty spec never fires; `all_text` is the AND escape hatch."""
from __future__ import annotations

import re
from typing import Callable

from groundloop.skills.ctx import SkillCtx

_FAMILIES = ("packages", "classes", "methods", "symbols", "libraries", "errors")
_LIT_KEYS = ("any_text", "all_text") + tuple(f"any_{f}" for f in _FAMILIES)
_RE_KEYS = ("any_text_regex",) + tuple(f"any_{f}_regex" for f in _FAMILIES)
_VALID = {"always", "repo_in"} | set(_LIT_KEYS) | set(_RE_KEYS)


def compile_predicate(spec: dict) -> Callable[[SkillCtx], bool]:
    bad = set(spec) - _VALID
    if bad:
        raise ValueError(f"unknown predicate keys: {sorted(bad)} (valid: {sorted(_VALID)})")
    lits = {k: tuple(str(x).lower() for x in spec[k]) for k in _LIT_KEYS if k in spec}
    try:
        res = {k: tuple(re.compile(str(x), re.I) for x in spec[k]) for k in _RE_KEYS if k in spec}
    except re.error as e:
        raise ValueError(f"bad regex in predicate: {e}") from e
    repo_in = tuple(str(x).lower() for x in spec.get("repo_in", ()))
    always = bool(spec.get("always", False))

    def _pred(ctx: SkillCtx) -> bool:
        clauses = []
        if always:
            clauses.append(True)
        if "any_text" in lits:
            clauses.append(any(t in ctx.text for t in lits["any_text"]))
        if "all_text" in lits:
            clauses.append(all(t in ctx.text for t in lits["all_text"]))
        if "any_text_regex" in res:
            clauses.append(any(p.search(ctx.text) for p in res["any_text_regex"]))
        for f in _FAMILIES:
            toks = [t.lower() for t in getattr(ctx.signals, f)]
            if f"any_{f}" in lits:
                clauses.append(any(lit in tok for lit in lits[f"any_{f}"] for tok in toks))
            if f"any_{f}_regex" in res:
                clauses.append(any(p.search(tok) for p in res[f"any_{f}_regex"] for tok in toks))
        if repo_in:
            clauses.append((ctx.repo or "").lower() in repo_in)
        return any(clauses)

    return _pred
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_predicate.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add groundloop/skills/predicate.py tests/skills/test_predicate.py
git commit -m "feat(skills): compile declarative match spec -> predicate closure (SP3-T3)"
```

---

### Task 4: `MockSkillRegistry` + real-data seed (+ optional bge-m3 rerank seam)

**Files:**
- Create: `groundloop/adapters/skills/__init__.py` (empty)
- Create: `groundloop/adapters/skills/mock.py`
- Create: `groundloop/adapters/skills/data/aaos_playbooks.toml`
- Test: `tests/skills/test_mock_registry.py`

- [ ] **Step 1: Write the seed** — `groundloop/adapters/skills/data/aaos_playbooks.toml` (REAL playbooks;
  guidance names no fleet repo — leak-safe; playbooks 1–2 fire on defect crash logs, 3–4 are ops
  null-controls that correctly do NOT fire on a defect ticket):

```toml
# Development-experience KB seed — REAL playbooks distilled from GroundLoop RCA/ops experience.
# "Mock" = the registry WIRING; the CONTENT is real, so the measured arm sees a genuine (small) effect.
# Real Skills swap in by REPLACING this data file (see docs/skill-kb-migration.md) — no code change.
# Each [skill.match] is a DECLARATIVE predicate compiled by groundloop/skills/predicate.compile_predicate
# (no code in data). Oracle-blind: guidance must name no fleet repo (enforced by a leak red-test).

[[skill]]
id = "aaos-native-lib-load-failure"
provenance = "docs/type2-atlas-build-findings.md; AAOS native-lib load RCA"
signals = ["native", "so", "unsatisfiedlinkerror"]
guidance = """
UnsatisfiedLinkError / "couldn't find lib*.so" on an AAOS device is a native-library load failure, not a
Java bug. Triage: (1) confirm the .so is packaged for the device ABI (arm64-v8a vs armeabi-v7a) under
jniLibs/<abi>/; (2) "No implementation found for <method>" means the JNI symbol is unregistered — a
missing RegisterNatives call or a static-JNI name mismatch (Java_<pkg>_<Class>_<method>); (3) verify the
loader (System.loadLibrary) runs before the first native call. Fix at the JNI interface that declares the
missing native method, not at the Java call site."""

[skill.match]
any_text = ["unsatisfiedlinkerror", "no implementation found", "couldn't find", "load library"]
any_text_regex = ["lib\\w+\\.so"]

[[skill]]
id = "jni-native-handle-lifecycle"
provenance = "AAOS JNI native-handle RCA"
signals = ["jni", "nativecreate", "handle"]
guidance = """
A native "handle" (jlong returned by nativeCreateHandler / nativeInit) has a strict create->use->release
lifecycle. Crashes at nativeCreateHandler / (Native Method) usually mean the native symbol is
unregistered or the handle is used after release. RCA: pair every nativeCreate* with a nativeRelease*,
guard against a 0/null handle before native calls, and confirm the JNI signature in the C/C++ interface
matches the Java `native` declaration exactly."""

[skill.match]
any_text = ["nativecreatehandler", "native method", "registernatives", "nativecreate", "nativerelease"]

[[skill]]
id = "cbm-index-ops"
provenance = "docs/type2-atlas-build-findings.md Finding 5/6 (CBM timeout + pgrep)"
signals = ["cbm", "index", "timeout"]
guidance = """
CodebaseMemory (CBM) index "hangs" are a 30s call-timeout tripping a minutes-long cold build, not a
deadlock. Raise KLOOP_CBM_INDEX_TIMEOUT (default 1800s), build the atlas from a native-ext4 copy of the
repos (not the slow /mnt/x v9fs mount), avoid concurrent `gloop index` jobs (contention pushes cold
builds past the timeout), and check liveness with `pgrep -fa 'gloop index'` — never `ps -C` (comm=gloop)."""

[skill.match]
any_text = ["codebase-memory", "cbm index", "index timeout", "call_timeout"]

[[skill]]
id = "produce-giant-repo"
provenance = "docs/type2-atlas-build-findings.md Finding 1/2 (produce + load_wiki)"
signals = ["produce", "codewiki", "wiki"]
guidance = """
`produce` (CodeWiki) is DeepSeek-latency-bound and crashes to an empty wiki on 2k-4k-file giants. For
Stage-1 matching prefer a symbol-only atlas: skip produce and run `gloop index` directly — CBM symbol
units carry the package/class/method/.so tokens the matcher needs and still get bge-m3 vectors. The index
path tolerates a missing/incomplete wiki (empty WikiData)."""

[skill.match]
any_text = ["codewiki", "produce stage", "empty wiki", "load_wiki"]
```

- [ ] **Step 2: Write the failing test** — `tests/skills/test_mock_registry.py`

```python
from pathlib import Path

from groundloop.adapters.skills.mock import MockSkillRegistry, load_skills, SEED_PATH
from groundloop.core.types import Signals
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.skills.ctx import SkillCtx

CRASH = ("java.lang.unsatisfiedlinkerror: no implementation found for "
         "org.wysaid.nativeport.cgeimagehandler.nativecreatehandler()\n"
         "e/libcge_java: load library for 'cge' failed!: couldn't find \"libffmpeg.so\"")


def _ctx(text):
    return SkillCtx(signals=Signals(), repo="android-gpuimage-plus", text=text)


def test_load_seed_skills_have_predicates_and_provenance():
    skills = load_skills(SEED_PATH)
    ids = {s.id for s in skills}
    assert {"aaos-native-lib-load-failure", "jni-native-handle-lifecycle"} <= ids
    assert all(s.provenance and callable(s.applies_to) for s in skills)


def test_select_fires_native_playbooks_on_crash_log():
    reg = MockSkillRegistry.load(SEED_PATH)
    hit = {s.id for s in reg.select(_ctx(CRASH))}
    assert "aaos-native-lib-load-failure" in hit and "jni-native-handle-lifecycle" in hit
    assert "cbm-index-ops" not in hit and "produce-giant-repo" not in hit    # ops null-controls silent


def test_select_silent_on_non_native_ticket():
    reg = MockSkillRegistry.load(SEED_PATH)
    ctx = _ctx("live preview freezes intermittently; no crash; ui stops refreshing")
    assert reg.select(ctx) == []      # empty -> empty preamble -> byte-identical none arm


def test_predicate_only_is_deterministic():
    reg = MockSkillRegistry.load(SEED_PATH)
    assert [s.id for s in reg.select(_ctx(CRASH))] == [s.id for s in reg.select(_ctx(CRASH))]


def test_optional_embedder_rerank_is_deterministic_and_capped():
    # StubEmbedder = offline deterministic vectors; rerank must return a stable, <=top_k ordering
    reg = MockSkillRegistry.load(SEED_PATH, embedder=StubEmbedder(), top_k=1)
    out = reg.select(_ctx(CRASH))
    assert len(out) == 1
    assert [s.id for s in out] == [s.id for s in MockSkillRegistry.load(
        SEED_PATH, embedder=StubEmbedder(), top_k=1).select(_ctx(CRASH))]
```

- [ ] **Step 3: Run, verify fail** — `.venv/bin/python -m pytest tests/skills/test_mock_registry.py -q`
  Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement** — `groundloop/adapters/skills/mock.py` (predicate-only default; optional
  bge-m3 rerank over `guidance` keyed on the ctx query, embedding guidance once at construction):

```python
"""MockSkillRegistry — the SP3 KB adapter. `select` = predicate filter (hermetic, deterministic default)
+ an OPTIONAL bge-m3 rerank over guidance (gated: pass an embedder). "Mock" = the wiring; the seed content
is real. Real Skills swap in by replacing the data file / passing a different loader (docs/skill-kb-
migration.md). Reads ONLY its seed data + the loop-visible SkillCtx — never _oracle/."""
from __future__ import annotations

import math
import tomllib
from pathlib import Path

from groundloop.skills.base import Skill
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate

SEED_PATH = str(Path(__file__).parent / "data" / "aaos_playbooks.toml")


def load_skills(path: str) -> list[Skill]:
    raw = tomllib.loads(Path(path).read_text())
    out: list[Skill] = []
    for e in raw.get("skill", []):
        out.append(Skill(
            id=e["id"],
            applies_to=compile_predicate(e.get("match", {})),
            guidance=e["guidance"].strip(),
            hint_apis=tuple(e.get("hint_apis", ())),
            signals=tuple(e.get("signals", ())),
            provenance=e.get("provenance", ""),
        ))
    return out


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class MockSkillRegistry:
    def __init__(self, skills: list[Skill], *, embedder=None, top_k: int = 3):
        self.skills = list(skills)
        self.embedder = embedder
        self.top_k = top_k
        # embed guidance ONCE (pinned bge-m3; query==index) — only when a live/stub embedder is attached
        self._gvecs = self.embedder.embed([s.guidance for s in self.skills]) if self.embedder else None

    @classmethod
    def load(cls, path: str = SEED_PATH, *, embedder=None, top_k: int = 3) -> "MockSkillRegistry":
        return cls(load_skills(path), embedder=embedder, top_k=top_k)

    def select(self, ctx: SkillCtx) -> list[Skill]:
        hits = [(i, s) for i, s in enumerate(self.skills) if s.applies_to(ctx)]   # predicate stage
        if self.embedder is None or not hits:
            return [s for _, s in hits]                                            # hermetic default
        qvec = self.embedder.embed([ctx.text or " ".join(ctx.tokens())])[0]        # bge-m3 rerank (gated)
        scored = sorted(hits, key=lambda p: (-_cos(qvec, self._gvecs[p[0]]), self.skills[p[0]].id))
        return [s for _, s in scored[: self.top_k]]
```

- [ ] **Step 5: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_mock_registry.py -q` → PASS.
- [ ] **Step 6: Commit**

```bash
git add groundloop/adapters/skills/ tests/skills/test_mock_registry.py
git commit -m "feat(skills): MockSkillRegistry + real-data seed + gated bge-m3 rerank (SP3-T4)"
```

---

## Phase B — Injection seam, runner wiring, direction-of-effect

### Task 5: `ModelPatchEngine` preamble injection

**Files:**
- Modify: `groundloop/adapters/fix/model_patch.py`
- Test: `tests/fixeval/test_model_patch_engine.py` (extend)

- [ ] **Step 1: Write the failing test** — append to `tests/fixeval/test_model_patch_engine.py`:

```python
class _CapturingModel:
    def __init__(self):
        self.prompt = None

    def complete(self, prompt: str) -> str:
        self.prompt = prompt
        return ""


def test_preamble_is_prepended_to_prompt(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "A.cpp").write_text("// bug\n")
    cap = _CapturingModel()
    eng = ModelPatchEngine(cap).with_preamble("\n\n# Applicable playbooks\n## Skill: s\ndo it")
    eng.propose(WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d"), ["x/A.cpp"])
    assert cap.prompt.startswith("\n\n# Applicable playbooks")
    assert "Bug: s" in cap.prompt


def test_empty_preamble_is_noop(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "A.cpp").write_text("// bug\n")
    cap_off, cap_on = _CapturingModel(), _CapturingModel()
    wt, tk = WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d")
    ModelPatchEngine(cap_off).propose(wt, tk, ["x/A.cpp"])
    ModelPatchEngine(cap_on, preamble="").propose(wt, tk, ["x/A.cpp"])
    assert cap_off.prompt == cap_on.prompt   # empty preamble => byte-identical prompt


def test_with_preamble_shares_model_for_cost():
    m = CannedModel({"default": ""})
    base = ModelPatchEngine(m)
    assert base.with_preamble("p").model is m   # cost accrues on the shared model instance
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/fixeval/test_model_patch_engine.py -q`
  Expected: FAIL (`with_preamble` / `preamble` absent).

- [ ] **Step 3: Implement** — edit `groundloop/adapters/fix/model_patch.py` (`__init__`, add
  `with_preamble`, prepend in `propose`):

```python
class ModelPatchEngine:
    def __init__(self, model, preamble: str = ""):
        self.model = model
        self.preamble = preamble

    def with_preamble(self, preamble: str) -> "ModelPatchEngine":
        """A skills-aware clone sharing self.model (so GatewayModel.cost_usd keeps accruing)."""
        return ModelPatchEngine(self.model, preamble=preamble)

    def _snippet(self, wt_path: str, loc: str, max_lines: int = 40) -> str:
        p = Path(wt_path) / loc
        if not p.is_file():
            return ""
        return f"### {loc}\n" + "\n".join(p.read_text(errors="replace").splitlines()[:max_lines])

    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch:
        snippets = "\n\n".join(self._snippet(worktree.path, loc) for loc in locations)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Candidate files:\n{snippets}\n\n"
                  "Reply ONLY with a unified diff (```diff fenced) that fixes the bug, or empty if you cannot.")
        if self.preamble:
            prompt = self.preamble + "\n\n" + prompt
        diff = extract_unified_diff(self.model.complete(prompt) or "")
        return Patch(diff=diff, files=tuple(touched_files(diff)))
```

- [ ] **Step 4: Run, verify pass** — targeted test → PASS. Then the full fix suite to prove the default
  path is unchanged: `.venv/bin/python -m pytest tests/fixeval -q` → PASS (the 4 existing
  `ModelPatchEngine(model)` call sites still green).
- [ ] **Step 5: Commit**

```bash
git add groundloop/adapters/fix/model_patch.py tests/fixeval/test_model_patch_engine.py
git commit -m "feat(fixeval): ModelPatchEngine preamble injection seam (SP3-T5)"
```

---

### Task 6: Wire skills into `FixEvalRunner` (post-match select/render/inject)

**Files:**
- Modify: `groundloop/fixeval/runner.py`
- Test: `tests/fixeval/test_skill_injection.py` (new)

- [ ] **Step 1: Write the failing test** — `tests/fixeval/test_skill_injection.py`

```python
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]


class _Capture:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return ""


def _runner(tmp_path, skills):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return (FixEvalRunner(issues=MockJira(str(ds)),
                          estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "w")),
                          catalog=CATALOG, tau_margin=0.0, tau_score=0.0, skills=skills),
            load_cases(str(ds)))


def test_skills_none_is_noop(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, skills=None)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    assert cap.prompts and not any("# Applicable playbooks" in p for p in cap.prompts)


def test_skills_mock_injects_native_playbook(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    cap = _Capture()
    runner, cases = _runner(tmp_path, skills=MockSkillRegistry.load())
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(cap))
    injected = [p for p in cap.prompts if "# Applicable playbooks" in p]
    assert injected, "skills=mock must inject a preamble on the native crash case"
    assert any("aaos-native-lib-load-failure" in p for p in injected)
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/fixeval/test_skill_injection.py -q`
  Expected: FAIL (`FixEvalRunner.__init__` has no `skills`).

- [ ] **Step 3: Implement** — edit `groundloop/fixeval/runner.py`. Add imports at top:

```python
from groundloop.skills.base import render_skills
from groundloop.skills.ctx import build_ctx
```

Add `skills=None` to `__init__`:

```python
    def __init__(self, *, issues, estate, catalog, tau_margin: float, tau_score: float,
                 max_refine: int = 1, skills=None):
        self.issues = issues
        self.estate = estate
        self.catalog = list(catalog)
        self.tau_margin = tau_margin
        self.tau_score = tau_score
        self.max_refine = max_refine
        self.skills = skills                     # a SkillRegistry or None (the `--skills` arm knob)
```

In `_one`, after `predicted = d.predicted` and before `wt = self.estate.materialize(...)`, select +
render (post-match; empty preamble when nothing applies) and swap in a preamble'd fixer for the propose
calls:

```python
        predicted = d.predicted
        # SKILL INJECTION (post-match, oracle-blind): key on the arm's signals + the predicted repo +
        # the raw ticket/log haystack. Empty when no playbook applies -> byte-identical to skills=none.
        f = fixer
        if self.skills is not None:
            preamble = render_skills(self.skills.select(build_ctx(signals, ticket, predicted)))
            if preamble:
                f = fixer.with_preamble(preamble)
        c0 = self._cost(fixer)
        wt = self.estate.materialize(RepoRef(predicted))
        locations = localize(arm.index, predicted, signals, ticket.summary)
        if not locations:
            return rec(predicted_repo=predicted, abstain_reason="no_localization",
                       cost_usd=self._cost(fixer) - c0)
        patch = f.propose(wt, ticket, locations)
        applies = patch_applies(patch.diff, wt.path)
        iters = 0
        while patch.diff and not applies and iters < self.max_refine:
            iters += 1
            patch = f.propose(wt, ticket, locations)
            applies = patch_applies(patch.diff, wt.path)
```

(Leave the rest of `_one` unchanged; `_cost` reads `fixer.model`, which `f` shares.)

- [ ] **Step 4: Run, verify pass** — targeted test → PASS; then `.venv/bin/python -m pytest tests/fixeval -q`
  → PASS (existing runner tests unaffected: default `skills=None`).
- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/runner.py tests/fixeval/test_skill_injection.py
git commit -m "feat(fixeval): wire skills arm into FixEvalRunner post-match (SP3-T6)"
```

---

### Task 7: Hermetic direction-of-effect + null-path (honest framing)

**Files:**
- Test: `tests/fixeval/test_skill_effect.py` (new)

**Honesty note (put in the test module docstring):** this proves the arm's **plumbing + direction of
effect** — a scripted `CannedModel` emits the GOLD diff only when the playbook preamble is present. It
does **not** claim a real lift magnitude; the real (small) lift on live models is a Type-2 gated
measurement (T14), flagged directional-only per spec §5.

- [ ] **Step 1: Write the test** — `tests/fixeval/test_skill_effect.py`

```python
"""Hermetic direction-of-effect for the KB arm. A scripted CannedModel returns the GOLD diff ONLY when
the '# Applicable playbooks' preamble is present -> proves the arm MOVES an outcome (abstain -> applying
patch) via the injection plumbing. NOT a real-lift claim (that is the Type-2 gated measurement)."""
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.fixeval.scorecard import grade_fix_all
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
GOLD = ("```diff\n"
        "--- a/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "+++ b/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "@@ -1,4 +1,4 @@\n"
        "-// bug\n"
        "+// fixed nativeCreateHandler\n"
        ' #include "cgeImageHandler.h"\n'
        " namespace CGE {\n"
        " jlong nativeCreateHandler(JNIEnv*, jclass) {\n"
        "```")


def _run(tmp_path, db, skills):
    ds = tmp_path / ("on" if skills else "off")
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    # model emits GOLD only when the playbook header is present; empty otherwise
    model = CannedModel({"# Applicable playbooks": GOLD, "default": ""})
    runner = FixEvalRunner(issues=MockJira(str(ds)),
                           estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / ("w_on" if skills else "w_off"))),
                           catalog=CATALOG, tau_margin=0.0, tau_score=0.0, skills=skills)
    cases = load_cases(str(ds))
    recs = runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=ModelPatchEngine(model))
    oracle = {c.case_id: load_eval_oracle(c) for c in cases}
    return recs, grade_fix_all(recs, oracle_by_case=oracle)


def test_skills_arm_moves_outcome_on_native_positive(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    off_recs, off_card = _run(tmp_path, db, skills=None)
    on_recs, on_card = _run(tmp_path, db, skills=MockSkillRegistry.load())
    off = next(r for r in off_recs if r.arm == "membership+logs")
    on = next(r for r in on_recs if r.arm == "membership+logs")
    assert off.abstained and off.abstain_reason == "patch_unappliable"   # no preamble -> "" -> abstain
    assert on.patch_emitted and on.patch_applies and not on.abstained    # preamble -> GOLD -> applies
    assert off_card["arms"]["membership+logs"]["file_recall@1"]["value"] == 0.0
    assert on_card["arms"]["membership+logs"]["file_recall@1"]["value"] == 1.0
```

- [ ] **Step 2: Run, verify pass** — `.venv/bin/python -m pytest tests/fixeval/test_skill_effect.py -q` → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/fixeval/test_skill_effect.py
git commit -m "test(fixeval): hermetic direction-of-effect for the KB arm (SP3-T7)"
```

---

## Phase C — Two-sided grading, CLI arm, leak invariants

### Task 8: Extend `compare` with metric deltas + accept gate

**Files:**
- Modify: `groundloop/fixeval/compare.py`
- Test: `tests/fixeval/test_compare_metrics.py` (new)

- [ ] **Step 1: Write the failing test** — `tests/fixeval/test_compare_metrics.py`

```python
from groundloop.fixeval.compare import compare_metrics, accept


def _arm(fr1, fab, cost, phi):
    return {"file_recall@1": {"value": fr1}, "file_recall@3": {"value": fr1},
            "file_recall@5": {"value": fr1}, "resolved_rate": {"value": None},
            "patch_apply_rate": 1.0, "fabrication_rate": {"value": fab},
            "cost_per_solved": cost, "cost_total": 0.0, "phi_c": {"1.0": phi}}


def test_compare_metrics_computes_deltas_none_safe():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.8, 0.0, 0.12, 0.7))
    assert abs(m["file_recall@1"]["delta"] - 0.3) < 1e-9
    assert m["resolved_rate"]["delta"] is None          # None on either side -> None (no crash)
    assert abs(m["phi_c@1.0"]["delta"] - 0.2) < 1e-9


def test_accept_positive_lift_no_honesty_regression():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.8, 0.0, 0.12, 0.7))
    v = accept(m, {"newly_solved": ["c1"], "newly_broken": []})
    assert v["accepted"] and v["pos_ok"] and v["honesty_ok"]


def test_accept_rejects_fabrication_rise():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.9, 0.25, 0.10, 0.6))   # fabrication up
    v = accept(m, {"newly_solved": ["c1"], "newly_broken": []})
    assert not v["accepted"] and not v["honesty_ok"]
    assert any("fabrication" in r for r in v["reasons"])


def test_accept_rejects_no_lift():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.5, 0.0, 0.10, 0.5))
    v = accept(m, {"newly_solved": [], "newly_broken": []})
    assert not v["accepted"] and not v["pos_ok"]


def test_accept_cost_budget_optional_gate():
    m = compare_metrics(_arm(0.5, 0.0, 0.10, 0.5), _arm(0.8, 0.0, 0.30, 0.7))    # cost tripled
    assert accept(m, {"newly_solved": ["c1"], "newly_broken": []})["accepted"]   # advisory by default
    assert not accept(m, {"newly_solved": ["c1"], "newly_broken": []}, cost_budget=0.05)["accepted"]
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/fixeval/test_compare_metrics.py -q`
  Expected: FAIL (`ImportError: compare_metrics`).

- [ ] **Step 3: Implement** — append to `groundloop/fixeval/compare.py` (pure add; `compare` unchanged;
  every scalar already lives in the board JSON from `grade_fix_all`):

```python
def _val(metric):
    return metric.get("value") if isinstance(metric, dict) else metric


def _delta(base, head):
    """head - base, None-safe (None on either side -> None; never raises on empty subsets)."""
    if base is None or head is None:
        return None
    return head - base


_POS = ("file_recall@1", "file_recall@3", "file_recall@5", "resolved_rate", "patch_apply_rate")
_NEG = ("fabrication_rate",)
_COST = ("cost_per_solved", "cost_total")


def compare_metrics(base_arm: dict, head_arm: dict) -> dict:
    """Per-arm {metric: {base, head, delta}} for the POS/NEG/COST scalars in a fix scorecard."""
    out: dict = {}
    for m in _POS + _NEG + _COST:
        b, h = _val(base_arm.get(m)), _val(head_arm.get(m))
        out[m] = {"base": b, "head": h, "delta": _delta(b, h)}
    b = base_arm.get("phi_c", {}).get("1.0")
    h = head_arm.get("phi_c", {}).get("1.0")
    out["phi_c@1.0"] = {"base": b, "head": h, "delta": _delta(b, h)}
    return out


def accept(metrics_cmp: dict, resolved_cmp: dict, *, cost_budget: float | None = None) -> dict:
    """The SP3 two-sided verdict. POS = Δfile_recall@1>0 OR newly_solved>newly_broken; NEG (honesty) =
    Δfabrication_rate<=0 (None = no Bucket-1 in set, not a regression); COST = advisory unless a
    cost_budget is given. abstention_recall_oof is a Stage-1 metric, invariant to skills (asserted
    elsewhere), so it is not diffed here."""
    dfr = metrics_cmp["file_recall@1"]["delta"]
    dfab = metrics_cmp["fabrication_rate"]["delta"]
    dcost = metrics_cmp["cost_per_solved"]["delta"]
    ns, nb = len(resolved_cmp.get("newly_solved", [])), len(resolved_cmp.get("newly_broken", []))
    pos_ok = (dfr is not None and dfr > 0) or ns > nb
    honesty_ok = dfab is None or dfab <= 0
    cost_ok = cost_budget is None or dcost is None or dcost <= cost_budget
    reasons = []
    if not pos_ok:
        reasons.append("no positive lift (Δfile_recall@1<=0 and newly_solved<=newly_broken)")
    if not honesty_ok:
        reasons.append(f"fabrication_rate rose (Δ={dfab})")
    if not cost_ok:
        reasons.append(f"cost_per_solved rose beyond budget (Δ={dcost})")
    return {"accepted": pos_ok and honesty_ok and cost_ok, "pos_ok": pos_ok,
            "honesty_ok": honesty_ok, "cost_ok": cost_ok,
            "newly_solved": ns, "newly_broken": nb, "reasons": reasons}
```

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/fixeval/test_compare_metrics.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add groundloop/fixeval/compare.py tests/fixeval/test_compare_metrics.py
git commit -m "feat(fixeval): compare_metrics + two-sided accept gate (SP3-T8)"
```

---

### Task 9: CLI — `--skills {none,mock}` + verdict surface

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_run_fixeval`, `_run_compare`, argparse)
- Test: `tests/fixeval/test_cli_skills.py` (new)

- [ ] **Step 1: Write the failing test** — `tests/fixeval/test_cli_skills.py`

```python
import json
import shutil
from pathlib import Path

from groundloop.cli import main
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"


def _ds(tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return ds


def test_fixeval_skills_flag_runs_both_arms(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)   # hermetic canned path
    ds, db = _ds(tmp_path), build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    common = ["--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
              "--index-db", db, "--repos", str(FIX / "repos")]
    assert main(["fixeval", *common, "--skills", "none", "--out", str(tmp_path / "off.json")]) == 0
    assert main(["fixeval", *common, "--skills", "mock", "--out", str(tmp_path / "on.json")]) == 0
    assert (tmp_path / "off.json").is_file() and (tmp_path / "on.json").is_file()


def test_compare_emits_accept_verdict(tmp_path):
    # hand-built off/on boards -> compare CLI writes a verdict json with the accept gate
    def board(fr1, fab):
        return {"arms": {"membership+logs": {
            "n": 1, "patch_apply_rate": 1.0, "n_gradeable": 1, "resolved_by_case": {"GP-352": None},
            "file_recall@1": {"value": fr1}, "file_recall@3": {"value": fr1}, "file_recall@5": {"value": fr1},
            "resolved_rate": {"value": None}, "required_api_pass_rate": {"value": None},
            "fabrication_rate": {"value": fab}, "cost_per_solved": None, "cost_total": 0.0,
            "phi_c": {"1.0": fr1}}}}
    (tmp_path / "off.json").write_text(json.dumps(board(0.0, 0.0)))
    (tmp_path / "on.json").write_text(json.dumps(board(1.0, 0.0)))
    out = tmp_path / "verdict.json"
    rc = main(["compare", "--base", str(tmp_path / "off.json"), "--head", str(tmp_path / "on.json"),
               "--arm", "membership+logs", "--out", str(out)])
    assert rc == 0
    v = json.loads(out.read_text())
    assert v["verdict"]["accepted"] and v["metrics"]["file_recall@1"]["delta"] == 1.0
```

- [ ] **Step 2: Run, verify fail** — `.venv/bin/python -m pytest tests/fixeval/test_cli_skills.py -q`
  Expected: FAIL (`--skills` unknown / compare lacks verdict).

- [ ] **Step 3: Implement** — in `groundloop/cli/__init__.py`:

  (a) `fixeval` parser — add the flag (near the other `fx.add_argument`s):

```python
    fx.add_argument("--skills", choices=["none", "mock"], default="none",
                    help="dev-experience KB arm: none (baseline) | mock (real-data seed)")
```

  (b) `_run_fixeval` — build the registry and pass it to the runner (gate the bge-m3 rerank on
  `KLOOP_EMBED_*`, else predicate-only). After `cases = load_cases(...)` and before constructing the
  runner:

```python
    skills = None
    if args.skills == "mock":
        from groundloop.adapters.skills.mock import MockSkillRegistry
        embedder = None
        if os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
            from groundloop.engines.atlas.embed import GatewayEmbedder
            from groundloop.config.settings import Settings
            st = Settings.load()
            embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
        skills = MockSkillRegistry.load(embedder=embedder)
```

  and add `skills=skills` to the `FixEvalRunner(...)` call.

  (c) `compare` parser (the existing `cmp = sub.add_parser("compare", ...)` block) — add `--out`:

```python
    cmp.add_argument("--out", default="", help="write the full compare (metrics+verdict) JSON here")
```

  (d) `_run_compare` — read the FULL arm dicts (not just `resolved_by_case`), compute
  `compare` + `compare_metrics` + `accept`, print + optionally write:

```python
def _run_compare(args) -> int:
    import json
    from pathlib import Path
    from groundloop.fixeval.compare import compare, compare_metrics, accept

    def _arms(path):
        return json.loads(Path(path).read_text()).get("arms", {})

    base_arms, head_arms = _arms(args.base), _arms(args.head)
    arm = args.arm if args.arm else (next(iter(base_arms)) if base_arms else None)
    base_arm, head_arm = base_arms.get(arm, {}), head_arms.get(arm, {})
    resolved = compare(base_arm.get("resolved_by_case", {}), head_arm.get("resolved_by_case", {}))
    metrics = compare_metrics(base_arm, head_arm)
    verdict = accept(metrics, resolved, cost_budget=args.cost_budget)
    result = {"arm": arm, "resolved": resolved, "metrics": metrics, "verdict": verdict}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"compare[{arm}]: Δfile_recall@1={metrics['file_recall@1']['delta']} "
          f"Δfabrication={metrics['fabrication_rate']['delta']} "
          f"newly_solved={verdict['newly_solved']} newly_broken={verdict['newly_broken']} "
          f"-> {'ACCEPT' if verdict['accepted'] else 'REJECT'} {verdict['reasons']}")
    return 0
```

  (e) `compare` parser — add `cmp.add_argument("--cost-budget", dest="cost_budget", type=float,
  default=None)`. (`os` is already imported in `_run_fixeval`. No existing CLI-level `compare` test
  exists — only `compare()` is unit-tested directly in `tests/fixeval/test_compare.py` — so this
  `_run_compare` rewrite breaks nothing.)

- [ ] **Step 4: Run, verify pass** — `.venv/bin/python -m pytest tests/fixeval/test_cli_skills.py -q` → PASS;
  then `.venv/bin/python -m pytest tests/fixeval/test_compare.py -q` → PASS (old `compare` untouched).
- [ ] **Step 5: Commit**

```bash
git add groundloop/cli/__init__.py tests/fixeval/test_cli_skills.py
git commit -m "feat(cli): gloop fixeval --skills + compare accept verdict (SP3-T9)"
```

---

### Task 10: Leak / oracle-blindness invariants for the KB

**Files:**
- Test: `tests/skills/test_invariants.py` (new)

- [ ] **Step 1: Write the test** — `tests/skills/test_invariants.py`

```python
"""Anti-leak invariants for the KB arm: the registry/ctx read no _oracle/, the seed guidance names no
fleet repo, and an empty preamble is a true no-op (so the measured Δ is clean)."""
import pathlib
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.skills.mock import MockSkillRegistry, load_skills, SEED_PATH
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
FLEET = ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview", "oboe", "osmand")


def test_seed_guidance_names_no_fleet_repo():
    for s in load_skills(SEED_PATH):
        blob = (s.guidance + " " + s.provenance).lower()
        for repo in FLEET:
            assert repo.lower() not in blob, f"skill {s.id} leaks fleet repo {repo}"


def test_skills_path_never_reads_oracle(tmp_path, monkeypatch):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])
    FixEvalRunner(issues=MockJira(str(ds)),
                  estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / "w")),
                  catalog=[RepoRef("android-gpuimage-plus")], tau_margin=0.0, tau_score=0.0,
                  skills=MockSkillRegistry.load()).run(
        load_cases(str(ds)), build_arms(membership_index=AtlasIndex(db)),
        fixer=ModelPatchEngine(CannedModel({"default": ""})))
    leaked = [r for r in reads if "_oracle" in pathlib.Path(r).parts]
    assert not leaked, f"KB path read the oracle: {leaked}"


def test_non_applicable_case_preamble_is_empty(tmp_path):
    from groundloop.core.types import Signals, Ticket, LogAttachment
    from groundloop.skills.base import render_skills
    from groundloop.skills.ctx import build_ctx
    tk = Ticket(id="NEG", summary="Live preview freezes intermittently",
                description="No crash is shown; the UI just stops refreshing.",
                logs=(LogAttachment(path="l", kind="logcat", content="ui stops refreshing"),))
    preamble = render_skills(MockSkillRegistry.load().select(build_ctx(Signals(), tk, "cameraview")))
    assert preamble == ""      # no native/JNI/ops cue -> no skill -> empty -> no-op vs skills=none
```

- [ ] **Step 2: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_invariants.py -q` → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/skills/test_invariants.py
git commit -m "test(skills): KB oracle-blindness + leak + null-path invariants (SP3-T10)"
```

---

## Phase D — Migration guide + parity self-test

### Task 11: `migrate_markdown_skills` + `triggers_to_spec` + fixtures

**Files:**
- Create: `groundloop/adapters/skills/migrate.py`
- Create fixtures: `tests/fixtures/skills/__init__.py` (empty — `panel.py` is imported as
  `tests.fixtures.skills.panel`, so the dir must be a package), `tests/fixtures/skills/md/native.md`,
  `tests/fixtures/skills/md/jni.md`, `tests/fixtures/skills/seed.toml`, `tests/fixtures/skills/panel.py`
- Test: `tests/skills/test_migrate.py`

**Why a *different* shape:** the parity test is only meaningful if the two registries load **genuinely
different** encodings. The foreign format is markdown + front-matter with a **foreign trigger
vocabulary** (`triggers: native-crash, so-load-failure`) that the shipped `triggers_to_spec` must
translate into the same predicate the native TOML seed expresses directly. A mistranslation flips a
membership over the ctx panel → parity fails (T12).

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/skills/md/native.md`:
```markdown
---
id: aaos-native-lib-load-failure
triggers: native-crash, so-load-failure
provenance: md-fixture:native
---
UnsatisfiedLinkError is a native-library load failure. Check the ABI, RegisterNatives, and loadLibrary
ordering; fix at the JNI interface.
```

`tests/fixtures/skills/md/jni.md`:
```markdown
---
id: jni-native-handle-lifecycle
triggers: jni-handle
provenance: md-fixture:jni
---
Pair every nativeCreate* with a nativeRelease*; guard a null handle; match the JNI signature to the Java
native declaration.
```

`tests/fixtures/skills/seed.toml` (native encoding of the SAME two skills — predicate written directly):
```toml
[[skill]]
id = "aaos-native-lib-load-failure"
provenance = "toml-fixture:native"
guidance = "native lib load failure guidance"
[skill.match]
any_text = ["unsatisfiedlinkerror", "no implementation found", "couldn't find", "load library"]
any_text_regex = ["lib\\w+\\.so"]

[[skill]]
id = "jni-native-handle-lifecycle"
provenance = "toml-fixture:jni"
guidance = "jni handle lifecycle guidance"
[skill.match]
any_text = ["nativecreatehandler", "native method", "registernatives", "nativecreate", "nativerelease"]
```

`tests/fixtures/skills/panel.py` (a **discriminating** ctx panel — each skill matches a proper,
non-empty subset; includes a native-only, a jni-only, a both, and a none):
```python
from groundloop.core.types import Signals
from groundloop.skills.ctx import SkillCtx


def build_panel() -> list[SkillCtx]:
    def c(text):
        return SkillCtx(signals=Signals(), repo="r", text=text.lower())
    return [
        c("java.lang.UnsatisfiedLinkError: couldn't find \"libffmpeg.so\""),   # native only
        c("crash at nativeCreateHandler (Native Method)"),                     # jni (+native via 'native method')
        c("registernatives failed for the handle"),                           # jni only
        c("live preview freezes; no crash; ui stops refreshing"),             # none
    ]
```

- [ ] **Step 2: Write the failing test** — `tests/skills/test_migrate.py`

```python
from pathlib import Path

from groundloop.adapters.skills.migrate import migrate_markdown_skills, triggers_to_spec

MD = Path(__file__).parent.parent / "fixtures" / "skills" / "md"


def test_triggers_to_spec_translates_foreign_vocab():
    spec = triggers_to_spec(["native-crash", "so-load-failure"])
    assert "any_text" in spec and "unsatisfiedlinkerror" in spec["any_text"]
    assert any("lib" in r for r in spec.get("any_text_regex", []))


def test_triggers_to_spec_unknown_trigger_raises():
    import pytest
    with pytest.raises(KeyError):
        triggers_to_spec(["not-a-real-trigger"])


def test_migrate_markdown_produces_skills():
    skills = {s.id: s for s in migrate_markdown_skills(str(MD))}
    assert "aaos-native-lib-load-failure" in skills and "jni-native-handle-lifecycle" in skills
    n = skills["aaos-native-lib-load-failure"]
    assert n.provenance == "md-fixture:native" and callable(n.applies_to) and n.guidance
```

- [ ] **Step 3: Run, verify fail** — `.venv/bin/python -m pytest tests/skills/test_migrate.py -q`
  Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement** — `groundloop/adapters/skills/migrate.py` (author-facing transform; dependency-
  free front-matter parse; the `_TRIGGER_MAP` is the translation the migration guide documents):

```python
"""Author-facing migration transform: foreign markdown+front-matter Skills (the shape the real dev-
experience Skills arrive in post-migration) -> groundloop Skill records. The predicate lives in a FOREIGN
trigger vocabulary (`triggers:`) that triggers_to_spec translates into the same declarative match spec the
native seed carries; compile_predicate then builds the closure. See docs/skill-kb-migration.md."""
from __future__ import annotations

from pathlib import Path

from groundloop.skills.base import Skill
from groundloop.skills.predicate import compile_predicate

# The documented trigger vocabulary -> declarative match-spec fragments. Real migrations extend this map.
_TRIGGER_MAP: dict[str, dict] = {
    "native-crash": {"any_text": ["unsatisfiedlinkerror", "no implementation found", "native method"]},
    "so-load-failure": {"any_text": ["couldn't find", "load library"], "any_text_regex": [r"lib\w+\.so"]},
    "jni-handle": {"any_text": ["nativecreatehandler", "registernatives", "nativecreate", "nativerelease"]},
}


def triggers_to_spec(triggers: list[str]) -> dict:
    """Merge foreign trigger names into one declarative match spec (union per key, de-duped, ordered)."""
    spec: dict[str, list] = {}
    for t in triggers:
        frag = _TRIGGER_MAP[t.strip()]              # KeyError on an undocumented trigger (fail loud)
        for k, vals in frag.items():
            bucket = spec.setdefault(k, [])
            bucket.extend(v for v in vals if v not in bucket)
    return spec


def _parse_front_matter(md: str) -> tuple[dict, str]:
    """Split a `--- ... ---` front-matter block (scalars + comma-lists) from the guidance body."""
    lines = md.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("markdown skill needs a --- front-matter block")
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    meta: dict = {}
    for ln in lines[1:end]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    body = "\n".join(lines[end + 1:]).strip()
    return meta, body


def migrate_markdown_skills(dir_path: str) -> list[Skill]:
    out: list[Skill] = []
    for p in sorted(Path(dir_path).glob("*.md")):
        meta, body = _parse_front_matter(p.read_text())
        triggers = [t for t in meta.get("triggers", "").split(",") if t.strip()]
        out.append(Skill(
            id=meta["id"],
            applies_to=compile_predicate(triggers_to_spec(triggers)),
            guidance=body,
            signals=tuple(t.strip() for t in triggers),
            provenance=meta.get("provenance", f"md:{p.name}"),
        ))
    return out
```

- [ ] **Step 5: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_migrate.py -q` → PASS.
- [ ] **Step 6: Commit**

```bash
git add groundloop/adapters/skills/migrate.py tests/fixtures/skills/ tests/skills/test_migrate.py
git commit -m "feat(skills): markdown->Skill migration transform + fixtures (SP3-T11)"
```

---

### Task 12: Parity self-test + negative control

**Files:**
- Test: `tests/skills/test_migration_parity.py` (new)

- [ ] **Step 1: Write the test** — `tests/skills/test_migration_parity.py`

```python
"""Migration parity: the native TOML seed and the migrated markdown Skills must select IDENTICALLY over a
discriminating ctx panel — proving the shipped transform reproduces author intent. NOT a general proof of
transform correctness (see docs/skill-kb-migration.md 'honesty ceiling'); it regression-guards the
transform + documents the contract. The negative control proves the assertion can fail."""
import dataclasses
from pathlib import Path

from groundloop.adapters.skills.migrate import migrate_markdown_skills
from groundloop.adapters.skills.mock import MockSkillRegistry, load_skills
from groundloop.skills.predicate import compile_predicate
from tests.fixtures.skills.panel import build_panel

FX = Path(__file__).parent.parent / "fixtures" / "skills"


def _ids(reg, ctx):
    return {s.id for s in reg.select(ctx)}


def test_panel_is_discriminating():
    # meta-assert: the panel is not all-empty and not all-match (else parity would be vacuously green)
    native = MockSkillRegistry(load_skills(str(FX / "seed.toml")))
    sizes = [len(native.select(c)) for c in build_panel()]
    assert min(sizes) == 0 and max(sizes) >= 1 and any(0 < s < len(native.skills) for s in sizes)


def test_native_and_migrated_select_identically():
    native = MockSkillRegistry(load_skills(str(FX / "seed.toml")))
    migrated = MockSkillRegistry(migrate_markdown_skills(str(FX / "md")))
    for ctx in build_panel():
        assert _ids(native, ctx) == _ids(migrated, ctx), f"parity break on: {ctx.text!r}"


def test_negative_control_broken_transform_fails_parity():
    # corrupt one migrated skill's predicate -> parity MUST break somewhere on the panel (test has teeth)
    native = MockSkillRegistry(load_skills(str(FX / "seed.toml")))
    skills = migrate_markdown_skills(str(FX / "md"))
    broken = [dataclasses.replace(s, applies_to=compile_predicate({"any_text": ["zzz-never"]}))
              if s.id == "aaos-native-lib-load-failure" else s for s in skills]
    broken_reg = MockSkillRegistry(broken)
    assert any(_ids(native, c) != _ids(broken_reg, c) for c in build_panel())
```

- [ ] **Step 2: Run, verify pass** — `.venv/bin/python -m pytest tests/skills/test_migration_parity.py -q` → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/skills/test_migration_parity.py
git commit -m "test(skills): migration parity self-test + negative control (SP3-T12)"
```

---

### Task 13: Migration guide

**Files:**
- Create: `docs/skill-kb-migration.md`

- [ ] **Step 1: Write the guide** — `docs/skill-kb-migration.md`. It MUST cover (per spec §3.4, D5 TOC):

  1. **Purpose / when to migrate** — the real dev-experience Skills live in another environment and
     arrive post-migration; this guide + the parity self-test let them drop in unchanged.
  2. **The `Skill` contract** — `groundloop/skills/base.py` fields (`id`, `applies_to`, `guidance`,
     `hint_apis`, `signals`, `provenance`) and `render_skills` output (`# Applicable playbooks`).
  3. **The `SkillCtx` contract + oracle-blindness rule** — what a predicate may read (`signals`, `repo`,
     `text`); it must NEVER read `_oracle/` or any expected_files/required_apis.
  4. **Supported source formats + field-mapping table** — markdown front-matter (primary; `id`,
     `triggers`, `provenance`, body→guidance) and the `bfl` `Skill` dataclass (secondary; note `tools`
     is dropped, `signals`/`provenance` default). One row per source field → `Skill` field.
  5. **The shipped transform** — `migrate_markdown_skills`, `triggers_to_spec`, `compile_predicate`; the
     declarative `match` vocabulary (the closed key set from `predicate.py`); id-collision + provenance
     policy. Document that predicates are **data compiled to closures** — never code in the data file.
  6. **Composition-root swap** — replace `MockSkillRegistry.load()` in `cli/__init__.py::_run_fixeval`
     with the migrated registry; the bge-m3 rerank stays gated on `KLOOP_EMBED_*`, pinned bge-m3
     (query==index).
  7. **Parity self-test protocol** — how to add fixtures (native seed + foreign markdown of the SAME
     logical skills + a discriminating ctx panel + a negative control); assert **predicate-only** id-set
     equality (retrieval off / StubEmbedder) — the bge-m3 rerank is Type-2, not in the parity assertion.
  8. **Constraints recap** — no `core/` edit; registry reads only its data + the loop-visible ctx; the
     KB is a **measured arm, not a trusted input** (graded by `gloop compare` → `accept`).
  9. **Honesty ceiling** — the parity test proves the transform reproduces author intent + regression-
     guards it; it does not prove the transform is semantically correct in general. Do not over-read a
     green parity run.

- [ ] **Step 2: Cross-check** — the guide's contract matches the shipped code (fields, vocab, gate).
- [ ] **Step 3: Commit**

```bash
git add docs/skill-kb-migration.md
git commit -m "docs: dev-experience KB (Skills) migration guide + parity protocol (SP3-T13)"
```

---

## Phase E — Type-2 gated live + doc/memory

### Task 14: Gated live KB smoke (bge-m3 rerank + live fix loop)

**Files:**
- Create: `tests/e2e/test_skills_live.py`

- [ ] **Step 1: Write the gated test** — `tests/e2e/test_skills_live.py` (mirror the existing `tests/e2e/`
  `skipif` gating on the `KLOOP_*` env; run the KB arm end-to-end on real bge-m3 + a real model):

```python
"""Type-2 gated: the KB arm end-to-end on real bge-m3 (rerank) + a live fix model. Proves the LIVE
plumbing; the lift magnitude is directional-only on this small seed (spec §5). Skipped without KLOOP_*."""
import os
import shutil
from pathlib import Path

import pytest

from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.engines.atlas.embed import GatewayEmbedder
from groundloop.config.settings import Settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("KLOOP_EMBED_BASE_URL"), reason="Type-2 live: needs KLOOP_EMBED_* gateway")

FIX = Path(__file__).parent.parent / "fixtures"


def test_live_bge_m3_rerank_returns_capped_ordered_skills():
    from groundloop.core.types import Signals
    from groundloop.skills.ctx import SkillCtx
    st = Settings.load()
    reg = MockSkillRegistry.load(embedder=GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model),
                                 top_k=1)
    ctx = SkillCtx(signals=Signals(), repo="android-gpuimage-plus",
                   text="unsatisfiedlinkerror: couldn't find \"libffmpeg.so\" nativecreatehandler")
    out = reg.select(ctx)
    assert 0 < len(out) <= 1 and out[0].id in {"aaos-native-lib-load-failure", "jni-native-handle-lifecycle"}
```

- [ ] **Step 2: Run (gated, expect skip in hermetic env)** —
  `.venv/bin/python -m pytest tests/e2e/test_skills_live.py -q` → `1 skipped` (no `KLOOP_EMBED_*`).
- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_skills_live.py
git commit -m "test(e2e): gated live bge-m3 KB rerank smoke (SP3-T14)"
```

---

### Task 15: Doc + memory updates

**Files:**
- Modify: `docs/type2-evaluation.md`, `docs/downstream-fix-loop.md`, `docs/STATUS.md`
- Modify: `docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md` (mark SP3 landed)

- [ ] **Step 1: `docs/downstream-fix-loop.md`** — where it says the skills arm is aspirational, note that
  the `skills ∈ {none, mock}` arm now exists (`gloop fixeval --skills`, `MockSkillRegistry`, graded by
  `gloop compare` → `accept`), and link `docs/skill-kb-migration.md`.
- [ ] **Step 2: `docs/type2-evaluation.md`** — add the KB arm to the arms/scorecard section: the
  two-sided acceptance (Δfile_recall POS + Δfabrication_rate honesty), directional-only on the mock seed.
- [ ] **Step 3: `docs/STATUS.md`** — record SP3 landed (KB arm + migration guide + parity test); the
  Type-2 track SP1a→SP1b→SP2→SP3 now complete; open follow-on = real-Skill migration + full-seed lift.
- [ ] **Step 4: spec** — add an SP3 "LANDED" note atop §3.
- [ ] **Step 5: Full suite green + ruff, then commit**

```bash
.venv/bin/python -m pytest -q > /tmp/pt.log 2>&1; echo $?      # gate on the printed 0
.venv/bin/ruff check groundloop tests
git add docs/
git commit -m "docs: record SP3 dev-experience KB arm landed (SP3-T15)"
```

---

## Self-Review (checklist run against the spec §3)

- **§3.1 Skill contract + SkillRegistry port** → T1 (`Skill`+`signals`/`provenance`, `SkillRegistry`,
  `render_skills`), T2 (`SkillCtx`), T3 (declarative→compiled `applies_to`). ✅
- **§3.2 MockSkillRegistry seeded with real data** → T4 (`MockSkillRegistry` + `aaos_playbooks.toml`
  distilled from real findings/ops docs; content-as-data via the predicate compile). ✅
- **§3.3 Measured arm + two-sided anti-hallucination acceptance** → T5–T7 (injection + direction-of-
  effect), T8–T9 (`compare_metrics` + `accept`: POS Δfile_recall, NEG Δfabrication_rate), T10
  (null-path + leak invariants). Post-match invariance of `abstention_recall_oof` documented in `accept`. ✅
- **§3.4 Migration guide + parity self-test** → T11 (transform + fixtures), T12 (parity + negative
  control), T13 (`docs/skill-kb-migration.md`). ✅
- **§3.5 Deliverables & acceptance** → all of the above + T14 (gated live) + T15 (docs). ✅
- **Guardrails:** no `core/` edit (injection via `ModelPatchEngine` preamble; `SkillRegistry` is a non-
  core Protocol); no schema change; embedder pinned bge-m3, gated; oracle-blind (T10); measured-arm
  (two runs + `accept`). ✅
- **Type consistency:** `SkillCtx(signals, repo, text)`, `build_ctx(signals, ticket, repo)`,
  `compile_predicate(spec)->Callable[[SkillCtx],bool]`, `MockSkillRegistry.load(path=SEED_PATH,*,embedder,top_k)`,
  `ModelPatchEngine(model, preamble="")` + `.with_preamble()`, `FixEvalRunner(..., skills=None)`,
  `compare_metrics(base_arm, head_arm)`, `accept(metrics_cmp, resolved_cmp, *, cost_budget=None)` — used
  identically across all tasks. ✅

## Risks (carried from spec §5)

- **Mock-KB representativeness** — the seed is small; the arm validates plumbing + **direction** of
  effect, not the migrated Skills' full lift. T7 is a hermetic plumbing proof (not a lift claim); T14 is
  directional-only. Flagged in T13's guide + T15's docs, never hidden.
- **Over-firing** — do NOT broaden the ops null-controls (cbm/produce) to force selection; that would
  raise `fabrication_rate` on Bucket-1 negatives and be caught (and rejected) by `accept`.
- **Prompt growth / cost** — cap `top_k` (default 3) and keep guidance terse; `accept` surfaces
  Δcost_per_solved (opt-in `cost_budget` gate).
