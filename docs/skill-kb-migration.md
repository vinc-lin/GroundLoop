# Dev-Experience KB (Skills) — Migration Guide

> **Status:** SP3 (2026-07-06). How the real development-experience **Skills** — authored by previous
> developers, living in another environment — drop into GroundLoop's KB arm **unchanged** after
> migration. The KB is wired as a **measured eval arm** on the SP2 fix loop
> (`docs/downstream-fix-loop.md`, `docs/type2-evaluation.md`), never a trusted input.

## 1. Purpose / when to migrate

The KB arm today runs on a **`MockSkillRegistry`** seeded with real GroundLoop RCA/ops playbooks
(`groundloop/adapters/skills/data/aaos_playbooks.toml`). "Mock" is only the *wiring*; the content is
real. When the previous developers' Skills arrive (in that other environment's format), you migrate them
into `Skill` records with the shipped transform, swap the registry at the composition root, and prove the
swap is faithful with the **parity self-test**. No `groundloop/core/` change, no SQLite schema change.

## 2. The `Skill` contract (`groundloop/skills/base.py`)

```python
@dataclass(frozen=True)
class Skill:
    id: str                                 # stable, unique
    applies_to: Callable[[SkillCtx], bool]  # compiled from declarative data (see §5) — NOT hand-written code
    guidance: str                           # the playbook text injected into the fix/RCA prompt
    hint_apis: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()           # retrieval tags
    provenance: str = ""                    # source doc/commit — KB traceability
```

`render_skills(skills)` renders the selected Skills into the prompt under a `# Applicable playbooks`
header (returns `""` for an empty list ⇒ a byte-identical no-op vs the `skills=none` arm). The
`SkillRegistry` Protocol is just `select(ctx) -> list[Skill]`; `NullSkillRegistry` is the `none` arm.

## 3. The `SkillCtx` contract + oracle-blindness rule (`groundloop/skills/ctx.py`)

```python
@dataclass(frozen=True)
class SkillCtx:
    signals: Signals        # the arm's structured, extracted signals
    repo: Optional[str]     # the PREDICTED owning repo (a loop prediction, never the oracle)
    text: str               # lowercased haystack: ticket summary + description + all log content
```

`build_ctx(signals, ticket, repo)` builds it from **loop-visible inputs only**. **A predicate MUST NOT
read the oracle** — no `expected_files`, no `required_apis`, no `_oracle/` path. This is enforced by a
red-test (`tests/skills/test_invariants.py`); a KB that could read the oracle would smuggle the answer
into its selection.

## 4. Supported source formats + field mapping

| Source (foreign) | → `Skill` field | Notes |
|---|---|---|
| front-matter `id` | `id` | must be unique across the set |
| front-matter `triggers: a, b` (comma-list) | `applies_to` (via `triggers_to_spec` → `compile_predicate`) + `signals` | the FOREIGN vocabulary; each trigger name maps to a match-spec fragment |
| front-matter `provenance` | `provenance` | defaults to `md:<filename>` if absent |
| markdown body | `guidance` | everything after the `--- … ---` block |

**Primary format — markdown + front-matter** (how the real dev-experience/superpowers Skills arrive):

```markdown
---
id: aaos-native-lib-load-failure
triggers: native-crash, so-load-failure
provenance: <source>
---
<the playbook guidance…>
```

**Secondary format — the `loop-agent/bfl` `Skill` dataclass**: it already differs (carries a live
`applies_to` callable + a `tools` field, lacks `signals`/`provenance`). A `from_bfl_skill` transform
copies `id`/`guidance`/`hint_apis`, carries `applies_to` as-is, **drops `tools`**, and sets
`signals=()` + `provenance="bfl:<module>"`. (Add it alongside `migrate_markdown_skills` when that source
is needed; the markdown path is the shipped one.)

## 5. The shipped transform (`groundloop/adapters/skills/migrate.py`)

