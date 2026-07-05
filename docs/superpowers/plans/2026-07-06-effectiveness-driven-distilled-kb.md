# Effectiveness-Driven Distilled Dev-Experience KB — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the [effectiveness-driven distilled-KB design](../specs/2026-07-06-effectiveness-driven-distilled-kb-design.md) into working software: first prove whether the dev-experience KB actually helps grounded fixing (Phase A), then — only if it does — automate its growth (Phase B) and distillation (Phase C).

**Architecture:** A *retain loop* over the shipped SP2 fix-eval + SP3 KB arm. Phase A wires OUR 11-Skill feedstock corpus (`groundloop/kb/`) into `gloop fixeval` as a measured `{none, placebo, kb}` A/B with a strengthened two-sided `accept()` (positive lift AND no `fabrication_rate` regression AND Φ_c non-negative AND a Wilson-95 lower bound > 0). Phases B/C add the provenance sidecar, the tiered lifecycle (staleness → auto-demote), a split-firewalled harvester, and an oracle-blind, re-validated distiller.

**Tech Stack:** Python 3.12 (`.venv`, uv-managed), pytest, ruff (line length 110); the shipped `groundloop/{fixeval,skills,adapters/skills,kb}` packages; the LiteLLM gateway (`deepseek-chat`, `bge-m3`) for the gated live A/B run.

**Coordination:** Tasks A1 and A5 edit now-merged SP3 code (`cli/__init__.py`, `fixeval/runner.py`, `fixeval/localize.py`). Keep those edits **additive** — default behaviour must stay byte-identical (`--skills none`, `skill_query=""`) — and reconcile with the SP3 owner. **Untouched:** `groundloop/core/`, `rank_repos`, `groundloop/mine/`, `owner_tokens.py`.

**Phasing gates (build the measurement, defer the automation):**
- **Phase A** — execute now.
- **Phase B** — execute **only if** Phase A's `strengthened_accept()` returns `accepted=True` on the held-out split (a lift worth protecting).
- **Phase C** — execute **only if** Phase B yields a `validated`/`canonical`-worthy Skill worth distilling.
- **Task A5 (localize-inject)** is itself GATED — do it only once the fix-stage A/B shows the KB helps and you want `file_recall` to become a live positive signal.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `groundloop/cli/__init__.py` (modify) | `--skills {none,mock,kb,placebo}` + `--skills-seed`; `_load_skills` helper | A1 |
| `groundloop/kb/placebo.py` + `data/placebo.toml` | length-matched irrelevant control corpus | A2 |
| `groundloop/kb/ab.py` | run the `{none,kb,placebo}` A/B → per-arm scorecards | A3 |
| `groundloop/kb/accept.py` | strengthened two-sided accept (Φ_c sweep + Wilson lower bound) | A4 |
| `groundloop/fixeval/{localize,runner}.py` (modify) | localize-inject — GATED net-new extension | A5 |
| `groundloop/kb/provenance.py` + `data/provenance.json` | per-entry provenance sidecar | B1 |
| `groundloop/kb/lifecycle.py` | tiers + promote/demote + hysteresis | B2 |
| `groundloop/kb/harvest/{__init__,cluster}.py` | split-firewalled candidate harvest (offline) | B3 |
| `groundloop/kb/distill/{__init__,extract}.py` | oracle-blind extraction distiller + leak-scrub | C1 |
| `groundloop/kb/distill/lofo.py` | leave-one-fragment-out attribution | C2 |
| `groundloop/kb/distill/revalidate.py` | the distilled form must re-earn the lift | C3 |

---

## Phase A — Prove the loop (measurement) — execute now

### Task A1: Load OUR corpus in gloop fixeval (--skills kb|placebo + --skills-seed)
**Files:**
- Modify: `groundloop/cli/__init__.py` (add `_load_skills` helper before `_run_fixeval` at :217; rewire handler :242-256; subparser :406-407)
- Test: `tests/fixeval/test_cli_skills.py` (append two unit tests on `_load_skills`)

- [ ] **Step 1: Write the failing test**
Append to `tests/fixeval/test_cli_skills.py`:
```python
def test_load_skills_selects_seed_corpus(tmp_path):
    # --skills-seed override: kb/placebo arms load OUR tiny fixture corpus (N skills of that file)
    from groundloop.cli import _load_skills
    corpus = tmp_path / "tiny.toml"
    corpus.write_text(
        '[[skill]]\n'
        'id = "s1"\n'
        'guidance = "Signature: NPE. Localize: FooActivity. Fix: null-guard."\n'
        'signals = ["npe"]\n'
        '[skill.match]\n'
        'any_errors = ["nullpointerexception"]\n\n'
        '[[skill]]\n'
        'id = "s2"\n'
        'guidance = "Signature: SIGSEGV. Localize: native peer. Fix: weak_ptr lock."\n'
        'signals = ["sigsegv"]\n'
        '[skill.match]\n'
        'any_errors = ["sigsegv"]\n'
    )
    reg = _load_skills("kb", str(corpus), None)
    assert reg is not None and {s.id for s in reg.skills} == {"s1", "s2"}
    # placebo arm honors the SAME --skills-seed override
    assert {s.id for s in _load_skills("placebo", str(corpus), None).skills} == {"s1", "s2"}
    # none -> baseline: no KB injected
    assert _load_skills("none", None, None) is None


def test_load_skills_kb_default_is_our_corpus():
    # kind=kb with no seed -> OUR 11-skill corpus (groundloop/kb/data/aaos_kb_seed.toml)
    from groundloop.cli import _load_skills
    from groundloop.kb.validate import SEED_PATH as KB_SEED
    reg = _load_skills("kb", None, None)
    assert reg is not None and len(reg.skills) == 11
    # mock with no seed -> the SP3 4-playbook default seed
    assert len(_load_skills("mock", None, None).skills) == 4
    assert KB_SEED.endswith("aaos_kb_seed.toml")
```

- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/fixeval/test_cli_skills.py::test_load_skills_selects_seed_corpus -q`
Expected: FAIL (`ImportError: cannot import name '_load_skills' from 'groundloop.cli'` — helper does not exist yet)

- [ ] **Step 3: Implement**
In `groundloop/cli/__init__.py`, insert the module-level helper immediately before `def _run_fixeval(args) -> int:` (currently :217):
```python
def _load_skills(kind: str, seed: str | None, embedder):
    """Compose the fixeval KB arm. kind: none|mock|kb|placebo.
    none -> None (baseline, no KB injected). mock -> the SP3 4-playbook seed.
    kb -> OUR 11-skill corpus (groundloop/kb/data/aaos_kb_seed.toml) or the --skills-seed override.
    placebo -> the length-matched irrelevant control (groundloop/kb/data/placebo.toml) or the override.
    All three real arms share the MockSkillRegistry wiring (predicate select + gated bge-m3 rerank)."""
    if kind == "none":
        return None
    from pathlib import Path

    from groundloop.adapters.skills.mock import SEED_PATH, MockSkillRegistry
    from groundloop.kb.validate import SEED_PATH as KB_SEED

    if kind == "mock":
        path = seed or SEED_PATH
    elif kind == "kb":
        path = seed or KB_SEED
    elif kind == "placebo":
        path = seed or str(Path(KB_SEED).parent / "placebo.toml")
    else:
        raise ValueError(f"unknown --skills kind: {kind!r}")
    return MockSkillRegistry.load(path, embedder=embedder)
```
Then replace the handler block at :242-256:
```python
    cases = load_cases(args.dataset)
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
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills)
```
with:
```python
    cases = load_cases(args.dataset)
    embedder = None
    if args.skills != "none" and os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
    skills = _load_skills(args.skills, args.skills_seed, embedder)
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills)
```
Then update the `fx` subparser `--skills` argument at :406-407:
```python
    fx.add_argument("--skills", choices=["none", "mock"], default="none",
                    help="dev-experience KB arm: none (baseline) | mock (real-data seed)")
```
to:
```python
    fx.add_argument("--skills", choices=["none", "mock", "kb", "placebo"], default="none",
                    help="dev-experience KB arm: none (baseline) | mock (SP3 seed) | "
                         "kb (our corpus) | placebo (length-matched irrelevant control)")
    fx.add_argument("--skills-seed", dest="skills_seed", default=None,
                    help="override the KB/placebo corpus TOML path (default: the packaged seed)")
```

- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/fixeval/test_cli_skills.py -q`

- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/cli/__init__.py tests/fixeval/test_cli_skills.py && git commit -m "feat(cli): fixeval --skills kb|placebo + --skills-seed via _load_skills

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task A2: Placebo control-corpus generator
**Files:**
- Create: `groundloop/kb/placebo.py`
- Create (generated, committed): `groundloop/kb/data/placebo.toml`
- Test: `tests/kb/test_placebo.py`

