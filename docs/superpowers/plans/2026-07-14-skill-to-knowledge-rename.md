# Skill → Knowledge Rename + Lane-A Deletion + kb-ab Retarget — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the KB so a `Skill` is *input-only* (raw feedstock) and the distilled unit the workflow injects is `Knowledge` (renamed from `Claim`); delete the lane that made a Skill an *output*; make the promotion gate measure Knowledge.

**Architecture:** A repo-wide rename `Claim→Knowledge` (atomic, history-preserving `git mv`), the deletion of Lane A (`kb/harvest/`, `kb/distill/`, `gloop kb-distill`, `--skills distilled`), and a retarget of `gloop kb-ab` from raw seed Skills to the distilled Knowledge registry. Zero `core/` edits; the atlas SQLite schema is untouched (`knowledge.json` is a plain JSON store). The raw-Skill injection (`--skills`, `render_skills`) is retained as an explicit *undistilled baseline* arm.

**Tech Stack:** Python 3.12 (`.venv`, uv), pytest, ruff (line 110). Spec: `docs/superpowers/specs/2026-07-13-skill-to-knowledge-rename-design.md`.

**Deviation from spec §9 (flagged):** §9's tasks 1–3 (rename core type / consumers / runtime) are **consolidated into one atomic rename task (Task 1)**. The `Claim` type is a leaf imported by ~8 modules; splitting the rename across commits would require throwaway back-compat shims and leave the suite red between commits, violating the repo rule "commit only when the suite is green." A rename is idiomatically one commit (`git diff -M` keeps it reviewable). So this plan has **5 tasks**: (1) atomic rename, (2) delete Lane A, (3) retarget kb-ab, (4) docs+memory, (5) final acceptance sweep.

**Out of scope (do NOT touch; not defects):**
- `gloop kb-promote` (`_run_kb_promote`) folds a kb-ab verdict into the *seed-Skill* provenance sidecar
  (`load_corpus(KB_SEED)` skill ids). It is **left untouched** — it governs the Skill *source* feedstock's
  authored-candidate tier, which is orthogonal to the rename. That after Task 3 `kb-ab` measures Knowledge
  while `kb-promote` walks Skill tiers is a **known follow-up** (should kb-promote operate on Knowledge
  provenance, or defer to `kb-attribute`?), recorded in memory — NOT resolved here.
- `gloop mine`, `gloop synth`, the matcher/eval arms, `groundloop/core/`, the atlas schema.

**Standing guardrails (every task):**
- **Never edit `groundloop/core/`.** Never alter the SQLite schema in `engines/atlas/store.py`.
- **`groundloop/mine/harvest.py` and `tests/mine/` are OUT OF SCOPE** — the GitHub issue→PR miner, a different subsystem that merely shares the word "harvest." "Delete harvest" means the *KB* `groundloop/kb/harvest/` **only**.
- Commit only when `.venv/bin/python -m pytest -q` is green **and** `.venv/bin/ruff check groundloop tests` is clean.
- End every commit message with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Guard against `.git/index.lock` races on the v9fs mount (retry the git command if it reports a lock).

---

## File Structure (what changes, and its responsibility)

| Path | Change | Responsibility after |
|---|---|---|
| `groundloop/kb/claim.py` → `groundloop/kb/knowledge.py` | `git mv` + rename | The atomic `Knowledge` unit + `knowledge.json` store (`KNOWLEDGE_PATH`, `load_knowledge`, `save_knowledge`) |
| `groundloop/kb/claim_ground.py` → `groundloop/kb/knowledge_ground.py` | `git mv` + rename | Oracle-blind ground-check for a candidate `Knowledge` |
| `groundloop/kb/claim_placebo.py` → `groundloop/kb/knowledge_placebo.py` | `git mv` + rename | Per-item placebo (`build_knowledge_placebo`) |
| `groundloop/kb/registry.py` | rename symbols | `KnowledgeRegistry` (`.items` attr); `select(ctx, tier_floor)` |
| `groundloop/kb/render.py` | rename symbols | `render_knowledge` → `# Grounded knowledge` preamble |
| `groundloop/kb/extract.py` | rename symbols | `knowledge_from_skill` (Skill→Knowledge distiller) |
| `groundloop/kb/attribute.py` | rename symbols | Knowledge retain-loop (`screen_knowledge`, `lofo_knowledge`, `attribute_and_govern`) |
| `groundloop/fixeval/runner.py` | rename symbols + field | `self.knowledge`, `knowledge_tier_floor`, `render_knowledge`, `FixRecord.fired_knowledge` |
| `groundloop/fixeval/archive.py` | rename JSON key | archive key `fired_knowledge` |
| `groundloop/cli/__init__.py` | rename flag/handlers + delete Lane A | `--knowledge`/`--knowledge-store`, `_load_knowledge`; `kb-extract`/`kb-attribute` internals; **remove** `kb-distill`, `--skills distilled` |
| `groundloop/kb/ab.py` | retarget | A/B injects Knowledge (candidate floor), not raw Skills |
| `groundloop/kb/harvest/`, `groundloop/kb/distill/` | **delete dirs** | — (Lane A: Skill-as-output) |
| `groundloop/kb/data/README.md`, `groundloop/kb/provenance.py` | comment fixes | drop deleted-lane references |
| `docs/*`, `CLAUDE.md`, memory | rewrite | Skill→knowledge direction; no `kb-distill` |
| tests under `tests/kb/`, `tests/fixeval/` | rename / delete | mirror code |

