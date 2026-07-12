# KB Fair-Evaluation Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make fix-loop resolution gradeable for the first time (synth-planted `required_apis`) and add a
fix-prompt-only KB injection mode, so a fair `none` vs `kb` A/B can be graded on `resolved_rate` instead of
the file-targeting proxy the KB null was (wrongly) measured on.

**Architecture:** Two hermetic code changes at the composition edges (synth data generation + the fixeval
runner/CLI) — never `core/`, never the atlas schema. The planted `required_api` is sourced from each KB
skill's own `hint_apis` and validated absent from its crash log (non-rigged + headroom-clean). A final live
A/B runbook (orchestrator-only, paused for spend approval) produces the verdict.

**Tech stack:** Python 3.12, pytest, the existing synth (`groundloop/synth/`), fixeval
(`groundloop/fixeval/`), and KB seed (`groundloop/kb/data/aaos_kb_seed.toml`).

Design: `docs/superpowers/specs/2026-07-12-kb-fair-eval-phase1-design.md`.

---

## Task 1: `CrashClass.required_api` — sourced from KB hint_apis, headroom-validated

**Files:**
- Modify: `groundloop/synth/logs.py` (add `required_api` to `CrashClass`; populate the gradeable subset)
- Test: `tests/synth/test_required_api.py` (create)

- [ ] **Step 1: Write the failing test** — provenance + headroom for every planted API.

```python
# tests/synth/test_required_api.py
import tomllib
from pathlib import Path
from groundloop.synth.logs import CRASH_CLASSES, Frame

_SEED = Path("groundloop/kb/data/aaos_kb_seed.toml")


def _hint_apis_by_skill():
    data = tomllib.loads(_SEED.read_text())
    return {s["id"]: [a.lower() for a in s.get("hint_apis", [])] for s in data["skill"]}


def _sample_log(cc) -> str:
    # deterministic frames (no atlas needed): one java + one native-ish frame
    import random
    frames = [Frame(package="com.x", cls="Foo", method="bar", filename="Foo.java", line=42)]
    rng = random.Random(0)
    return (cc.builder("libx.so", frames, rng) if cc.surface == "native"
            else cc.builder(frames, rng)).lower()


def test_planted_api_is_provenanced_and_headroom_clean():
    hints = _hint_apis_by_skill()
    gradeable = [c for c in CRASH_CLASSES if c.required_api]
    assert len(gradeable) >= 4, "need a non-trivial gradeable subset"
    for cc in gradeable:
        api = cc.required_api.lower()
        # provenance: the planted API is one the KB skill actually recommends (non-rigged)
        assert api in hints.get(cc.skill_id, []), f"{cc.skill_id}: {api} not in skill hint_apis"
        # headroom: the API must NOT already appear in the crash log (else `none` gets it free)
        assert api not in _sample_log(cc), f"{cc.skill_id}: required_api leaks into its own log"
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/synth/test_required_api.py -q`
Expected: FAIL — `CrashClass` has no `required_api` attribute.

- [ ] **Step 3: Add the field + populate the gradeable subset**

In `groundloop/synth/logs.py`, extend the NamedTuple and each entry. Add `required_api: str = ""` as the
last field of `CrashClass`, then set it ONLY where a skill `hint_api` is clean of that class's log (leave
`""` — excluded — for classes whose fix API leaks into the log or is ambiguous):

```python
class CrashClass(NamedTuple):
    skill_id: str
    surface: str
    builder: Callable
    affinity: Optional[frozenset]
    required_api: str = ""     # a KB hint_api absent from this class's log; "" => not resolution-gradeable
```