- [ ] **Step 1: Write the failing test**
```python
"""Hermetic tests for the placebo control-corpus generator (Task A2)."""
from __future__ import annotations

from groundloop.kb.placebo import KB_SEED, build_placebo
from groundloop.kb.validate import load_corpus, validate_corpus


def test_build_placebo_mirrors_matches_and_validates(tmp_path):
    out = str(tmp_path / "placebo.toml")
    n = build_placebo(kb_path=KB_SEED, out_path=out)

    kb = load_corpus(KB_SEED)
    placebo = load_corpus(out)

    # returned count agrees, and there is exactly one placebo per KB skill
    assert n == len(kb)
    assert len(placebo) == len(kb)

    # the generated corpus is conforming + leak-safe (validate returns [] == clean)
    assert validate_corpus(out) == []

    kb_by_id = {sk["id"]: sk for sk in kb}
    assert {p["id"] for p in placebo} == {"placebo-" + i for i in kb_by_id}

    for psk in placebo:
        assert psk["id"].startswith("placebo-")
        origin = psk["id"][len("placebo-"):]
        ksk = kb_by_id[origin]
        # fires identically: the match predicate is copied verbatim (round-trips exactly)
        assert psk["match"] == ksk["match"]
        # but the guidance is different (length-matched irrelevant filler)
        assert psk["guidance"] != ksk["guidance"]
        # still structured with the three required clauses (so it validates + injects at both stages)
        for clause in ("Signature:", "Localize:", "Fix:"):
            assert clause in psk["guidance"]
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_placebo.py::test_build_placebo_mirrors_matches_and_validates -q`
Expected: FAIL (`ModuleNotFoundError: groundloop.kb.placebo` — module + `build_placebo`/`KB_SEED` do not exist yet)
- [ ] **Step 3: Implement**
```python
"""Placebo control-corpus generator (Task A2) for the dev-experience KB A/B.

`build_placebo` emits `groundloop/kb/data/placebo.toml`: one placebo skill per real KB skill in
`aaos_kb_seed.toml`. Each placebo copies the KB skill's `[skill.match]` VERBATIM (so it fires on
exactly the same cases) under `id = "placebo-" + <kb id>`, but replaces the guidance with
length-matched, deliberately IRRELEVANT filler that still carries the required
`Signature:`/`Localize:`/`Fix:` clauses (so it validates and is injected at both the localize and
fix stages).

It is the NULL arm of the KB A/B: any lift the real KB shows over this control isolates the guidance
CONTENT as the treatment, ruling out the confound of merely injecting *some* skill on those cases.
The output conforms to `groundloop/kb/validate.py` (closed-vocab predicate + owner-token leak red-test).
"""
from __future__ import annotations

from pathlib import Path

from groundloop.kb.validate import load_corpus

KB_SEED = str(Path(__file__).parent / "data" / "aaos_kb_seed.toml")
PLACEBO_SEED = str(Path(__file__).parent / "data" / "placebo.toml")

_HEADER = (
    "# Placebo control corpus — GENERATED by groundloop/kb/placebo.py; DO NOT EDIT BY HAND.\n"
    "# Each [[skill]] copies a groundloop/kb/data/aaos_kb_seed.toml skill's [skill.match] VERBATIM\n"
    "#   (id prefixed 'placebo-') so it fires on the identical cases, but its guidance is\n"
    "#   length-matched, deliberately IRRELEVANT filler. This is the null arm for the KB A/B: any\n"
    "#   lift the KB shows over it is attributable to guidance CONTENT, not to the mere act of\n"
    "#   injecting a skill on those cases. Conforms to groundloop/kb/validate.py.\n"
)

# Neutral, owner-token-free filler (verified leak-safe against FLEET_OWNER_TOKENS via validate_corpus).
_FILLER = (
    "This clause is placebo control text of matched length that conveys no diagnostic or "
    "corrective information and points at nothing in particular; it exists only so the treatment "
    "and control arms differ solely in the wording of the injected guidance, never in which cases "
    "the skill fires. "
)
_LABELS = ("Signature:", "Localize:", "Fix:")


def _toml_str(s: str) -> str:
    """Emit a TOML string. Prefer a literal (single-quoted) string so regex backslashes survive
    verbatim; fall back to an escaped basic string when the value contains a quote or a newline."""
    if "'" not in s and "\n" not in s:
        return "'" + s + "'"
    esc = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + esc + '"'


def _toml_array(vals) -> str:
    return "[" + ", ".join(_toml_str(str(v)) for v in vals) + "]"


def _placebo_guidance(reference: str) -> str:
    """Length-matched filler carrying the three required clauses; content is irrelevant."""
    target = max(len(reference), 120)
    overhead = sum(len(lab) + 2 for lab in _LABELS)
    per = max((target - overhead) // len(_LABELS), 40)

    def fill(n: int) -> str:
        reps = (n // len(_FILLER)) + 1
        return (_FILLER * reps)[:n].rstrip()

    return "\n".join(f"{lab} {fill(per)}" for lab in _LABELS)


def _render_skill(sid: str, provenance: str, guidance: str, match: dict) -> str:
    lines = [
        "[[skill]]",
        f"id = {_toml_str(sid)}",
        f"provenance = {_toml_str(provenance)}",
        "guidance = '''",
        guidance.strip("\n"),
        "'''",
        "",
        "[skill.match]",
    ]
    for key, vals in match.items():
        lines.append(f"{key} = {_toml_array(vals)}")
    return "\n".join(lines) + "\n"


def build_placebo(kb_path: str = KB_SEED, out_path: str = PLACEBO_SEED) -> int:
    """Generate the placebo corpus from `kb_path`, write it to `out_path`, return the skill count."""
    skills = load_corpus(kb_path)
    blocks = [_HEADER]
    for sk in skills:
        sid = sk["id"]
        provenance = (
            f"Placebo control paired to KB skill {sid}: length-matched, deliberately irrelevant "
            "guidance behind a verbatim-copied match predicate — fires on the identical cases while "
            "conveying no diagnostic content, isolating the KB guidance as the A/B treatment."
        )
        blocks.append(
            _render_skill("placebo-" + sid, provenance, _placebo_guidance(sk.get("guidance", "")),
                          sk.get("match", {}) or {})
        )
    Path(out_path).write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    return len(skills)


if __name__ == "__main__":  # pragma: no cover
    print(build_placebo())
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_placebo.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/python -c "from groundloop.kb.placebo import build_placebo; print(build_placebo())"
.venv/bin/ruff check groundloop tests
git add groundloop/kb/placebo.py groundloop/kb/data/placebo.toml tests/kb/test_placebo.py && git commit -m "feat(kb): placebo control-corpus generator for the KB A/B null arm

build_placebo copies each aaos_kb_seed.toml skill's [skill.match] verbatim
(id='placebo-'+id) so it fires on identical cases, but swaps in length-matched
irrelevant filler guidance (Signature:/Localize:/Fix: clauses intact). Output
groundloop/kb/data/placebo.toml passes validate_corpus (conforming + leak-safe).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task A3: A/B runner over {none, kb, placebo} arms

**Files:**
- Create: `/mnt/x/code/GroundLoop/groundloop/kb/ab.py`
- Test: `/mnt/x/code/GroundLoop/tests/kb/test_ab.py`

Coordination: A3 depends on Task A2's `groundloop/kb/placebo.py` (`KB_SEED`, `PLACEBO_SEED` constants) and the generated `groundloop/kb/data/placebo.toml`; it reads SP3's `MockSkillRegistry` but edits no SP3-owned code.

- [ ] **Step 1: Write the failing test**
```python
"""Hermetic A/B: run_ab returns the 3 KB arms {none, kb, placebo} and the kb arm RESOLVES the native
positive (GP-352) that the none arm abstains on — proving the KB injection flows through the per-arm
orchestration (FixEvalRunner + grade_fix_all reused once per arm). A scripted CannedModel emits the GOLD
diff ONLY when a '# Applicable playbooks' preamble is present (mirrors tests/fixeval/test_skill_effect.py).
NOT a real-lift claim (that is the Type-2 gated measurement)."""
import json
import shutil
from pathlib import Path