---

## Task 1: Atomic rename `Claim → Knowledge`

**Files (move with `git mv` to preserve history):**
- `groundloop/kb/claim.py` → `groundloop/kb/knowledge.py`
- `groundloop/kb/claim_ground.py` → `groundloop/kb/knowledge_ground.py`
- `groundloop/kb/claim_placebo.py` → `groundloop/kb/knowledge_placebo.py`
- `tests/kb/test_claim.py` → `tests/kb/test_knowledge.py`
- `tests/kb/test_claim_ground.py` → `tests/kb/test_knowledge_ground.py`
- `tests/kb/test_claim_placebo.py` → `tests/kb/test_knowledge_placebo.py`
- `tests/kb/test_lofo_claims.py` → `tests/kb/test_lofo_knowledge.py`

**Files edited in place (symbol renames):** `groundloop/kb/{registry,render,extract,attribute}.py`, `groundloop/fixeval/{runner,archive}.py`, `groundloop/cli/__init__.py`, and tests `tests/kb/{test_render,test_registry,test_extract,test_cli_kb_extract,test_cli_kb_attribute,test_attribute_screen,test_attribute_govern}.py`, `tests/fixeval/{test_runner_claims,test_cli_claims,test_archive}.py`.

> **Rename `tests/fixeval/test_runner_claims.py` → `test_runner_knowledge.py` and `tests/fixeval/test_cli_claims.py` → `test_cli_knowledge.py`** as part of this task.

**The complete symbol map (apply everywhere, code + tests):**

| Old | New |
|---|---|
| module `groundloop.kb.claim` | `groundloop.kb.knowledge` |
| module `groundloop.kb.claim_ground` | `groundloop.kb.knowledge_ground` |
| module `groundloop.kb.claim_placebo` | `groundloop.kb.knowledge_placebo` |
| class `Claim` | class `Knowledge` |
| `CLAIMS_PATH` (`data/claims.json`) | `KNOWLEDGE_PATH` (`data/knowledge.json`) |
| `load_claims` / `save_claims` / `_to_claim` | `load_knowledge` / `save_knowledge` / `_to_knowledge` |
| `ClaimRegistry` | `KnowledgeRegistry` |
| `ClaimRegistry.claims` attr | `KnowledgeRegistry.items` attr |
| `render_claims` / header `# Grounded claims` | `render_knowledge` / `# Grounded knowledge` |
| `claims_from_skill` / `parse_claims` | `knowledge_from_skill` / `parse_knowledge` |
| `build_claim_placebo` | `build_knowledge_placebo` |
| `screen_claims` / `lofo_claims` | `screen_knowledge` / `lofo_knowledge` |
| CLI `--claims` / `--claims-store` / `args.claims` / `args.claims_store` | `--knowledge` / `--knowledge-store` / `args.knowledge` / `args.knowledge_store` |
| `_load_claims` | `_load_knowledge` |
| runner `self.claims` / `self.claims_tier_floor` / `claim_pre` / `selected_claims` | `self.knowledge` / `self.knowledge_tier_floor` / `knowledge_pre` / `selected_knowledge` |
| `FixRecord.fired_claims` field **and** archive JSON key `"fired_claims"` | `fired_knowledge` |
| **UNCHANGED (keep):** `Skill`, `render_skills`, `MockSkillRegistry`, `--skills`, `FixRecord.fired_skills`, archive key `"fired_skills"`, `attribute_and_govern`, `promote_or_retire`, `load_archive` (params `claims:`→`knowledge:` only) | — |

> `Knowledge` keeps **all field names identical** to `Claim` (`id, applies_when, type, content, grounding_refs, provenance, tier, evidence`) — only the class name changes, so `render_knowledge`/registry logic is untouched apart from the type name.

- [ ] **Step 1: Move the three modules + four test files with `git mv`**

```bash
cd /mnt/x/code/GroundLoop
git mv groundloop/kb/claim.py            groundloop/kb/knowledge.py
git mv groundloop/kb/claim_ground.py     groundloop/kb/knowledge_ground.py
git mv groundloop/kb/claim_placebo.py    groundloop/kb/knowledge_placebo.py
git mv tests/kb/test_claim.py            tests/kb/test_knowledge.py
git mv tests/kb/test_claim_ground.py     tests/kb/test_knowledge_ground.py
git mv tests/kb/test_claim_placebo.py    tests/kb/test_knowledge_placebo.py
git mv tests/kb/test_lofo_claims.py      tests/kb/test_lofo_knowledge.py
git mv tests/fixeval/test_runner_claims.py tests/fixeval/test_runner_knowledge.py
git mv tests/fixeval/test_cli_claims.py    tests/fixeval/test_cli_knowledge.py
```

- [ ] **Step 2: Rename symbols inside `groundloop/kb/knowledge.py`**

Rename `Claim`→`Knowledge`, `_to_claim`→`_to_knowledge`, `load_claims`→`load_knowledge`, `save_claims`→`save_knowledge`, `CLAIMS_PATH`→`KNOWLEDGE_PATH`, and the store path `"claims.json"`→`"knowledge.json"`. Update the module docstring's spec reference. The head becomes:

```python
"""The atomic Knowledge unit — what the fix/localize loop consumes, distilled FROM a source Skill (design
spec docs/superpowers/specs/2026-07-13-skill-to-knowledge-rename-design.md). A Knowledge item is a
self-contained, GROUNDED piece of advice carrying its OWN firing predicate (`applies_when`, a
[skill.match]-style spec reusing groundloop/skills/predicate.compile_predicate) — never a whole Skill.

Knowledge persists in a machine-updated JSON store (`groundloop/kb/data/knowledge.json`, keyed by id —
analogous to kb/provenance.py's sidecar): the retain-loop mutates tier + evidence, while the human-authored
feedstock stays the aaos_kb_seed.toml Skills that extraction (kb-extract) decomposes. ...
"""
...
KNOWLEDGE_PATH = str(Path(__file__).parent / "data" / "knowledge.json")
...
@dataclass(frozen=True)
class Knowledge:
    id: str
    applies_when: dict
    type: str                     # "localize_hint" | "fix_step" | "api_requirement"
    content: str                  # the ONE thing it advises (this text enters the plan prompt)
    grounding_refs: tuple[str, ...]
    provenance: str               # the source Skill id it was distilled from (kept; never trusted)
    tier: str
    evidence: dict = field(default_factory=dict)

def _to_knowledge(kid: str, raw: dict) -> Knowledge: ...
def load_knowledge(path: str = KNOWLEDGE_PATH) -> dict[str, Knowledge]: ...
def save_knowledge(path: str, items: dict[str, Knowledge]) -> None: ...
```

- [ ] **Step 3: Update the kb-internal consumers** — `registry.py`, `render.py`, `extract.py`, `knowledge_ground.py`, `knowledge_placebo.py`, `attribute.py`

Apply the symbol map. Key spots:
- `registry.py`: `from groundloop.kb.knowledge import KNOWLEDGE_PATH, Knowledge, load_knowledge`; class `KnowledgeRegistry`; `self.items = list(items)` (constructor param `items`); `.load(path=KNOWLEDGE_PATH, ...)`; `_cvecs`/`_preds` iterate `self.items`; `select` returns `list[Knowledge]`.
- `render.py`: `from groundloop.kb.knowledge import Knowledge`; `def render_knowledge(items: list[Knowledge]) -> str:`; final return header `"\n\n# Grounded knowledge\n"`.
- `extract.py`: `knowledge_from_skill(skill, model) -> list[Knowledge]`, `parse_knowledge`, and any `extract_to_store` return type.
- `knowledge_placebo.py`: `build_knowledge_placebo(items: dict[str, Knowledge]) -> dict[str, Knowledge]`.
- `attribute.py`: `screen_knowledge`, `lofo_knowledge`; params `claims`→`knowledge`; **change the archive reads** `p.get("fired_claims")` → `p.get("fired_knowledge")` (lines ~67, 69); update the stale comment `mirrors kb/distill/lofo.lofo_fragments` → `the knowledge-granular LOFO` and `_build_distill_run_fn` reference → `_build_attribute_run_card_fn`.

- [ ] **Step 4: Update the runtime — `groundloop/fixeval/runner.py`**

Rename the import, the two `FixEvalRunner.__init__` params, the `FixRecord` field, and the injection block:

```python
from groundloop.kb.render import render_knowledge   # was render_claims
...
class FixRecord:
    ...
    fired_skills: tuple[str, ...] = ()
    fired_knowledge: tuple[str, ...] = ()            # was fired_claims

class FixEvalRunner:
    def __init__(self, *, issues, estate, catalog, tau_margin, tau_score,
                 max_refine=1, skills=None, knowledge=None, knowledge_tier_floor="validated",
                 skill_inject="both"):
        ...
        self.knowledge = knowledge                        # a KnowledgeRegistry or None (`--knowledge` arm)
        self.knowledge_tier_floor = knowledge_tier_floor
```

Injection block (`_one`):
```python
        if self.skills is not None or self.knowledge is not None:
            ctx = build_ctx(signals, ticket, predicted)
        skill_pre = ""
        if self.skills is not None:
            selected = self.skills.select(ctx)
            fired = tuple(getattr(s, "id", "") for s in selected)
            skill_pre = render_skills(selected)
            skill_query = _skill_query(selected) if self.skill_inject == "both" else ""
        knowledge_pre = ""
        if self.knowledge is not None:
            selected_knowledge = self.knowledge.select(ctx, self.knowledge_tier_floor)
            knowledge_pre = render_knowledge(selected_knowledge)
        preamble = skill_pre + knowledge_pre
        ...
        fired_knowledge = tuple(getattr(k, "id", "") for k in selected_knowledge)
```
and both `rec(... fired_skills=fired, fired_knowledge=fired_knowledge)` call sites (lines ~135, ~144). Rename the local `selected_claims = []` initializer to `selected_knowledge = []`.

- [ ] **Step 5: Update `groundloop/fixeval/archive.py`** — the JSON key

```python
            "fired_skills": list(getattr(r, "fired_skills", [])),
            "fired_knowledge": list(getattr(r, "fired_knowledge", [])),   # was "fired_claims"
```

- [ ] **Step 6: Update the CLI — `groundloop/cli/__init__.py`** (rename only; Lane-A deletion is Task 2)