Then annotate the entries (verify each against Step-1's headroom test; these are hint_apis NOT in the log):

```python
CRASH_CLASSES: list[CrashClass] = [
    CrashClass("native-null-deref-segv", "native", build_native_backtrace, None, "GetLongField"),
    CrashClass("native-heap-corruption-abort", "native", build_native_abort, None, "std::unique_ptr"),
    CrashClass("realtime-audio-callback-underrun", "native", build_audio_underrun, frozenset({"oboe"})),
    CrashClass("foreground-service-not-started", "java", build_fgs_crash, None, "NotificationChannel"),
    CrashClass("illegalstate-after-savedinstancestate", "java", build_ise_saved_crash, None,
               "commitAllowingStateLoss"),
    CrashClass("binder-transaction-too-large", "java", build_binder_too_large_crash, None),
    CrashClass("media-player-illegal-state", "java", build_media_illegal_state_crash, None),
    CrashClass("camera-gl-surface-lifecycle", "java", build_camera_gl_crash, None),
    CrashClass("shared-state-race-cme", "java", build_cme_crash, None, "CopyOnWriteArrayList"),
    CrashClass("native-lib-load-failure", "java", build_native_lib_load_crash, None),
    CrashClass("fragment-view-after-destroy-npe", "java", build_fragment_npe_crash, None,
               "getViewLifecycleOwner"),
    CrashClass("main-thread-blocking-anr", "java", build_anr, None),
]
```

> The chosen APIs must each (a) appear in that skill's `hint_apis` in `aaos_kb_seed.toml`, and (b) be absent
> from the class's generated log. If a value fails Step-1's test, pick another `hint_api` for that skill or
> set it back to `""`. `commitAllowingStateLoss` / `CopyOnWriteArrayList` are added to those skills'
> `hint_apis` in Task 1b if not already present.

- [ ] **Step 3b: Ensure the KB skills actually name the planted APIs** (so the `kb` arm is told them)

For each gradeable class, confirm the skill's `hint_apis` (and ideally the "A correct patch references …"
line) in `groundloop/kb/data/aaos_kb_seed.toml` includes the planted `required_api`. Add the token to
`hint_apis` where missing (e.g. add `"commitAllowingStateLoss"` to `illegalstate-after-savedinstancestate`,
`"CopyOnWriteArrayList"` to `shared-state-race-cme`). Do NOT weaken any `[skill.match]` or leak a repo token.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/synth/test_required_api.py -q`
Expected: PASS (≥4 gradeable classes, all provenanced + headroom-clean).

- [ ] **Step 5: Commit**

```bash
git add groundloop/synth/logs.py groundloop/kb/data/aaos_kb_seed.toml tests/synth/test_required_api.py
git commit -m "feat(synth): plant a headroom-clean required_api per crash class (from KB hint_apis)"
```

---

## Task 2: Thread `required_api` into the synth oracle

**Files:**
- Modify: `groundloop/synth/logs.py` (`synth_log_for_case` returns the planted API)
- Modify: `groundloop/synth/dataset.py` (`write_synth_case` writes `required_apis`)
- Test: `tests/synth/test_logs.py` (extend) or `tests/synth/test_synth_dataset_required_api.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/synth/test_synth_dataset_required_api.py
import json, os
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.dataset import write_synth_case


def _mk_case(dirp, owner, files):
    os.makedirs(os.path.join(dirp, "_oracle"), exist_ok=True)
    json.dump({"summary": "boom", "logs": []}, open(os.path.join(dirp, "ticket.json"), "w"))
    json.dump({"owning_repo": owner, "expected_files": files, "required_apis": []},
              open(os.path.join(dirp, "_oracle", "oracle.json"), "w"))