from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.mock.model import CannedModel
from groundloop.kb import ab
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [{"name": n} for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
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


def test_run_ab_three_arms_kb_beats_none(tmp_path, monkeypatch):
    # scripted fix-stage model: GOLD only when the KB preamble fired, "" (abstain) otherwise.
    def _fx():
        return ModelPatchEngine(CannedModel({"# Applicable playbooks": GOLD, "default": ""}))
    monkeypatch.setattr(ab, "_make_fixer", _fx)

    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(CATALOG))
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))

    cards = ab.run_ab(dataset=str(ds), repos=str(FIX / "repos"), index_db=db,
                      catalog_path=str(catalog_path), out_dir=str(tmp_path / "out"))

    assert set(cards) == {"none", "kb", "placebo"}
    for arm in ("none", "kb", "placebo"):
        assert (tmp_path / "out" / f"scorecard-{arm}.json").is_file()
    none_rr = cards["none"]["arms"]["membership+logs"]["resolved_rate"]["value"]
    kb_rr = cards["kb"]["arms"]["membership+logs"]["resolved_rate"]["value"]
    assert none_rr == 0.0        # no preamble -> "" -> patch_unappliable abstain -> unresolved
    assert kb_rr == 1.0          # KB skill fires -> preamble -> GOLD -> applies -> resolved
    assert kb_rr > none_rr       # the direction-of-effect the A/B measures
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_ab.py::test_run_ab_three_arms_kb_beats_none -q`
Expected: FAIL (`groundloop/kb/ab.py` does not exist yet — `ImportError: cannot import name 'ab' from 'groundloop.kb'`)

- [ ] **Step 3: Implement**
```python
"""A/B fix-eval orchestration over dev-experience-KB arms {none, kb, placebo}. Each arm reruns the SAME
whole-loop fix-eval (FixEvalRunner + grade_fix_all) with a different skills registry injected at the FIX
stage: none = skills off (byte-identical to pre-SP3), kb = OUR 11-skill corpus (groundloop/kb/data/
aaos_kb_seed.toml), placebo = the length-matched IRRELEVANT control that fires on the SAME cases. Writes
one scorecard-<arm>.json per arm under out_dir and returns {arm: card}. Oracle-blind loop; grade_fix_all
is the sole oracle read. _make_fixer mirrors the CLI fixeval handler and is monkeypatched by hermetic
tests to inject a scripted CannedModel."""
from __future__ import annotations

import json
import os
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.fixeval.scorecard import grade_fix_all
from groundloop.kb.placebo import KB_SEED, PLACEBO_SEED


def _make_fixer():
    """The fix-stage FixEngine, wired exactly like the CLI fixeval handler: a live GatewayModel when
    KLOOP_PRODUCE_API_KEY is set, else a hermetic CannedModel (every case abstains at fix). Tests
    monkeypatch this symbol to inject a scripted CannedModel."""
    if os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
        from groundloop.adapters.model.gateway import GatewayModel
        from groundloop.config.settings import Settings
        s = Settings.load()
        model = GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
    else:
        model = CannedModel({"default": ""})
    return ModelPatchEngine(model)


def _registry_for(arm: str, embedder):
    """Map an A/B arm name to its skills registry (None = the true no-op `none` arm)."""
    if arm == "none":
        return None
    if arm == "kb":
        return MockSkillRegistry.load(path=KB_SEED, embedder=embedder)
    if arm == "placebo":
        return MockSkillRegistry.load(path=PLACEBO_SEED, embedder=embedder)
    raise ValueError(f"unknown A/B arm: {arm!r} (expected one of none|kb|placebo)")