- `_load_claims` → `_load_knowledge(kind, embedder, store_path=None)`; body: `from groundloop.kb.knowledge import KNOWLEDGE_PATH`; `from groundloop.kb.registry import KnowledgeRegistry`; `return KnowledgeRegistry.load(path=store_path or KNOWLEDGE_PATH, embedder=embedder), kind`.
- `_run_fixeval`: `want_embed = args.skills != "none" or args.knowledge != "none"`; `knowledge, knowledge_tier_floor = _load_knowledge(args.knowledge, embedder, store_path=args.knowledge_store)`; pass `knowledge=knowledge, knowledge_tier_floor=knowledge_tier_floor` to `FixEvalRunner`.
- `_run_kb_extract`: `from groundloop.kb.knowledge import KNOWLEDGE_PATH, load_knowledge, save_knowledge`; default out `KNOWLEDGE_PATH`; the "proposes 0 claims" print → "proposes 0 knowledge item(s)".
- `_run_kb_attribute`: `from groundloop.kb.attribute import attribute_and_govern, load_archive, screen_knowledge`; `from groundloop.kb.knowledge import KNOWLEDGE_PATH, load_knowledge, save_knowledge`; `store_path = args.knowledge_store or KNOWLEDGE_PATH`; `screen_knowledge(...)`; hint text `run gloop fixeval --knowledge candidate first`.
- `_build_attribute_run_card_fn`: `from groundloop.kb.knowledge_placebo import build_knowledge_placebo`; `pool.update(build_knowledge_placebo(knowledge))`; `FixEvalRunner(..., knowledge=registry, knowledge_tier_floor="candidate")`.
- Argparse: fixeval `--claims`→`--knowledge` (choices unchanged `none|candidate|validated`), `--claims-store`→`--knowledge-store` (`dest="knowledge_store"`); help text `claims.json`→`knowledge.json`. kb-attribute `--claims-store`→`--knowledge-store`. Update all help strings mentioning "claim".

- [ ] **Step 7: Update the moved test files + the in-place tests**

Apply the symbol map to every renamed/edited test. Specifically: `test_knowledge.py`, `test_knowledge_ground.py`, `test_knowledge_placebo.py`, `test_lofo_knowledge.py`, `test_render.py`, `test_registry.py`, `test_extract.py`, `test_cli_kb_extract.py`, `test_cli_kb_attribute.py`, `test_attribute_screen.py`, `test_attribute_govern.py`, `test_runner_knowledge.py`, `test_cli_knowledge.py`, `test_archive.py`. Notably:
- `test_archive.py`: `fired_claims`→`fired_knowledge` (construct + payload assert, lines ~64–76). Keep the `fired_skills` cases unchanged.
- `test_cli_kb_attribute.py` / `test_attribute_screen.py`: archive fixtures `"fired_claims"`→`"fired_knowledge"`.
- `test_cli_knowledge.py`: `--claims`→`--knowledge`, `--claims-store`→`--knowledge-store`, `_load_claims`→`_load_knowledge`, `reg.claims`→`reg.items`, `save_claims`/`load_claims`→`save_knowledge`/`load_knowledge`, `claims.json`→`knowledge.json`.

- [ ] **Step 8: Run the full suite — expect RED until this step is complete, then green**

> The suite is red mid-task (partial rename) — that is expected. Do not commit until it is fully green.

```bash
cd /mnt/x/code/GroundLoop && .venv/bin/python -m pytest -q
```
Expected: PASS (same test count minus none — all renamed tests collected under new names).

- [ ] **Step 9: Acceptance grep #1 + ruff — must be clean**

```bash
cd /mnt/x/code/GroundLoop
rg -n --no-heading -g '!docs/**' -e '\bClaim\b' -e 'ClaimRegistry' -e 'render_claims' -e 'claims_from_skill' \
   -e 'CLAIMS_PATH' -e 'load_claims' -e 'save_claims' -e '--claims\b' -e 'claims\.json' \
   -e 'fired_claims' -e 'kb\.claim\b' -e 'kb\.claim_ground' -e 'kb\.claim_placebo' -e 'screen_claims' \
   -e 'lofo_claims' -e 'build_claim_placebo' groundloop tests
# EXPECT: no output (Lane-A's --skills distilled / kb-distill still reference nothing here; that is Task 2)
.venv/bin/ruff check groundloop tests
```
Expected: the `rg` prints nothing; ruff clean.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(kb): rename Claim -> Knowledge across the KB (Skill is now input-only)