- `migrate_markdown_skills(dir)` — parse each `*.md`'s front-matter + body → `Skill`.
- `triggers_to_spec(triggers)` — translate the foreign trigger vocabulary into a declarative match spec
  (union per key, de-duped). **`KeyError` on an undocumented trigger** (fail loud, don't silently drop).
  Extend `_TRIGGER_MAP` for new triggers.
- `compile_predicate(spec)` (`groundloop/skills/predicate.py`) — compile the spec into the closure. The
  **closed match vocabulary** (unknown key → `ValueError`; every `*_regex` compiled eagerly → bad pattern
  fails at load, never mid-select):
  - `always` (bool), `repo_in` (list, over `ctx.repo`)
  - `any_text` / `all_text` / `any_text_regex` (over `ctx.text`)
  - `any_<family>` / `any_<family>_regex` for `family ∈ {packages, classes, methods, symbols, libraries,
    errors}` (over `ctx.signals.<family>`)
  - **Semantics:** clauses are **OR'd** (the skill applies if ANY clause fires); a list within a key is
    OR'd; `all_text` is the AND escape hatch; an **empty spec never fires**.
- **No code in data.** Predicates are declarative specs compiled to closures — never serialized lambdas,
  never `eval`/`exec`. This is what lets a real Skill set swap in by replacing the *data*, and what makes
  the data reviewable for secret/leak hygiene.
- **id-collision & provenance policy:** ids must be unique; on a collision, fail rather than silently
  overwrite. Always carry `provenance` so every injected playbook is traceable to its source.

## 6. Composition-root swap

The registry is chosen in `groundloop/cli/__init__.py::_run_fixeval` behind `--skills {none, mock}`:

```python
if args.skills == "mock":
    ...
    skills = MockSkillRegistry.load(embedder=embedder)   # <- replace load() with the migrated registry
runner = FixEvalRunner(..., skills=skills)
```

To ship the real Skills, build the registry from the migrated records
(`MockSkillRegistry(migrate_markdown_skills(<dir>))`) at this one call site — no `core/` edit, no runner
change. **Reuse contract:** the optional bge-m3 rerank embedder is pinned `bge-m3` and gated on
`KLOOP_EMBED_BASE_URL` (query == index); the hermetic default is predicate-only.

## 7. Parity self-test protocol (`tests/skills/test_migration_parity.py`)

The self-test proves a migrated registry reproduces the native seed's behavior. To add your own:

1. Provide the SAME logical skills in **two genuinely different shapes**: a native declarative seed
   (`seed.toml`) and the foreign markdown (`md/*.md`). **Align the two encodings** — the seed's match spec
   must equal what `triggers_to_spec` produces from the markdown triggers, or parity fails (this is the
   point: it catches a mistranslated trigger).
2. Author a **discriminating ctx panel** (`build_panel()`): each skill matches a proper, non-empty subset
   (some ctx selects only A, some only B, some both, some none). A `test_panel_is_discriminating`
   meta-assert guards against a vacuous all-empty / all-match panel.
3. Assert **predicate-only** id-set equality across the panel (`select` with **no embedder** — the bge-m3
   rerank is Type-2 and must NOT be in the parity assertion; it is non-deterministic without a fixed
   gateway).
4. Add a **negative control**: corrupt one migrated skill's predicate and assert parity **fails** on at
   least one ctx — proving the test has teeth.

## 8. Constraints recap

- **No `groundloop/core/` edit; no SQLite schema change.** The `SkillRegistry` is a non-core Protocol
  swapped at the composition root.
- The registry reads **only its data file + the loop-visible `SkillCtx`** — never `_oracle/`. Grading
  (`groundloop/fixeval/scorecard.py`) is the sole offline oracle read.
- The KB is a **measured arm, not a trusted input.** Its value is decided by running `gloop fixeval
  --skills none` vs `--skills mock` and diffing with `gloop compare` → the two-sided `accept` gate
  (positive lift on `Δfile_recall@1` **and** `Δfabrication_rate ≤ 0` honesty; cost advisory).

## 9. Honesty ceiling & troubleshooting

- The parity test proves the transform **reproduces author intent + regression-guards `triggers_to_spec`
  + documents the contract**. It does **not** prove the transform is semantically correct in general — do
  not over-read a green parity run.
- The mock seed is small: the KB arm validates **plumbing + direction of effect**, not the full lift the
  migrated Skills will show (`docs/type2-evaluation.md`; the SP3 spec §5). Treat a near-zero Δ on the mock
  seed as directional-only.
- **Troubleshooting:** parity fails ⇒ the seed spec and the trigger map disagree (diff the per-ctx
  selections). `ValueError` at load ⇒ an unknown predicate key or a bad regex in the seed. `KeyError` in
  `triggers_to_spec` ⇒ an undocumented trigger — add it to `_TRIGGER_MAP`. A skill firing on everything ⇒
  an empty/`always` match spec or an over-broad `any_text` token.