def run_ab(*, dataset, repos, index_db, catalog_path, out_dir,
           arms=("none", "kb", "placebo"), embedder=None) -> dict[str, dict]:
    catalog = [RepoRef(r["name"]) for r in json.loads(Path(catalog_path).read_text())]
    cases = load_cases(dataset)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — sole oracle read
    eval_arms = build_arms(membership_index=AtlasIndex(index_db))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cards: dict[str, dict] = {}
    for arm in arms:
        skills = _registry_for(arm, embedder)
        runner = FixEvalRunner(issues=MockJira(dataset),
                               estate=GitFixtureEstate(repos, str(out / f"_work-{arm}")),
                               catalog=catalog, tau_margin=0.0, tau_score=0.0, skills=skills)
        records = runner.run(cases, eval_arms, fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        (out / f"scorecard-{arm}.json").write_text(json.dumps(card, indent=2))
        cards[arm] = card
    return cards
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_ab.py -q`

- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/ab.py tests/kb/test_ab.py && git commit -m "feat(kb): A/B fix-eval runner over {none,kb,placebo} arms

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task A4: Strengthened two-sided accept (Φ_c sweep + Wilson lower bound)
**Files:**
- Create: `groundloop/kb/accept.py`
- Test: `tests/kb/test_accept.py`

- [ ] **Step 1: Write the failing test**
```python
"""A4 — strengthened_accept: the SP3 two-sided accept() plus a Φ_c-sweep monotonicity gate and a
Wilson-95 lower-bound guard on the newly-solved evidence. Two synthetic fix-scorecard arm dicts per
case; no oracle, no network."""
from groundloop.kb.accept import strengthened_accept


def _arm(*, resolved_by_case, fabrication, phi, file_recall1=0.5, cost_per_solved=1.0):
    """A minimal fix-scorecard arm: exactly the keys compare/compare_metrics/accept read."""
    return {
        "file_recall@1": {"value": file_recall1},
        "fabrication_rate": {"value": fabrication},
        "cost_per_solved": cost_per_solved,
        "cost_total": cost_per_solved,
        "phi_c": {"0.5": phi, "1.0": phi, "2.0": phi},
        "resolved_by_case": resolved_by_case,
    }


def test_honesty_regression_rejected():
    # head solves both cases (strong positive lift) but raises fabrication -> honesty fails -> reject
    base = _arm(resolved_by_case={"c1": False, "c2": False}, fabrication=0.0, phi=0.10,
                file_recall1=0.50)
    head = _arm(resolved_by_case={"c1": True, "c2": True}, fabrication=0.20, phi=0.10,
                file_recall1=0.60)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["honesty_ok"] is False
    assert v["accepted"] is False
    assert any("fabrication" in r for r in v["reasons"])
    assert set(v) == {"accepted", "pos_ok", "honesty_ok", "phi_ok", "wilson_lo", "cost_ok", "reasons"}


def test_clean_lift_accepted():
    # head solves 3 (Wilson-95 lo>0), holds honesty, and never regresses phi at any c -> accept
    base = _arm(resolved_by_case={"c1": False, "c2": False, "c3": False}, fabrication=0.10,
                phi=0.10, file_recall1=0.40)
    head = _arm(resolved_by_case={"c1": True, "c2": True, "c3": True}, fabrication=0.05,
                phi=0.25, file_recall1=0.70)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["honesty_ok"] is True
    assert v["phi_ok"] is True
    assert v["wilson_lo"] > 0
    assert v["cost_ok"] is True
    assert v["accepted"] is True
    assert v["reasons"] == []


def test_phi_regression_blocks_accept():
    # solves 3, honesty held, but Φ_c drops at every c -> phi_ok False -> reject (the NEW gate)
    base = _arm(resolved_by_case={"c1": False, "c2": False, "c3": False}, fabrication=0.10,
                phi=0.30, file_recall1=0.40)
    head = _arm(resolved_by_case={"c1": True, "c2": True, "c3": True}, fabrication=0.05,
                phi=0.10, file_recall1=0.70)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["honesty_ok"] is True
    assert v["phi_ok"] is False
    assert v["accepted"] is False
    assert any("phi_c" in r for r in v["reasons"])


def test_thin_evidence_blocks_accept():
    # file_recall@1 lifts (pos_ok) but NO case is newly solved (None never counts) -> Wilson lo==0
    base = _arm(resolved_by_case={"c1": False, "c2": None}, fabrication=0.10, phi=0.10,
                file_recall1=0.40)
    head = _arm(resolved_by_case={"c1": False, "c2": None}, fabrication=0.10, phi=0.10,
                file_recall1=0.70)
    v = strengthened_accept(base, head)
    assert v["pos_ok"] is True
    assert v["wilson_lo"] == 0.0
    assert v["accepted"] is False
    assert any("Wilson" in r for r in v["reasons"])
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_accept.py -q`
Expected: FAIL (`ModuleNotFoundError: groundloop.kb.accept` — module does not exist yet)
- [ ] **Step 3: Implement**
```python
"""A4 — strengthened two-sided accept for the KB A/B verdict. Wraps SP3's
fixeval.compare.{compare,compare_metrics,accept} and ADDS two gates the base verdict lacks:
  * phi_ok  — Δphi_c >= 0 at EVERY c in the sweep (a KB set may never regress effective
    reliability at any risk aversion, not just at c=1.0);
  * wilson_lo — the Wilson-95 lower bound of newly_solved/(newly_solved+newly_broken) must
    clear 0, so a "lift" backed by too few actually-resolved cases (or none) is rejected.
accepted = pos_ok and honesty_ok and phi_ok and (wilson_lo > 0) and cost_ok."""
from __future__ import annotations

from groundloop.eval.metrics import wilson
from groundloop.fixeval.compare import accept, compare, compare_metrics


def strengthened_accept(base_arm: dict, head_arm: dict, *, c_values=(0.5, 1.0, 2.0),
                        cost_budget: float | None = None) -> dict:
    resolved_cmp = compare(base_arm.get("resolved_by_case", {}),
                           head_arm.get("resolved_by_case", {}))
    metrics_cmp = compare_metrics(base_arm, head_arm)
    base = accept(metrics_cmp, resolved_cmp, cost_budget=cost_budget)
    pos_ok = base["pos_ok"]
    honesty_ok = base["honesty_ok"]
    cost_ok = base["cost_ok"]
    ns, nb = base["newly_solved"], base["newly_broken"]

    base_phi, head_phi = base_arm.get("phi_c", {}), head_arm.get("phi_c", {})
    phi_deltas = {str(c): head_phi.get(str(c), 0.0) - base_phi.get(str(c), 0.0) for c in c_values}
    phi_ok = all(d >= 0 for d in phi_deltas.values())

    wilson_lo, _ = wilson(ns, ns + nb)

    reasons = list(base["reasons"])
    if not phi_ok:
        regressed = [c for c, d in phi_deltas.items() if d < 0]
        reasons.append(f"phi_c regressed at c={regressed}")
    if wilson_lo <= 0:
        reasons.append(f"newly-solved evidence too thin (Wilson-95 lo={wilson_lo:.3f} "
                       f"at {ns}/{ns + nb})")

    accepted = pos_ok and honesty_ok and phi_ok and (wilson_lo > 0) and cost_ok
    return {"accepted": accepted, "pos_ok": pos_ok, "honesty_ok": honesty_ok, "phi_ok": phi_ok,
            "wilson_lo": wilson_lo, "cost_ok": cost_ok, "reasons": reasons}
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_accept.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/accept.py tests/kb/test_accept.py && git commit -m "feat(kb): strengthened two-sided accept — Phi_c sweep + Wilson-95 lower bound (A4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task A5: Localize-inject — a Skill can bias file_recall via `skill_query` (GATED)
**Files:**
- Modify: `groundloop/fixeval/localize.py:8-21` (add `skill_query` param; default `""` keeps the query byte-identical)
- Modify: `groundloop/fixeval/runner.py:16-17` (new `_skill_query` helper) and `groundloop/fixeval/runner.py:73-80` (build `skill_query` from the already-selected skills, pass to `localize`)
- Test: `tests/fixeval/test_localize_inject.py` (create)

**Coordination:** edits SP3-owned `runner.py` + `localize.py`. Additive only: the new `skill_query` param defaults to `""` and the runner passes `""` whenever `self.skills is None` or nothing was selected, so the `skills=none` path stays byte-identical to pre-A5. GATED — land only after Phase A shows the KB arm's lift is worth the localize coupling.

- [ ] **Step 1: Write the failing test**
```python
"""GATED (A5): a Skill can bias localization via skill_query. Hermetic — a two-unit atlas where the
gold JNI-loader file is retrievable ONLY by a skill token ('registernatives'), never by the arm's
signal tokens. Proves skill_query surfaces a file plain localize misses (a file_recall bias lever)
and that skill_query='' stays byte-identical to the pre-A5 query."""
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals
from groundloop.engines.atlas.store import Store, Unit
from groundloop.fixeval.localize import localize
from groundloop.fixeval.runner import _skill_query
from groundloop.skills.base import Skill

_SIGNAL_FILE = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"
_SKILL_FILE = "library/src/main/jni/loader/registerNatives.cpp"


def _build(db_path: str) -> str:
    s = Store(db_path)
    units = [
        Unit(repo="android-gpuimage-plus", kind="symbol", name="CGEImageHandler",
             qualified_name="org.wysaid.CGEImageHandler", file=_SIGNAL_FILE, repo_head="fixsha",
             text="CGEImageHandler nativeCreateHandler", meta={}),
        Unit(repo="android-gpuimage-plus", kind="symbol", name="registerNatives",
             qualified_name="org.wysaid.registerNatives", file=_SKILL_FILE, repo_head="fixsha",
             text="registernatives unsatisfiedlinkerror jni loader", meta={}),
    ]
    s.reindex_repo("android-gpuimage-plus", list(zip(units, [[0.0]] * len(units))),
                   repo_head="fixsha")
    return db_path


def _sig() -> Signals:
    return Signals(classes=("CGEImageHandler",), methods=("nativeCreateHandler",))


def test_default_skill_query_is_byte_identical(tmp_path):
    db = _build(str(tmp_path / "atlas.db"))
    idx = AtlasIndex(db)
    assert localize(idx, "android-gpuimage-plus", _sig(), summary="crash", k=5) == \
        localize(idx, "android-gpuimage-plus", _sig(), summary="crash", k=5, skill_query="")


def test_plain_localize_misses_the_skill_only_file(tmp_path):
    db = _build(str(tmp_path / "atlas.db"))
    plain = localize(AtlasIndex(db), "android-gpuimage-plus", _sig(), summary="crash", k=5)
    assert _SIGNAL_FILE in plain and _SKILL_FILE not in plain


def test_skill_query_biases_file_recall(tmp_path):
    db = _build(str(tmp_path / "atlas.db"))
    boosted = localize(AtlasIndex(db), "android-gpuimage-plus", _sig(), summary="crash",
                       k=5, skill_query="registernatives")
    assert _SKILL_FILE in boosted   # the skill token surfaced a file plain localize missed


def test_skill_query_built_from_signals_and_localize_line():
    s = Skill(id="jni-loader", applies_to=lambda c: True,
              guidance="Signature: UnsatisfiedLinkError\nLocalize: registernatives jniLibs\nFix: register",
              signals=("native", "so"))
    q = _skill_query([s])
    assert "native" in q and "so" in q
    assert "registernatives" in q and "jniLibs" in q
    assert "Signature:" not in q and "Fix:" not in q


def test_skill_query_empty_when_no_skills():
    assert _skill_query([]) == ""
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/fixeval/test_localize_inject.py -q`
Expected: FAIL (collection ImportError: `cannot import name '_skill_query' from groundloop.fixeval.runner`; and `localize()` has no `skill_query` keyword yet)

- [ ] **Step 3: Implement**
Rewrite `groundloop/fixeval/localize.py` (function body, lines 8-21):
```python
def localize(index, repo: str, signals, summary: str = "", *, k: int = 5,
             skill_query: str = "") -> list[str]:
    """Query = signals.tokens() (fallback: summary), optionally biased by a Skill's skill_query (its
    .signals + the 'Localize:' hint). index.retrieve(RepoRef(repo), query) -> dedup top-k repo-relative
    paths. Empty result => localize-abstain. skill_query='' is BYTE-IDENTICAL to the pre-A5 query."""
    query = " ".join(signals.tokens()) if signals.tokens() else summary
    if skill_query.strip():
        query = (query + " " + skill_query).strip()
    if not query.strip():
        return []
    out: list[str] = []
    for hit in index.retrieve(RepoRef(repo), query):
        p = norm_path(hit)
        if p and p not in out:
            out.append(p)
        if len(out) >= k:
            break
    return out
```
In `groundloop/fixeval/runner.py`, add the module-level helper directly after the imports (after line 16, `from groundloop.skills.ctx import build_ctx`):
```python


def _skill_query(skills) -> str:
    """Build a localize-bias query from selected skills: their retrieval .signals plus the token(s) on
    any 'Localize:' line of their guidance. Empty -> localize() stays byte-identical to skills=none."""
    parts: list[str] = []
    for s in skills:
        parts.extend(s.signals)
        for line in s.guidance.splitlines():
            t = line.strip()
            if t.lower().startswith("localize:"):
                parts.append(t.split(":", 1)[1].strip())
    return " ".join(p for p in parts if p).strip()
```
Then replace the skill-injection + localize block in `FixEvalRunner._one` (lines 73-80). Old:
```python
        f = fixer
        if self.skills is not None:
            preamble = render_skills(self.skills.select(build_ctx(signals, ticket, predicted)))
            if preamble:
                f = fixer.with_preamble(preamble)
        c0 = self._cost(fixer)
        wt = self.estate.materialize(RepoRef(predicted))
        locations = localize(arm.index, predicted, signals, ticket.summary)
```
New (select ONCE, reuse for both the preamble and the localize bias):
```python
        f = fixer
        skill_query = ""
        if self.skills is not None:
            selected = self.skills.select(build_ctx(signals, ticket, predicted))
            preamble = render_skills(selected)
            if preamble:
                f = fixer.with_preamble(preamble)
            skill_query = _skill_query(selected)
        c0 = self._cost(fixer)
        wt = self.estate.materialize(RepoRef(predicted))
        locations = localize(arm.index, predicted, signals, ticket.summary, skill_query=skill_query)
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/fixeval/test_localize_inject.py tests/fixeval/test_localize.py tests/fixeval/test_skill_effect.py tests/fixeval/test_runner.py -q`

- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/fixeval/localize.py groundloop/fixeval/runner.py tests/fixeval/test_localize_inject.py && git commit -m "feat(fixeval): A5 skill-biased localize (skill_query) — GATED

localize() gains skill_query (default '' byte-identical); runner builds it from
selected skills' .signals + their 'Localize:' guidance line so a Skill can surface
a file plain signal-token retrieval misses (a file_recall bias lever).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```


---

## Phase B — Automate growth — GATED on Phase A `accepted=True`

### Task B1: Provenance sidecar (ProvenanceRecord + load/save)
**Files:**
- Create: `/mnt/x/code/GroundLoop/groundloop/kb/provenance.py`
- Test: `/mnt/x/code/GroundLoop/tests/kb/test_provenance.py`

**Gating:** Phase B (lifecycle/provenance/harvest/distill, Tasks B1–C3) is **GATED on a positive Phase-A `accept()`** — the KB arm must first clear the two-sided A/B (`strengthened_accept` in Task A4 returns `accepted=True`, i.e. `pos_ok and honesty_ok and phi_ok and wilson_lo>0 and cost_ok`) over the placebo control before we invest in tiering the corpus. This task ships the frozen record + JSON sidecar I/O only (no lifecycle transitions — that is Task B2). This gate is stated in the module docstring so it is discoverable at the code.

- [ ] **Step 1: Write the failing test**
```python
"""Round-trip + defaulting contract for the KB provenance sidecar (Phase B, GATED on Phase-A accept)."""
import json
from pathlib import Path

from groundloop.kb.provenance import (
    SIDECAR_PATH,
    ProvenanceRecord,
    load_sidecar,
    save_sidecar,
)


def _full_record() -> ProvenanceRecord:
    return ProvenanceRecord(
        id="native-null-deref-segv",
        tier="validated",
        lineage="cold-start-author",
        validating_case_ids=("case-001", "case-017"),
        measured_lift={"phi_1.0": 0.31, "resolved_delta": 0.12, "proxy": True},
        evidence_context={"atlas_sha": "abc123", "embed": "bge-m3", "date": "2026-07-06"},
        fail_count=2,
        demotions=("2026-07-06:validated->applied",),
        leak_check="clean",
    )


def test_save_then_load_round_trips_all_fields(tmp_path):
    rec = _full_record()
    p = tmp_path / "provenance.json"
    save_sidecar(str(p), {rec.id: rec})
    back = load_sidecar(str(p))
    assert back == {rec.id: rec}
    # tuple fields must survive JSON (list) -> tuple reconstruction, else equality would fail
    assert isinstance(back[rec.id].validating_case_ids, tuple)
    assert isinstance(back[rec.id].demotions, tuple)


def test_missing_optional_fields_default_and_unknown_ignored(tmp_path):
    p = tmp_path / "prov.json"
    p.write_text(
        json.dumps(
            {
                "skill-x": {
                    "id": "skill-x",
                    "tier": "candidate",
                    "lineage": "harvest",
                    "validating_case_ids": ["c1"],
                    "measured_lift": {},
                    "evidence_context": {},
                    "future_field": "should-be-ignored",  # unknown key -> dropped, not crash
                }
            }
        ),
        encoding="utf-8",
    )
    rec = load_sidecar(str(p))["skill-x"]
    assert rec.fail_count == 0
    assert rec.demotions == ()
    assert rec.leak_check == ""
    assert not hasattr(rec, "future_field")


def test_missing_file_returns_empty(tmp_path):
    assert load_sidecar(str(tmp_path / "does-not-exist.json")) == {}


def test_record_is_frozen():
    rec = _full_record()
    try:
        rec.tier = "canonical"  # type: ignore[misc]
    except Exception as e:  # FrozenInstanceError is an AttributeError subclass
        assert e.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("ProvenanceRecord must be frozen")


def test_default_sidecar_path_points_at_kb_data():
    p = Path(SIDECAR_PATH)
    assert p.name == "provenance.json"
    assert p.parent.name == "data"
    assert p.parent.parent.name == "kb"
```

- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_provenance.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'groundloop.kb.provenance'` — the module does not exist yet)