A Skill is raw source feedstock; the distilled unit the loop injects is Knowledge.
git-mv claim/claim_ground/claim_placebo -> knowledge*; ClaimRegistry->KnowledgeRegistry,
render_claims->render_knowledge (# Grounded knowledge), claims_from_skill->knowledge_from_skill,
--claims->--knowledge, claims.json->knowledge.json, FixRecord.fired_claims->fired_knowledge
(field + archive key). Skill/render_skills/--skills/fired_skills unchanged (raw baseline arm).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Delete Lane A (harvest / distill / kb-distill / `--skills distilled`)

**Files:**
- Delete dirs: `groundloop/kb/harvest/`, `groundloop/kb/distill/`
- Delete tests: `tests/kb/test_harvest.py`, `tests/kb/test_lofo.py`, `tests/kb/test_distill_extract.py`, `tests/kb/test_distill_revalidate.py`, `tests/kb/test_cli_kb_distill.py`, `tests/fixeval/test_skills_distilled_arm.py`
- Modify: `groundloop/cli/__init__.py` (remove `kb-distill`, `_run_kb_distill`, `_build_distill_run_fn`, `_ALL_SPLITS`/`_MINING_SPLITS`, `--skills distilled`), `groundloop/kb/provenance.py:10` (comment), `groundloop/kb/data/README.md:54-55` (comment)

> **Do NOT touch `groundloop/kb/attribute.py`'s functionality** — it has NO `import` from `kb.distill` (only the comment updated in Task 1). Confirm with `rg -n 'from groundloop.kb.distill|import.*distill' groundloop/kb/attribute.py` → no output before deleting.
> **Do NOT touch `groundloop/mine/harvest.py` or `tests/mine/`.**

- [ ] **Step 1: Confirm no live importer depends on the deleted dirs (besides the deleted tests + kb-distill CLI)**

```bash
cd /mnt/x/code/GroundLoop
rg -n --no-heading -e 'from groundloop\.kb\.harvest' -e 'from groundloop\.kb\.distill' -e 'import.*kb\.(harvest|distill)' groundloop tests
```
Expected importers: only `tests/kb/test_harvest.py`, `tests/kb/test_lofo.py`, `tests/kb/test_distill_*`, `tests/kb/test_cli_kb_distill.py`, and `groundloop/cli/__init__.py` (kb-distill handler). If anything else appears, STOP and report.

- [ ] **Step 2: `git rm` the dirs + tests**

```bash
git rm -r groundloop/kb/harvest groundloop/kb/distill
git rm tests/kb/test_harvest.py tests/kb/test_lofo.py tests/kb/test_distill_extract.py \
       tests/kb/test_distill_revalidate.py tests/kb/test_cli_kb_distill.py \
       tests/fixeval/test_skills_distilled_arm.py
```

- [ ] **Step 3: Remove the `--skills distilled` arm in `cli/__init__.py`**

In `_load_skills`, delete the `elif kind == "distilled":` branch (the `distilled.toml` path). In the fixeval argparse, change the `--skills` choices and help to drop `distilled`:
```python
    fx.add_argument("--skills", choices=["none", "mock", "kb", "placebo"], default="none",
                    help="raw-Skill baseline arm (UNDISTILLED source): none | mock | kb | placebo")
```

- [ ] **Step 4: Remove the `kb-distill` command surface in `cli/__init__.py`**

Delete: the function `_run_kb_distill` (≈643–735), `_build_distill_run_fn` (≈582–641), the split-firewall constants `_ALL_SPLITS`/`_MINING_SPLITS` (≈535–538, only used by kb-distill), the `kds = sub.add_parser("kb-distill", ...)` subparser block (≈1186–1198), and the dispatch lines `if args.cmd == "kb-distill": return _run_kb_distill(args)` (≈1528–1529).

```bash
# after editing, prove the surface is gone:
rg -n --no-heading -e 'kb-distill' -e '_run_kb_distill' -e '_build_distill_run_fn' -e '_MINING_SPLITS' -e 'distilled' groundloop/cli/__init__.py
```
Expected: no output.

- [ ] **Step 5: Fix the two stale comments**

`groundloop/kb/provenance.py:10` — the GATING comment naming `harvest/`+`distill/`: reword to drop those (e.g. "Phase B (this sidecar + `lifecycle.py`) gates the Knowledge retain-loop..."). `groundloop/kb/data/README.md:54-55` — drop the "distilled/harvested Skill ... the distiller must be oracle-blind and split-firewalled" sentence.

- [ ] **Step 6: Run suite + ruff + acceptance grep #2**

```bash
cd /mnt/x/code/GroundLoop && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
test ! -d groundloop/kb/harvest && test ! -d groundloop/kb/distill && echo "dirs gone"
.venv/bin/gloop --help | rg -q 'kb-distill' && echo "FAIL: kb-distill still listed" || echo "kb-distill gone"
.venv/bin/gloop fixeval --help | rg -q 'distilled' && echo "FAIL: distilled still listed" || echo "distilled arm gone"
git diff --quiet groundloop/mine/harvest.py && echo "mine/harvest.py untouched"
```
Expected: PASS, ruff clean, "dirs gone", "kb-distill gone", "distilled arm gone", "mine/harvest.py untouched".

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(kb): delete Lane A (harvest/distill/kb-distill) — a Skill is never an output

Removes the lane that MINTED Skills from cases (kb/harvest/, kb/distill/, gloop kb-distill,
--skills distilled, distilled.toml path) + its tests. The raw-Skill baseline arm (--skills
none|mock|kb|placebo) and the Skill->Knowledge distiller (kb-extract) are kept.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Retarget `gloop kb-ab` to the Knowledge arm

**Files:** `groundloop/kb/ab.py` (modify `_registry_for` + `run_ab`), `tests/kb/test_kb_ab_retarget.py` (create).

**Behavior:** the A/B injects distilled **Knowledge** (candidate floor) for `kb`, a per-item knowledge **placebo** for `placebo`, and nothing for `none` — via the `FixEvalRunner(knowledge=...)` path, not `skills=`. On an empty `knowledge.json` every arm selects nothing → byte-identical to `none` (honest cold-start).

- [ ] **Step 1: Write the failing tests** — `tests/kb/test_kb_ab_retarget.py`

```python
"""kb-ab retargeted to Knowledge: _registry_for builds a KnowledgeRegistry (not a raw-Skill registry);
an empty knowledge store -> every arm selects nothing (byte-identical to none); a populated store ->
kb selects the item and placebo selects its length-matched control."""
from __future__ import annotations

from groundloop.core.types import Signals
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.registry import KnowledgeRegistry
from groundloop.skills.ctx import SkillCtx


def _ctx() -> SkillCtx:
    # SkillCtx(signals, repo, text) — loop-visible only (see groundloop/skills/ctx.py)
    return SkillCtx(signals=Signals(), repo="r", text="segv null deref crash")


def _k(kid="k-seg") -> Knowledge:
    return Knowledge(id=kid, applies_when={"always": True}, type="fix_step",
                     content="Reject the 0 handle at entry.", grounding_refs=(), provenance="skill-x",
                     tier="candidate", evidence={})


def test_none_arm_is_none(monkeypatch):
    from groundloop.kb import ab
    assert ab._registry_for("none", None) is None


def test_empty_store_every_arm_selects_nothing(monkeypatch):
    from groundloop.kb import ab
    monkeypatch.setattr(ab, "load_knowledge", lambda path=None: {})
    kb = ab._registry_for("kb", None)
    placebo = ab._registry_for("placebo", None)
    assert isinstance(kb, KnowledgeRegistry) and isinstance(placebo, KnowledgeRegistry)
    assert kb.select(_ctx(), "candidate") == []       # empty store -> byte-identical to none
    assert placebo.select(_ctx(), "candidate") == []


def test_populated_store_kb_and_placebo_fire(monkeypatch):
    from groundloop.kb import ab
    monkeypatch.setattr(ab, "load_knowledge", lambda path=None: {"k-seg": _k()})
    kb_sel = ab._registry_for("kb", None).select(_ctx(), "candidate")
    pl_sel = ab._registry_for("placebo", None).select(_ctx(), "candidate")
    assert [k.id for k in kb_sel] == ["k-seg"]
    assert len(pl_sel) == 1 and pl_sel[0].id == "placebo-k-seg"
    assert pl_sel[0].content != kb_sel[0].content     # placebo is scrambled/irrelevant


def test_run_ab_threads_knowledge_not_skills(monkeypatch, tmp_path):
    """run_ab constructs FixEvalRunner with knowledge=..., never skills=... (the retarget)."""
    from groundloop.kb import ab
    seen = {}

    class _Spy:
        def __init__(self, **kw):
            seen.update(kw)
        def run(self, *a, **k):
            return []
    monkeypatch.setattr(ab, "FixEvalRunner", _Spy)
    monkeypatch.setattr(ab, "_make_fixer", lambda: object())
    monkeypatch.setattr(ab, "grade_fix_all", lambda records, oracle_by_case=None: {"arms": {}})
    monkeypatch.setattr(ab, "load_cases", lambda ds: [])
    monkeypatch.setattr(ab, "load_eval_oracle", lambda c: None)
    monkeypatch.setattr(ab, "build_arms", lambda membership_index=None: [])
    monkeypatch.setattr(ab, "AtlasIndex", lambda db: object())
    monkeypatch.setattr(ab, "MockJira", lambda ds: object())
    monkeypatch.setattr(ab, "GitFixtureEstate", lambda r, w: object())
    monkeypatch.setattr(ab, "load_knowledge", lambda path=None: {})
    cat = tmp_path / "catalog.json"
    cat.write_text('[{"name": "r"}]')
    ab.run_ab(dataset="d", repos="r", index_db="a.db", catalog_path=str(cat),
              out_dir=str(tmp_path / "o"), arms=("kb",))
    assert "knowledge" in seen and "skills" not in seen
    assert seen["knowledge_tier_floor"] == "candidate"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/kb/test_kb_ab_retarget.py -q
```
Expected: FAIL (`ab._registry_for` still returns a MockSkillRegistry / `load_knowledge` not imported in `ab`).

- [ ] **Step 3: Rewrite `groundloop/kb/ab.py`** — imports, `_registry_for`, `run_ab`

Replace the imports block + `_registry_for` + the runner construction inside `run_ab`:
```python
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.core.types import RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases, load_eval_oracle
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.fixeval.scorecard import grade_fix_all
from groundloop.kb.knowledge import KNOWLEDGE_PATH, load_knowledge
from groundloop.kb.knowledge_placebo import build_knowledge_placebo
from groundloop.kb.registry import KnowledgeRegistry

# _make_fixer() unchanged

def _registry_for(arm: str, embedder):
    """Map an A/B arm to its KNOWLEDGE registry (None = the true no-op `none` arm). kb = distilled
    Knowledge (candidate floor); placebo = the per-item knowledge placebo (same firing set, scrambled
    content). Reads knowledge.json; an empty store -> empty registry -> every arm == none (cold-start)."""
    if arm == "none":
        return None
    store = load_knowledge(KNOWLEDGE_PATH)
    if arm == "kb":
        return KnowledgeRegistry(list(store.values()), embedder=embedder)
    if arm == "placebo":
        return KnowledgeRegistry(list(build_knowledge_placebo(store).values()), embedder=embedder)
    raise ValueError(f"unknown A/B arm: {arm!r} (expected one of none|kb|placebo)")


def run_ab(*, dataset, repos, index_db, catalog_path, out_dir,
           arms=("none", "kb", "placebo"), embedder=None) -> dict[str, dict]:
    catalog = [RepoRef(r["name"]) for r in json.loads(Path(catalog_path).read_text())]
    cases = load_cases(dataset)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}
    eval_arms = build_arms(membership_index=AtlasIndex(index_db))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cards: dict[str, dict] = {}
    for arm in arms:
        knowledge = _registry_for(arm, embedder)
        runner = FixEvalRunner(issues=MockJira(dataset),
                               estate=GitFixtureEstate(repos, str(out / f"_work-{arm}")),
                               catalog=catalog, tau_margin=0.0, tau_score=0.0,
                               knowledge=knowledge, knowledge_tier_floor="candidate")
        records = runner.run(cases, eval_arms, fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        (out / f"scorecard-{arm}.json").write_text(json.dumps(card, indent=2))
        cards[arm] = card
    return cards
```
Update the module docstring: the `kb` arm now injects "distilled Knowledge (candidate floor) at the FIX stage" rather than "OUR 12-skill corpus."

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/kb/test_kb_ab_retarget.py -q
```
Expected: PASS (4 tests).

- [ ] **Step 5: Full suite + ruff**

```bash
cd /mnt/x/code/GroundLoop && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
```
Expected: PASS + clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(kb): kb-ab gates on distilled Knowledge, not raw Skills

_registry_for/run_ab build a KnowledgeRegistry over knowledge.json (candidate floor) for the kb arm
and a per-item knowledge placebo for the placebo arm, injected via FixEvalRunner(knowledge=...).
Empty store -> every arm byte-identical to none (honest cold-start), asserted in test_kb_ab_retarget.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Docs + memory rewrite

**Files:** `docs/kb-distillation.md`, `CLAUDE.md`, `docs/fix-loop.md`, `docs/capabilities.md`, `docs/workflows.md`, `groundloop/kb/data/README.md`, `docs/STATUS.md`, `docs/results-log.md`, and memory under `/home/vinc/.claude/projects/-mnt-x-code-GroundLoop/memory/`.

- [ ] **Step 1: Rewrite `docs/kb-distillation.md`**

- Retitle line 1 → `# How the KB distills Skills into knowledge`.
- §1 "What this doc is" → `how raw crash-RCA Skills (authored playbooks) are distilled into small, injectable **Knowledge** items`.
- §2 "What a Skill is" → frame the `Skill` as the **raw authored source/feedstock** (input only); add/replace the primitive section with `Knowledge` (was `Claim`) as the distilled, injectable unit; show the `Knowledge` dataclass.
- **Delete** all Lane-A sections (§4 Lane A harvest/distill, the `kb-distill`/`distilled.toml` mentions, "distilled Skills" language).
- §6 Injection → `render_skills` (raw baseline) + `render_knowledge` (the headline distilled arm) + `--knowledge`.
- §8 Status → the Knowledge names; note `kb-ab` gates on Knowledge; KB remains **Candidate/unproven**.

- [ ] **Step 2: Fix `CLAUDE.md`**

Line 71 pointer → `- \`docs/kb-distillation.md\` — **how the KB distills Skills into knowledge** (the Skill source + Knowledge primitive, the distillation lane, injection, the admit-on-measured-lift retain-loop; machinery built, efficacy production-gated).` Also review the Type-2 `skills/`+`kb/` architecture bullet (line ~34) and the KB/fix-arm gotcha (grade Skill lift…) — reword any "Skill as output" implication; `--claims`→`--knowledge` if present.

- [ ] **Step 3: Fix `docs/fix-loop.md`, `docs/capabilities.md`, `docs/workflows.md`, `kb/data/README.md`**

- `fix-loop.md`: the `kb-distillation.md` pointer wording + §5 dev-experience-KB text; `--claims`→`--knowledge`; drop "distilled Skills."
- `capabilities.md`: the KB row → `Dev-experience KB (raw Skills → **knowledge** distill)`; **remove** any `kb-distill` capability entry; the KB stays Candidate.
- `workflows.md`: the per-stage feature-map row `Claim-centric KB injection` → `Knowledge injection` with `fixeval --knowledge {candidate,validated}`; drop `kb-distill` from any command list.
- `kb/data/README.md`: `Skill` = feedstock/source; distillation produces `Knowledge`; drop distilled/harvested-Skill language.

- [ ] **Step 4: Light-touch `docs/STATUS.md` + `docs/results-log.md`**

Add a dated note that the KB was renamed `Claim→Knowledge`, Lane A removed, and `kb-ab` retargeted to Knowledge (2026-07-14). **Do not rewrite historical `[proxy]`/`[production]` numbers** — only annotate the vocabulary change.

- [ ] **Step 5: Update memory**

Update these files to the Skill→Knowledge vocabulary + Lane-A removal, and add a MEMORY.md pointer for this correction:
- `/home/vinc/.claude/projects/-mnt-x-code-GroundLoop/memory/claim-centric-kb.md`
- `.../type2-kb-feedstock.md`
- `.../kb-reverdict.md`
- `.../provisional-core-loop-closure.md`
- New: `.../skill-to-knowledge-rename.md` (the correction: direction was reversed in docs + Lane A; fix = rename + delete Lane A + retarget kb-ab; KB still Candidate/unproven) + a one-line MEMORY.md entry.

- [ ] **Step 6: Verify no doc states the reversed direction**

```bash
cd /mnt/x/code/GroundLoop
rg -n --no-heading -e 'distills knowledge into Skills' -e 'knowledge becomes.*Skills' -e 'into \*\*Skills\*\*' \
   -e 'kb-distill' -e 'distilled\.toml' docs CLAUDE.md
```
Expected: no output.

- [ ] **Step 7: Commit** (docs-only; suite unaffected but run ruff for safety)

```bash
git add -A docs CLAUDE.md groundloop/kb/data/README.md
git commit -m "$(cat <<'EOF'
docs(kb): correct the distillation direction — Skills are distilled INTO knowledge

Retitle kb-distillation.md "How the KB distills Skills into knowledge"; Skill = raw source,
Knowledge = distilled injectable unit; drop all Lane-A (harvest/distill/kb-distill) docs; --claims
-> --knowledge; capabilities/workflows/fix-loop/CLAUDE.md aligned. KB stays Candidate/unproven.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Final acceptance sweep

**Files:** none (verification + a guard). Modify: none unless a check fails.

- [ ] **Step 1: Run every acceptance-criterion check from the spec §8**

```bash
cd /mnt/x/code/GroundLoop
echo "== #1 no Claim/claims refs in code+tests =="
rg -n --no-heading -g '!docs/**' -e '\bClaim\b' -e 'ClaimRegistry' -e 'render_claims' -e 'claims_from_skill' \
   -e 'CLAIMS_PATH' -e 'load_claims' -e 'save_claims' -e '--claims\b' -e 'claims\.json' -e 'fired_claims' \
   -e 'kb\.claim' -e 'screen_claims' -e 'lofo_claims' -e 'build_claim_placebo' groundloop tests || echo "OK: none"
echo "== #2 Lane A gone =="
test ! -d groundloop/kb/harvest && test ! -d groundloop/kb/distill && echo "OK: dirs gone"
rg -n 'kb-distill|distilled\.toml' groundloop || echo "OK: no kb-distill/distilled.toml in code"
.venv/bin/gloop fixeval --help | rg -q 'distilled' && echo "FAIL" || echo "OK: no distilled arm"
echo "== #3 miner untouched =="
git diff --quiet HEAD~4 -- groundloop/mine/harvest.py && echo "OK: mine/harvest.py unchanged since branch start" || echo "CHECK: mine/harvest.py changed"
echo "== #5 no reversed-direction doc line =="
rg -n 'distills knowledge into Skills|kb-distill' docs CLAUDE.md || echo "OK: docs clean"
echo "== #7 history continuity =="
git log --follow --oneline groundloop/kb/knowledge.py | tail -2
```
Expected: every line reports OK; `git log --follow` shows commits predating the rename (continuity from `claim.py`).

> If `git diff --quiet HEAD~4` doesn't line up with the actual commit count on the branch, use `git log --oneline` to find the branch-base SHA and diff `mine/harvest.py` against it instead. The invariant is: `groundloop/mine/harvest.py` is byte-identical to its state at branch start.

- [ ] **Step 2: Full suite + ruff (final gate)**

```bash
cd /mnt/x/code/GroundLoop && .venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
```
Expected: PASS + clean. Also spot-check the anti-leak invariants collected: `.venv/bin/python -m pytest tests/test_invariants.py -q`.

- [ ] **Step 3: Smoke-test the renamed CLI surface (hermetic, no creds needed)**

```bash
cd /mnt/x/code/GroundLoop
.venv/bin/gloop fixeval --help | rg -- '--knowledge'      # the renamed arm exists
.venv/bin/gloop --help | rg -e 'kb-extract' -e 'kb-attribute' -e 'kb-ab' -e 'kb-promote'   # kept commands
.venv/bin/gloop --help | rg -q 'kb-distill' && echo "FAIL: kb-distill present" || echo "OK: kb-distill gone"
```
Expected: `--knowledge` present; the four kept `kb-*` commands present; `kb-distill` gone.

- [ ] **Step 4: Final commit only if Step 1 required a fix; otherwise nothing to commit**

If any check surfaced a straggler, fix it, re-run Steps 1–2, then:
```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(kb): final acceptance sweep for the Skill->Knowledge rename

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Otherwise report the branch is clean and ready for `superpowers:finishing-a-development-branch`.

---

## Verification (end-to-end acceptance)

1. **Rename complete:** acceptance grep #1 (Task 5 Step 1) returns nothing; `git log --follow groundloop/kb/knowledge.py` shows continuity from `claim.py`.
2. **Lane A gone:** `kb/harvest/`, `kb/distill/`, `gloop kb-distill`, `--skills distilled`, `distilled.toml` all absent; `mine/harvest.py` byte-identical to branch start.
3. **kb-ab retargeted:** `test_kb_ab_retarget.py` green — `run_ab` threads `knowledge=`/`knowledge_tier_floor="candidate"`; empty store ⇒ every arm identical to `none`.
4. **Docs corrected:** no doc/`CLAUDE.md` line states knowledge→Skills; `kb-distillation.md` title reads "…distills Skills into knowledge"; `capabilities.md`/`workflows.md`/`fix-loop.md` use Knowledge vocabulary and list no `kb-distill`.
5. **Hermetic gate:** full `pytest -q` green + `ruff check groundloop tests` clean at every commit; the anti-leak invariants pass.
6. **No efficacy claim:** the KB remains **Candidate/unproven** — this plan is a naming + surface correction only.

## Critical files

- `groundloop/kb/knowledge.py` (was `claim.py`) — the `Knowledge` unit + `knowledge.json` store.
- `groundloop/kb/ab.py` — the retargeted A/B (`_registry_for`/`run_ab` over `KnowledgeRegistry`).
- `groundloop/fixeval/runner.py` — `self.knowledge`, `FixRecord.fired_knowledge`, `render_knowledge`.
- `groundloop/cli/__init__.py` — `--knowledge`/`_load_knowledge`; Lane-A surface removed.
- `docs/kb-distillation.md` — the retitled, direction-corrected guide.
- **Never touch:** `groundloop/core/`, `engines/atlas/store.py` (schema), `groundloop/mine/harvest.py`.