def test_positive_oracle_gains_required_apis(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = tmp_path / "src" / "C1"
    _mk_case(str(src), "android-gpuimage-plus", ["src/main/cpp/GPUImageFilter.cpp"])
    cid = write_synth_case(str(src), store, str(tmp_path / "out"))
    assert cid == "C1"
    oracle = json.load(open(tmp_path / "out" / "C1" / "_oracle" / "oracle.json"))
    # native class -> a native gradeable class may fire; required_apis is [] OR a single planted api,
    # never left undefined; when the fired class is gradeable it is exactly its required_api.
    assert isinstance(oracle["required_apis"], list)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/synth/test_synth_dataset_required_api.py -q`
Expected: FAIL — `write_synth_case` never writes `required_apis` (KeyError or the field is absent).

- [ ] **Step 3: Return the planted API from `synth_log_for_case`**

In `groundloop/synth/logs.py`, change the return to include the class's `required_api`:

```python
def synth_log_for_case(store, owning_repo, files, case_id):
    rng = _rng(case_id)
    frames = crash_frames(store, owning_repo, files, rng)
    if not frames:
        return None
    cc = select_crash_class(owning_repo, frames, case_id)
    if cc.surface == "native":
        so = _NATIVE_SO.get(owning_repo, f"lib{owning_repo.split('-')[0]}.so")
        return cc.builder(so, frames, rng), "native", cc.required_api
    return cc.builder(frames, rng), "logcat", cc.required_api
```

- [ ] **Step 4: Write `required_apis` in `write_synth_case`**

In `groundloop/synth/dataset.py`, unpack the third value and write it (only when non-empty; preserve any
existing oracle APIs otherwise):

```python
    built = synth_log_for_case(store, owner, files, cid)
    if not built:
        return None
    text, kind, required_api = built
    ...
    oracle_out = {**oracle, "synth_log": kind}
    if required_api:
        oracle_out["required_apis"] = [required_api]     # makes resolved_rate gradeable
    _dump(os.path.join(dest, "_oracle", "oracle.json"), oracle_out)
```

- [ ] **Step 5: Run tests (this test + the existing synth suite)**

Run: `.venv/bin/python -m pytest tests/synth/ -q`
Expected: PASS (new test green; existing synth tests unaffected — any that call `synth_log_for_case`
directly must unpack 3 values; fix those call sites if present).

- [ ] **Step 6: Commit**

```bash
git add groundloop/synth/logs.py groundloop/synth/dataset.py tests/synth/test_synth_dataset_required_api.py
git commit -m "feat(synth): write the planted required_api into the case oracle (resolution now gradeable)"
```

---

## Task 3: Fixeval `--skills-inject {both,fix-only}` (isolate the KB from localize)

**Files:**
- Modify: `groundloop/fixeval/runner.py` (`FixEvalRunner` gains `skill_inject`; gate `skill_query`)
- Modify: `groundloop/cli/__init__.py` (add `--skills-inject`; pass to the runner)
- Test: `tests/fixeval/test_skills_inject.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/fixeval/test_skills_inject.py
from groundloop.fixeval.runner import FixEvalRunner


def test_fix_only_empties_the_localize_query(monkeypatch):
    r = FixEvalRunner(issues=None, estate=None, catalog=[], tau_margin=1.0, tau_score=1.0,
                      skills=object(), skill_inject="fix-only")
    assert r.skill_inject == "fix-only"
    # default stays "both" (back-compat)
    r2 = FixEvalRunner(issues=None, estate=None, catalog=[], tau_margin=1.0, tau_score=1.0)
    assert r2.skill_inject == "both"
```

(A fuller behavioral test — that `_one` sets `skill_query=""` under `fix-only` while the preamble is still
built — is added once the constructor param exists; assert on a captured `localize(..., skill_query=...)`
by monkeypatching `groundloop.fixeval.runner.localize` to record its `skill_query` kwarg.)

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/fixeval/test_skills_inject.py -q`
Expected: FAIL — `FixEvalRunner.__init__` has no `skill_inject`.

- [ ] **Step 3: Add the param + gate `skill_query`**

In `groundloop/fixeval/runner.py`, add to `__init__` (default `"both"`):

```python
    def __init__(self, *, issues, estate, catalog, tau_margin, tau_score, max_refine=1,
                 skills=None, claims=None, claims_tier_floor="validated", skill_inject="both"):
        ...
        self.skill_inject = skill_inject
```

In `_one`, gate the localize-query injection (line ~117):

```python
            skill_pre = render_skills(selected)
            skill_query = _skill_query(selected) if self.skill_inject == "both" else ""
```

- [ ] **Step 4: Plumb the CLI flag**

In `groundloop/cli/__init__.py`, add to the `fixeval` subparser (near `--skills`):

```python
    fx.add_argument("--skills-inject", dest="skills_inject", choices=["both", "fix-only"], default="both",
                    help="how a skill arm injects: both (localize query + fix prompt) | fix-only "
                         "(fix/plan prompt only — isolates KB fix-content value from retrieval)")
```

And pass it into the runner construction in `_run_fixeval`:

```python
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills, claims=claims, claims_tier_floor=claims_tier_floor,
                           skill_inject=args.skills_inject)
```

- [ ] **Step 5: Run the fixeval suite**

Run: `.venv/bin/python -m pytest tests/fixeval/ -q`
Expected: PASS (new test green; existing fixeval tests unaffected — default `both` preserves behavior).

- [ ] **Step 6: Commit**

```bash
git add groundloop/fixeval/runner.py groundloop/cli/__init__.py tests/fixeval/test_skills_inject.py
git commit -m "feat(fixeval): --skills-inject fix-only (KB into the fix prompt only, not the localize query)"
```

---

## Task 4: Full-suite + lint gate (pre-run checkpoint)

- [ ] **Step 1: Whole suite green**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass / gated-skips only.

- [ ] **Step 2: Lint clean**

Run: `.venv/bin/ruff check groundloop tests`
Expected: All checks passed.

(No commit — this is a checkpoint gate before the live run.)

---

## Live runbook (orchestrator only — NOT a subagent task; PAUSE for spend approval)

Off ext4, creds loaded. `DS`=a mined source dataset with `expected_files`; `ATLAS`=`atlas-9.db`;
`REPOS`=`/mnt/x/code/corpora-local`; `OUT`=`$GL_DATA/kb-fair`.

```bash
set -a; . ./.env; set +a
# 1) Build the gradeable synth slice (planted required_apis)
.venv/bin/gloop synth --src $DS --atlas-db $ATLAS --out $OUT/slice
# sanity: at least some positives now carry required_apis
grep -rl '"required_apis": \[".' $OUT/slice/*/_oracle/oracle.json | wc -l    # > 0

# 2) The fair A/B (small; --fixer plan). Snapshot each scorecard as it lands.
for spec in "none:both" "kb:fix-only" "kb:both"; do
  arm=${spec%%:*}; inj=${spec##*:}
  .venv/bin/gloop fixeval --dataset $OUT/slice --catalog $OUT/slice/catalog.json --index-db $ATLAS \
    --repos $REPOS --skills $arm --skills-inject $inj --fixer plan --out $OUT/fix-$arm-$inj.json
done

# 3) Verdict: does the metric+injection fix flip the null?
.venv/bin/gloop compare --base $OUT/fix-none-both.json --head $OUT/fix-kb-fix-only.json --out $OUT/verdict.json
# read: Δresolved_rate, Δrequired_api_pass_rate, Δfabrication_rate (n_gradeable > 0 now);
# file_recall must be ~unchanged under fix-only (localize-invariant control).
```

**Interpretation gate (honesty):** report `n_gradeable`; if the gradeable slice is tiny, state the
weak-signal caveat. `kb-fix-only` vs `none` is the fair verdict; `kb-both` vs `kb-fix-only` quantifies the
localize-pollution confound.

---

## Task 5: Record the verdict + reclassify (after the run)

**Files:** `docs/results-log.md`, `docs/capabilities.md`, `docs/workflows.md`, `docs/STATUS.md`.

- [ ] Append a `[proxy]` entry to `results-log.md`: the fair A/B (metric = `resolved_rate`, injection =
  fix-only), `n_gradeable`, the three deltas, and the verdict.
- [ ] Update the KB rows in `capabilities.md` §3 (Archived) + the `workflows.md` per-stage matrix:
  - signal → **Archived → Candidate** ("mis-tested null corrected; [proxy] resolved_rate lift, blocked on a
    [production] read"),
  - genuinely null on the correct metric → keep **Archived**, but replace the reasoning with the
    resolved_rate evidence (not `plan_target_recall`).
- [ ] Commit the held docs (`workflows.md` + `capabilities.md` + pointers from the earlier session) **together
  with** this KB reclassification, so the KB verdict is committed once and correctly.

---

## Verification (end-to-end acceptance)

1. `tests/synth/test_required_api.py` proves every planted API is provenanced (∈ KB `hint_apis`) and
   headroom-clean (∉ its log); ≥4 gradeable classes.
2. A synth slice built by `gloop synth` has positives carrying `required_apis` → `grade_fix_all` reports
   `resolved_rate.n > 0` (resolution finally gradeable).
3. `--skills-inject fix-only` leaves localize byte-identical to `--skills none` (skill_query empty) while the
   fix prompt still carries the skill preamble.
4. Full `pytest -q` green + ruff clean before the live run.
5. The live A/B yields a `resolved_rate`-based verdict with `n_gradeable > 0`; the KB is reclassified on that
   evidence (not on `plan_target_recall`).

## Critical files

- `groundloop/synth/logs.py` — `CrashClass.required_api` + `synth_log_for_case` 3-tuple.
- `groundloop/synth/dataset.py` — `write_synth_case` writes `required_apis`.
- `groundloop/kb/data/aaos_kb_seed.toml` — ensure planted APIs ∈ the skills' `hint_apis`.
- `groundloop/fixeval/runner.py` + `cli/__init__.py` — `--skills-inject fix-only`.
- Docs: `results-log.md`, `capabilities.md`, `workflows.md`, `STATUS.md` (verdict + reclassify).