- [ ] **Step 3: Implement**
```python
"""Per-entry provenance sidecar for the KB lifecycle (tiering / auto-demotion).

Records the traceability every KB Skill needs to be auto-demotable: source `lineage`, the
split-tagged `validating_case_ids`, the (proxy) `measured_lift`, and the `evidence_context`
(atlas SHA + `bge-m3` + model pin + date) a lift was measured against. Stored OUT-OF-BAND from the
corpus TOML as JSON (`groundloop/kb/data/provenance.json`) so authoring the leak-safe *content*
stays separate from the mutable lifecycle *bookkeeping* — the TOML is human-authored + regression
checked (`groundloop/kb/validate.py`), this sidecar is machine-updated by the lifecycle.

GATING: Phase B (this sidecar + `lifecycle.py` + `harvest/` + `distill/`) is gated on a positive
Phase-A `accept()` (`groundloop/kb/accept.strengthened_accept(...) -> {"accepted": True, ...}`): the
KB arm must first show a two-sided A/B lift over the placebo control before we invest in tiering the
corpus that produced it. This module ships the frozen record + JSON I/O only; tier transitions live
in `groundloop/kb/lifecycle.py` (Task B2).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SIDECAR_PATH = str(Path(__file__).parent / "data" / "provenance.json")

# JSON has no tuple type — these fields serialize as lists and must be re-tupled on load so that
# frozen-dataclass equality (used by the round-trip test + by lifecycle diffing) holds.
_TUPLE_FIELDS = ("validating_case_ids", "demotions")


@dataclass(frozen=True)
class ProvenanceRecord:
    id: str
    tier: str
    lineage: str
    validating_case_ids: tuple[str, ...]
    measured_lift: dict
    evidence_context: dict
    fail_count: int = 0
    demotions: tuple[str, ...] = ()
    leak_check: str = ""


def _to_record(sid: str, raw: dict) -> ProvenanceRecord:
    """Build a record from a raw JSON row: drop unknown keys, default missing optionals, re-tuple."""
    known = {f.name for f in fields(ProvenanceRecord)}
    kw = {k: v for k, v in raw.items() if k in known}
    kw.setdefault("id", sid)  # id is the dict key; tolerate its absence in the body
    for tf in _TUPLE_FIELDS:
        if kw.get(tf) is not None and not isinstance(kw[tf], tuple):
            kw[tf] = tuple(kw[tf])
    return ProvenanceRecord(**kw)


def load_sidecar(path: str = SIDECAR_PATH) -> dict[str, ProvenanceRecord]:
    """Load the sidecar; a missing file is an empty sidecar (no records yet), not an error."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {sid: _to_record(sid, row) for sid, row in raw.items()}


def save_sidecar(path: str, records: dict[str, ProvenanceRecord]) -> None:
    """Write the sidecar as deterministic (sorted-key, indented) JSON, keyed by the passed keys."""
    out = {sid: asdict(rec) for sid, rec in records.items()}
    Path(path).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_provenance.py -q`

- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/provenance.py tests/kb/test_provenance.py && git commit -m "feat(kb): provenance sidecar — frozen ProvenanceRecord + JSON load/save (Phase B, GATED on Phase-A accept)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

The B1 file `groundloop/kb/provenance.py` does not exist yet (B1 is upstream in this same plan), so I pin B2 to the exact `ProvenanceRecord` signature from the skeleton. Existing kb conventions (test layout in `tests/kb/`, `from __future__ import annotations`, frozen dataclass) confirmed from `validate.py` and `test_feedstock.py`.

### Task B2: Lifecycle/tier manager (promote/demote + hysteresis)
**Files:**
- Create: `groundloop/kb/lifecycle.py`
- Test: `tests/kb/test_lifecycle.py`
- Read first: `groundloop/kb/provenance.py` (B1 — use its `ProvenanceRecord`; must land before this task)

- [ ] **Step 1: Write the failing test**
```python
"""Lifecycle tier manager: promote on pass, demote on hysteresis-many consecutive fails."""
import dataclasses

from groundloop.kb.lifecycle import TIERS, apply_verdict, next_tier, prev_tier
from groundloop.kb.provenance import ProvenanceRecord


def _rec(tier="candidate", fail_count=0, demotions=()):
    return ProvenanceRecord(
        id="skill-1",
        tier=tier,
        lineage="harvest:cluster-42",
        validating_case_ids=("c1", "c2"),
        measured_lift={"phi_1.0": 0.31},
        evidence_context={"n": 5},
        fail_count=fail_count,
        demotions=tuple(demotions),
        leak_check="clean",
    )


def test_tiers_order_and_neighbors():
    assert TIERS == ("candidate", "applied", "validated", "canonical")
    assert next_tier("candidate") == "applied"
    assert next_tier("canonical") == "canonical"  # clamps at top
    assert prev_tier("applied") == "candidate"
    assert prev_tier("candidate") == "candidate"  # clamps at bottom


def test_passing_verdict_promotes_and_resets_fail_count():
    rec = _rec(tier="candidate", fail_count=1)
    out = apply_verdict(rec, True)
    assert out.tier == "applied"
    assert out.fail_count == 0
    assert out.demotions == ()
    assert isinstance(out, ProvenanceRecord)
    # frozen: input untouched
    assert rec.tier == "candidate" and rec.fail_count == 1


def test_single_fail_does_not_demote_hysteresis():
    rec = _rec(tier="applied", fail_count=0)
    out = apply_verdict(rec, False)
    assert out.tier == "applied"  # NOT demoted on one fail
    assert out.fail_count == 1
    assert out.demotions == ()


def test_two_consecutive_fails_demote_record_and_reset():
    rec = _rec(tier="applied", fail_count=0)
    once = apply_verdict(rec, False)
    twice = apply_verdict(once, False)
    assert twice.tier == "candidate"  # demoted one tier
    assert twice.fail_count == 0  # reset after demotion
    assert twice.demotions == ("applied->candidate",)


def test_pass_after_one_fail_resets_streak_no_demote():
    rec = _rec(tier="applied", fail_count=1)
    out = apply_verdict(rec, True)
    assert out.tier == "validated"
    assert out.fail_count == 0
    assert out.demotions == ()


def test_custom_hysteresis_threshold():
    rec = _rec(tier="validated", fail_count=0)
    r1 = apply_verdict(rec, False, hysteresis=3)
    r2 = apply_verdict(r1, False, hysteresis=3)
    assert r2.tier == "validated" and r2.fail_count == 2  # still no demote at 2
    r3 = apply_verdict(r2, False, hysteresis=3)
    assert r3.tier == "applied" and r3.fail_count == 0
    assert r3.demotions == ("validated->applied",)


def test_apply_verdict_returns_new_instance():
    rec = _rec()
    assert apply_verdict(rec, True) is not rec
    assert dataclasses.is_dataclass(apply_verdict(rec, True))
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_lifecycle.py -q`
Expected: FAIL (`groundloop/kb/lifecycle.py` does not exist yet — `ImportError` on `TIERS`/`apply_verdict`/`next_tier`/`prev_tier`)
- [ ] **Step 3: Implement**
```python
"""Lifecycle tier manager for KB provenance records.

A Skill climbs the trust ladder one rung per passing verdict and slides down only after
`hysteresis` CONSECUTIVE failing verdicts (so a single noisy A/B run cannot demote a canonical
playbook). Records are frozen `ProvenanceRecord`s (B1); every transition returns a NEW record via
`dataclasses.replace` — the input is never mutated.
"""
from __future__ import annotations

import dataclasses

from groundloop.kb.provenance import ProvenanceRecord

# Trust ladder, lowest -> highest. Ordered; index arithmetic drives promote/demote.
TIERS: tuple[str, ...] = ("candidate", "applied", "validated", "canonical")


def next_tier(t: str) -> str:
    """The tier one rung up, clamped at the top (`canonical` stays `canonical`)."""
    i = TIERS.index(t)
    return TIERS[min(i + 1, len(TIERS) - 1)]


def prev_tier(t: str) -> str:
    """The tier one rung down, clamped at the bottom (`candidate` stays `candidate`)."""
    i = TIERS.index(t)
    return TIERS[max(i - 1, 0)]


def apply_verdict(
    rec: ProvenanceRecord, passed: bool, *, hysteresis: int = 2
) -> ProvenanceRecord:
    """Fold one A/B verdict into a provenance record and return the updated (new) record.

    passed -> promote one tier and reset the fail streak.
    failed -> increment the fail streak; only once it reaches `hysteresis` do we demote one tier,
              record the `from->to` transition in `demotions`, and reset the streak.
    """
    if passed:
        return dataclasses.replace(rec, tier=next_tier(rec.tier), fail_count=0)

    streak = rec.fail_count + 1
    if streak < hysteresis:
        return dataclasses.replace(rec, fail_count=streak)

    demoted = prev_tier(rec.tier)
    return dataclasses.replace(
        rec,
        tier=demoted,
        fail_count=0,
        demotions=rec.demotions + (f"{rec.tier}->{demoted}",),
    )
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_lifecycle.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/lifecycle.py tests/kb/test_lifecycle.py && git commit -m "feat(kb): lifecycle tier manager — promote on pass, hysteresis demote (B2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Repo is clean. Here is the task block.

### Task B3: Harvester — cluster-by-signature + split-firewalled candidate (offline, GATED)
**Files:**
- Create: `groundloop/kb/harvest/__init__.py`
- Create: `groundloop/kb/harvest/cluster.py`
- Test: `tests/kb/test_harvest.py`

GATED: optional harvester slice — depends only on OUR `groundloop/kb/validate.py` (`owner_denylist`); touches no SP3-owned files and no `groundloop/core/`. Offline: the test does no network / model / atlas I/O.

- [ ] **Step 1: Write the failing test**
```python
"""Offline harvester (B3): cluster-by-signature + the split-firewalled candidate minter.

No network / no model / no atlas — pure dict + TOML round-trip through the real validator.
"""
from __future__ import annotations

from groundloop.kb.harvest import candidate_from_cluster, cluster_by_signature
from groundloop.kb.validate import validate_corpus


def _dump_corpus(skill: dict) -> str:
    """Serialize ONE skill dict to a `[[skill]]` corpus TOML (no tomli_w in the venv)."""
    def b(v: object) -> str:  # TOML basic string
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def arr(xs) -> str:
        return "[" + ", ".join(b(x) for x in xs) + "]"

    lines = [
        "[[skill]]",
        f"id = {b(skill['id'])}",
        f"provenance = {b(skill['provenance'])}",
        f"signals = {arr(skill.get('signals', []))}",
        f"hint_apis = {arr(skill.get('hint_apis', []))}",
        "guidance = '''\n" + skill["guidance"] + "\n'''",
        "",
        "[skill.match]",
    ]
    for key, val in skill["match"].items():
        lines.append(f"{key} = {arr(val)}")
    return "\n".join(lines) + "\n"


def _cases() -> list[dict]:
    return [
        {"case_id": "c1", "signals": {"errors": ["NullPointerException"], "libraries": []}},
        {"case_id": "c2", "signals": {"errors": ["NullPointerException"], "packages": ["com.example"]}},
        {"case_id": "c3", "signals": {"errors": [], "libraries": ["libwidget.so"]}},
    ]


def test_cluster_by_signature_groups_by_top_signal():
    groups = cluster_by_signature(_cases())
    assert groups == {"nullpointerexception": ["c1", "c2"], "libwidget.so": ["c3"]}


def test_candidate_eval_and_holdout_splits_are_none():
    # The split firewall: eval/holdout cases may never author a scored playbook.
    assert candidate_from_cluster("NullPointerException", ["c1", "c2"], split_tag="eval") is None
    assert candidate_from_cluster("NullPointerException", ["c1", "c2"], split_tag="holdout") is None


def test_candidate_calib_split_is_validate_clean(tmp_path):
    skill = candidate_from_cluster("NullPointerException", ["c1", "c2"], split_tag="calib")
    assert skill is not None
    assert skill["id"] == "harvest-nullpointerexception"
    for clause in ("Signature:", "Localize:", "Fix:"):
        assert clause in skill["guidance"]
    corpus = tmp_path / "candidate.toml"
    corpus.write_text(_dump_corpus(skill), encoding="utf-8")
    assert validate_corpus(str(corpus)) == []


def test_candidate_train_split_also_mints():
    assert candidate_from_cluster("IllegalStateException", ["c9"], split_tag="train") is not None


def test_candidate_leaky_signature_refused():
    # A signature that is itself a fleet-owner token can't seed a repo-agnostic playbook.
    assert candidate_from_cluster("liboboe.so", ["c1"], split_tag="calib") is None
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_harvest.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'groundloop.kb.harvest'` — package not created yet)
- [ ] **Step 3: Implement**

Create `groundloop/kb/harvest/cluster.py`:
```python
"""Offline harvester: cluster loop-visible failure cases by a coarse crash SIGNATURE, then mint a
split-firewalled candidate playbook from a cluster.

Grounding rules baked in:
- The signature is the case's single most discriminative signal (top error, else top .so, else the
  next non-empty family) — a coarse key so genuinely-related failures land in one cluster.
- `candidate_from_cluster` only mints a Skill dict for MINING splits (`calib`/`train`); for `eval`/
  `holdout` (or anything else) it returns None. This is the split firewall: no eval/holdout case may
  ever author a playbook that is later scored against eval/holdout (would be a leak).
- The minted dict is repo-agnostic + leak-safe by construction: guidance/provenance are generic
  templates, and a signature that is itself a fleet-owner token is refused (returns None) rather than
  seeding a lookup-table row. The result passes `groundloop.kb.validate.validate_corpus`.

Offline only — no network, no model, no atlas.
"""
from __future__ import annotations

import re

from groundloop.kb.validate import owner_denylist

# Signal families in priority order for the coarse signature (top error, then .so, then the rest).
_SIGNATURE_FAMILIES = ("errors", "libraries", "symbols", "classes", "methods", "packages")

# Split firewall: only these splits may author candidates.
_MINING_SPLITS = frozenset({"calib", "train"})


def _signature_of(signals: dict) -> str:
    """The coarse cluster key: the first non-empty value across the priority families, lowercased."""
    for fam in _SIGNATURE_FAMILIES:
        for val in signals.get(fam) or ():
            if val:
                return str(val).strip().lower()
    return "unknown"


def cluster_by_signature(cases: list[dict]) -> dict[str, list[str]]:
    """Group case ids by coarse crash signature.

    Each case is `{"case_id": str, "signals": {family: [tokens]}}`. Returns
    `{signature: [case_id, ...]}` preserving input order within each group.
    """
    groups: dict[str, list[str]] = {}
    for case in cases:
        cid = case.get("case_id")
        if not cid:
            continue
        sig = _signature_of(case.get("signals") or {})
        groups.setdefault(sig, []).append(cid)
    return groups


def candidate_from_cluster(signature: str, case_ids: list[str], *, split_tag: str) -> dict | None:
    """Mint a candidate Skill dict from a cluster, or None if the split firewall forbids it.

    Returns a `validate_corpus`-clean skill dict ONLY when `split_tag` is a mining split
    (`calib`/`train`); returns None for `eval`/`holdout`/anything else, for an empty signature/cluster,
    or for a signature that is itself a fleet-owner token (can't seed a repo-agnostic playbook).
    """
    if split_tag not in _MINING_SPLITS:
        return None
    sig = str(signature or "").strip()
    if not sig or not case_ids:
        return None
    sig_low = sig.lower()
    if any(tok in sig_low for tok in owner_denylist()):
        return None  # a leaky signature can't seed a repo-agnostic playbook
    slug = re.sub(r"[^a-z0-9]+", "-", sig_low).strip("-") or "signature"
    n = len(case_ids)
    guidance = (
        f"Signature: Failures clustered by the recurring crash signature '{sig}' seen across "
        f"{n} case(s) sharing this top signal.\n"
        f"Localize: Rank source files by the frame, class, or method that raises '{sig}'; begin at "
        f"the first application frame beneath the framework frames.\n"
        f"Fix: Address the root cause behind '{sig}' at that boundary; add the missing lifecycle, "
        f"null, or ownership guard and re-run the reproducing case to confirm."
    )
    return {
        "id": f"harvest-{slug}",
        "provenance": (
            f"Auto-harvested candidate (split={split_tag}) from {n} clustered case(s) "
            f"with signature '{sig}'"
        ),
        "signals": [sig_low],
        "hint_apis": [],
        "guidance": guidance,
        "match": {"any_text": [sig_low]},
    }
```

Create `groundloop/kb/harvest/__init__.py`:
```python
"""Offline KB harvester (B3): cluster loop-visible cases by signature + mint split-firewalled candidates."""
from __future__ import annotations

from groundloop.kb.harvest.cluster import candidate_from_cluster, cluster_by_signature

__all__ = ["cluster_by_signature", "candidate_from_cluster"]
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_harvest.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/harvest/__init__.py groundloop/kb/harvest/cluster.py tests/kb/test_harvest.py && git commit -m "feat(kb): offline harvester — cluster-by-signature + split-firewalled candidate (B3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```


---

## Phase C — Distillation — GATED on Phase B

### Task C1: Oracle-blind distiller (extraction + leak-scrub)
**Phase C — GATED** (deferred/optional; land only when the fix/RCA distill track is greenlit).

**Files:**
- Create: `/mnt/x/code/GroundLoop/groundloop/kb/distill/__init__.py`
- Create: `/mnt/x/code/GroundLoop/groundloop/kb/distill/extract.py`
- Test: `/mnt/x/code/GroundLoop/tests/kb/test_distill_extract.py`

- [ ] **Step 1: Write the failing test**
```python
"""Phase C (GATED) — oracle-blind distiller: verbatim extraction + owner-token leak-scrub."""
from __future__ import annotations

import pytest

from groundloop.kb.distill import distill_guidance
from groundloop.kb.validate import owner_denylist


def _trace(**kw) -> dict:
    """A LOOP-VISIBLE fix-loop trace (no oracle keys)."""
    base = {
        "ticket_summary": "app crashes on boot",
        "signals": {"errors": ["NullPointerException"]},
        "injected_guidance": (
            "Signature: NullPointerException in onCreate\n"
            "Localize: search the Activity lifecycle callbacks\n"
            "Fix: null-guard the injected binder before use"
        ),
        "patch_diff": "--- a/A.java\n+++ b/A.java\n",
        "helped": True,
    }
    base.update(kw)
    return base


def test_distill_extracts_verbatim_span_from_helped_trace():
    helped = _trace()
    ignored = _trace(
        helped=False,
        injected_guidance="Signature: unrelated\nLocalize: nowhere\nFix: do nothing",
    )
    out = distill_guidance([helped, ignored])
    # non-empty: the helped trace contributed
    assert out.strip()
    # every distilled line is a VERBATIM span of the helped trace's injected_guidance
    for line in out.splitlines():
        assert line in helped["injected_guidance"]
    # the not-helped trace contributed nothing (no free synthesis, no other sources)
    assert "unrelated" not in out
    # leak check re-passes: the distilled guidance names no fleet owner token
    hay = out.lower()
    for tok in owner_denylist():
        assert tok not in hay


def test_distill_leak_scrub_drops_owner_token_lines():
    leak_tok = sorted(owner_denylist())[0]
    helped = _trace(
        injected_guidance=(
            f"Signature: crash referencing {leak_tok} owner\n"
            "Localize: check the service binding\n"
            "Fix: retry the connection with backoff"
        ),
    )
    out = distill_guidance([helped])
    # the owner-token line is scrubbed
    assert leak_tok not in out.lower()
    # clean spans survive verbatim
    assert "Fix: retry the connection with backoff" in out


def test_distill_raises_on_expected_files_oracle_key():
    bad = _trace()
    bad["expected_files"] = ["foo/Bar.java"]
    with pytest.raises(ValueError):
        distill_guidance([bad])


def test_distill_raises_on_owning_repo_oracle_key():
    bad = _trace()
    bad["owning_repo"] = "some-repo"
    with pytest.raises(ValueError):
        distill_guidance([bad])
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_distill_extract.py -q`
Expected: FAIL (collection error — `groundloop.kb.distill` package does not exist yet)
- [ ] **Step 3: Implement**

`/mnt/x/code/GroundLoop/groundloop/kb/distill/__init__.py`:
```python
"""Oracle-blind KB guidance distiller (Phase C, GATED)."""
from __future__ import annotations

from groundloop.kb.distill.extract import distill_guidance

__all__ = ["distill_guidance"]
```

`/mnt/x/code/GroundLoop/groundloop/kb/distill/extract.py`:
```python
"""Oracle-blind guidance distiller (Phase C, GATED).

`distill_guidance(traces)` turns a batch of LOOP-VISIBLE fix-loop traces into one distilled guidance
string by EXTRACTING verbatim spans from the `injected_guidance` of traces that HELPED — never by
free-synthesizing new prose. It is oracle-blind by construction:

* it REFUSES any trace carrying an oracle-ish key (`owning_repo` / `expected_files`) — raising
  ValueError for the whole batch, and
* it RE-RUNS the KB leak check (`groundloop.kb.validate.owner_denylist`) over each extracted span,
  dropping any span that names a fleet owner token, so the distilled form stays generic to the crash
  SIGNATURE.

A trace is LOOP-VISIBLE ONLY:
    {"ticket_summary": str, "signals": dict, "injected_guidance": str, "patch_diff": str,
     "helped": bool}
"""
from __future__ import annotations

from groundloop.kb.validate import owner_denylist

# Presence of any of these proves the trace was assembled with oracle knowledge — refuse the batch.
_ORACLE_KEYS = frozenset({"owning_repo", "expected_files"})


def _has_leak(span: str, deny: set[str]) -> bool:
    """True if any owner-denylist token is a substring of `span` (same test as validate_corpus)."""
    hay = span.lower()
    return any(tok in hay for tok in deny)


def distill_guidance(traces: list[dict]) -> str:
    """Extract + leak-scrub distilled guidance from helped fix-loop traces.

    Raises ValueError if ANY trace carries an oracle-ish key (owning_repo / expected_files).
    Returns verbatim, order-preserving, de-duplicated non-empty lines drawn ONLY from the
    `injected_guidance` of `helped` traces, with every owner-token line dropped (leak-scrub).
    """
    for i, trace in enumerate(traces):
        leaked = _ORACLE_KEYS.intersection(trace)
        if leaked:
            raise ValueError(
                f"trace[{i}] carries oracle key(s) {sorted(leaked)} — distiller is oracle-blind"
            )

    deny = owner_denylist()
    out: list[str] = []
    seen: set[str] = set()
    for trace in traces:
        if not trace.get("helped"):
            continue
        for raw in str(trace.get("injected_guidance", "")).splitlines():
            line = raw.strip()
            if not line or line in seen:
                continue
            if _has_leak(line, deny):
                continue
            seen.add(line)
            out.append(line)
    return "\n".join(out)
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_distill_extract.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/distill/__init__.py groundloop/kb/distill/extract.py tests/kb/test_distill_extract.py && git commit -m "feat(kb): oracle-blind guidance distiller — verbatim extract + leak-scrub (Phase C, GATED)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task C2: LOFO fragment attribution
**Files:**
- Create: `/mnt/x/code/GroundLoop/groundloop/kb/distill/lofo.py`
- Test: `/mnt/x/code/GroundLoop/tests/kb/test_lofo.py`

- [ ] **Step 1: Write the failing test**
```python
"""LOFO attribution: keep only line-fragments whose removal drops the measured lift."""
from groundloop.kb.distill.lofo import lofo_fragments


def test_lofo_isolates_the_single_load_bearing_fragment():
    guidance = "\n".join(
        [
            "Signature: NPE in HvacController.onPropertyChanged",
            "Localize: search bind_hvac_service near the CarPropertyManager callback",
            "Fix: null-guard the property value before dispatch",
        ]
    )
    key = "Localize: search bind_hvac_service near the CarPropertyManager callback"

    def run_fn(candidate: str) -> float:
        # Exactly one fragment carries the lift; every other line is inert filler.
        return 1.0 if key in candidate else 0.0

    load_bearing = lofo_fragments(guidance, run_fn)
    assert load_bearing == [key]


def test_lofo_returns_empty_when_no_fragment_moves_the_score():
    guidance = "Signature: A\nLocalize: B\nFix: C"

    def run_fn(_candidate: str) -> float:
        return 0.42  # constant lift -> removing anything never drops it

    assert lofo_fragments(guidance, run_fn) == []


def test_lofo_skips_blank_lines_and_preserves_order():
    guidance = "line-1\n\n  \nline-2\nline-3"
    survivors = {"line-1", "line-3"}

    def run_fn(candidate: str) -> float:
        # Two load-bearing fragments; each removal must drop the score.
        return float(sum(1 for s in survivors if s in candidate))

    assert lofo_fragments(guidance, run_fn) == ["line-1", "line-3"]
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_lofo.py::test_lofo_isolates_the_single_load_bearing_fragment -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'groundloop.kb.distill.lofo'` — the module does not exist yet)
- [ ] **Step 3: Implement**
```python
"""Leave-one-fragment-out (LOFO) attribution for distilled KB guidance (SP2/SP3 KB lane, C2).

Given a candidate guidance string and a ``run_fn`` that scores its lift, LOFO ablates one
line-fragment at a time and keeps only the fragments whose removal *drops* the lift. This is the
attribution step between C1 (verbatim extraction) and C3 (re-validation of the distilled form):
it prunes inert filler so only load-bearing spans survive toward the canonical skill.
"""
from __future__ import annotations

from collections.abc import Callable


def lofo_fragments(guidance: str, run_fn: Callable[[str], float]) -> list[str]:
    """Return the load-bearing line-fragments of ``guidance`` under ``run_fn``.

    Split ``guidance`` into non-blank line fragments (original order preserved). Measure the
    baseline lift ``run_fn(guidance)``, then for each fragment measure the lift of the guidance
    with that fragment removed. A fragment is *load-bearing* iff its removal strictly lowers the
    lift (``run_fn(ablated) < baseline``); such fragments are returned in their original order.
    """
    fragments = [line for line in guidance.splitlines() if line.strip()]
    baseline = run_fn(guidance)
    load_bearing: list[str] = []
    for i, frag in enumerate(fragments):
        ablated = "\n".join(fragments[:i] + fragments[i + 1 :])
        if run_fn(ablated) < baseline:
            load_bearing.append(frag)
    return load_bearing
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_lofo.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/distill/lofo.py tests/kb/test_lofo.py && git commit -m "feat(kb): LOFO fragment attribution for distilled guidance (C2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task C3: Re-validation gate for the distilled form
**Files:**
- Create: `/mnt/x/code/GroundLoop/groundloop/kb/distill/revalidate.py`
- Test: `/mnt/x/code/GroundLoop/tests/kb/test_distill_revalidate.py`

Coordination: `groundloop/kb/distill/__init__.py` is created by Task C1; C3's test imports `groundloop.kb.distill.revalidate` as a namespace submodule of the regular `groundloop.kb` package, which resolves even without that `__init__.py` (verified), so C3 has no hard ordering blocker on C1.

- [ ] **Step 1: Write the failing test**
```python
"""C3 gate: the distilled form (B) must re-earn the form-A lift before it can be canonical."""
from groundloop.kb.distill.revalidate import revalidate

# Form A is the full (helped-trace) guidance; the two form-B variants are distillations of it.
_FORM_A = "Signature: NPE in binder. Localize: the HAL service. Fix: null-guard the callback."
_FORM_B_GOOD = "Signature: NPE in binder. Fix: null-guard the callback."   # reproduces the lift
_FORM_B_THIN = "Fix: null-guard."                                          # over-shrunk, weaker

# A tiny lift oracle standing in for a fix-eval A/B run (run_fn: Callable[[str], float]).
_LIFT = {_FORM_A: 0.31, _FORM_B_GOOD: 0.31, _FORM_B_THIN: 0.08}


def _run_fn(guidance: str) -> float:
    return _LIFT[guidance]


def test_distilled_form_that_reproduces_lift_is_accepted():
    assert revalidate(_FORM_B_GOOD, _LIFT[_FORM_A], _run_fn) is True


def test_distilled_form_that_underperforms_is_rejected():
    # B < A beyond the (zero) margin -> rejected before it can be promoted to canonical.
    assert revalidate(_FORM_B_THIN, _LIFT[_FORM_A], _run_fn) is False


def test_margin_tolerates_a_small_regression_but_zero_margin_does_not():
    # Distilled scores 0.29 vs a 0.31 baseline — a 0.02 dip.
    assert revalidate(_FORM_B_GOOD, 0.31, lambda g: 0.29, margin=0.05) is True
    assert revalidate(_FORM_B_GOOD, 0.31, lambda g: 0.29, margin=0.0) is False


def test_exact_baseline_passes_at_zero_margin():
    # Boundary: run_fn == baseline is a PASS (>=, not >).
    assert revalidate(_FORM_B_GOOD, 0.5, lambda g: 0.5) is True
```
- [ ] **Step 2: Run the test — expect FAIL**
Run: `.venv/bin/python -m pytest tests/kb/test_distill_revalidate.py::test_distilled_form_that_reproduces_lift_is_accepted -q`
Expected: FAIL (ModuleNotFoundError — `groundloop.kb.distill.revalidate` does not exist yet, so collection errors at import)
- [ ] **Step 3: Implement**
```python
"""C3 re-validation gate — the distilled form (B) must RE-EARN its lift before it is canonical.

Provenance: C1 `distill_guidance` compresses helped-trace spans into a shorter form B and C2
`lofo_fragments` prunes the non-load-bearing ones. Neither guarantees B reproduces form A's lift —
compression can over-shrink. This is the gate: re-measure the lift on the distilled form and require
it to clear the baseline (form-A) lift within `margin`. If B underperforms A beyond `margin`, the
distilled form is REJECTED (False) and must not be promoted to canonical (mirrors the accept-gate
notion of lift in `groundloop/kb/accept.py`, but for the distilled artifact rather than an arm).
"""
from __future__ import annotations

from collections.abc import Callable


def revalidate(
    distilled_guidance: str,
    baseline_lift: float,
    run_fn: Callable[[str], float],
    *,
    margin: float = 0.0,
) -> bool:
    """True iff the distilled form re-earns the baseline lift within `margin`.

    ``run_fn(guidance) -> float`` returns a lift score (same Callable[[str], float] shape C2
    `lofo_fragments` consumes — e.g. a Φ_c delta or newly-solved rate from a fix-eval A/B run).
    Passes iff ``run_fn(distilled_guidance) >= baseline_lift - margin``; ``margin`` is a
    non-negative slack (0.0 demands the full baseline lift).
    """
    if margin < 0:
        raise ValueError(f"margin must be non-negative, got {margin!r}")
    return run_fn(distilled_guidance) >= baseline_lift - margin
```
- [ ] **Step 4: Run the test — expect PASS**
Run: `.venv/bin/python -m pytest tests/kb/test_distill_revalidate.py -q`
- [ ] **Step 5: Lint + commit**
```bash
.venv/bin/ruff check groundloop tests
git add groundloop/kb/distill/revalidate.py tests/kb/test_distill_revalidate.py && git commit -m "feat(kb): C3 revalidate gate — distilled form must re-earn lift before canonical

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```


---

## Execution

Execute with **superpowers:subagent-driven-development** (fresh subagent per task + two-stage review), one task at a time in order. Stop at the Phase A→B and B→C gates and run `strengthened_accept()` before proceeding. The gated live A/B (Task A3 with a real model) needs the Type-2 env flags (`KLOOP_PRODUCE_API_KEY`, `KLOOP_EMBED_BASE_URL`) — see `docs/type2-eval-setup.md`; all other tasks are hermetic (Type-1).
