# Authored Tier-B Test Cases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** A grounding **validator** (the anti-fabrication gate) + **3 authored, real-code-grounded, full-Tier-B**
crash cases (oboe C++ / newpipe Java / dlt-daemon C), committed as the first `[authored]` end-to-end corpus.

**Architecture:** All labs (`groundloop/mine/`) + committed case data; no `core/` or atlas-schema edit. The
validator is hermetic-tested; the cases are grounded in real fleet source at `/mnt/x/code/corpora/<repo>/` and each
must pass the validator. Spec: `docs/superpowers/specs/2026-07-20-authored-tierb-cases-design.md`.

**Tech Stack:** Python 3.12, `.venv`. Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`.

**Hard constraints:** never edit `groundloop/core/`; never alter the atlas schema; suite green + ruff clean +
import-boundary green per commit; every case grounded in REAL source (validator-enforced) + leak-safe; label
`[authored]`, never `[production]`.

---

### Task 1: The grounding validator (`validate_authored_case`) + hermetic tests

**Files:**
- Create: `groundloop/mine/authored.py`, `tests/mine/test_authored.py`, a tiny fixture repo under
  `tests/fixtures/authored_repo/`.

- [ ] **Step 1: Build the fixture repo** `tests/fixtures/authored_repo/demo-lib/` with ONE real-ish source file
  `src/decoder.c` containing a function `decode_frame` (a few lines, includes a null-deref-able line). This is the
  "real source" the validator checks against in tests.

- [ ] **Step 2: Write the failing test** `tests/mine/test_authored.py`. Build a GOOD case dir in `tmp_path`
  (`ticket.json` with a crash log naming `decode_frame`, no "demo-lib" leak; `_oracle/oracle.json` with
  `owning_repo="demo-lib"`, `expected_files=["src/decoder.c"]`, `required_apis=["decode_frame"]`,
  `fix_patch="fix.diff"`, `is_answerable=true`, `bug_kind="crash"`; a `fix.diff` touching `src/decoder.c` adding a
  `decode_frame` guard line) and assert `validate_authored_case(good_dir, fixtures_root) == []`. Then BROKEN cases,
  each asserting a specific problem string is returned:
  - expected_file not in repo → problem mentions the missing file;
  - required_api not in the file's source → problem mentions the api;
  - log names no oracle symbol → problem;
  - ticket text contains "demo-lib" (leak) → problem;
  - fix.diff doesn't touch `expected_files` → problem.
  Run → FAIL (undefined).

- [ ] **Step 3: Implement `validate_authored_case(case_dir: Path, repo_root: Path) -> list[str]`** in
  `mine/authored.py`:
  - Load `case_dir/ticket.json` + `case_dir/_oracle/oracle.json`.
  - **exists:** each `expected_files[i]` exists at `repo_root/<owning_repo>/<path>` → else problem.
  - **api present:** each `required_apis[i]` occurs (substring, word-ish) in that real file's text → else problem.
  - **log grounds:** the concatenated `ticket.logs[].content` names ≥1 oracle symbol — a `required_api`, an
    `expected_files` basename, or a `.so` derived from the repo — else problem.
  - **leak-safe:** `owning_repo` (and simple slug variants: with/without `-`, lowercased) does NOT appear in the
    ticket `summary`+`description`+logs text → else problem.
  - **fix targets:** parse `case_dir/fix.diff` — its `+++ `/`--- ` paths intersect `expected_files`, and ≥1
    `required_api` appears on an added (`+`) line → else problem(s).
  Return the accumulated problems (empty = valid). Make Step 2 PASS.

- [ ] **Step 4: Verify + commit.** `.venv/bin/python -m pytest -q` (green) · `ruff check groundloop tests` ·
  `pytest tests/architecture/test_import_boundary.py -q` · `git diff --stat -- groundloop/core groundloop/engines/atlas/store.py` empty.
```bash
git add groundloop/mine/authored.py tests/mine/test_authored.py tests/fixtures/authored_repo/
git commit -m "feat(mine): grounding validator for authored Tier-B cases

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Author the 3 grounded cases (executed as a parallel author→verify Workflow)

> The controller runs this as a Workflow: one authoring agent per case (grounded in its real repo) → one adversarial
> grounding-verifier per case (independently re-checks every oracle field against real source). Each case must pass
> BOTH `validate_authored_case` (against `/mnt/x/code/corpora`) AND the adversarial verifier before it's kept.

**Files (per case `<id>` in `groundloop/mine/data/authored/<id>/`):** `ticket.json`, `_oracle/oracle.json`,
`logs/crash.txt`, `fix.diff`; plus a shared `groundloop/mine/data/authored/catalog.json` + `README.md`.

Per case, the authoring agent:
- [ ] Reads the real repo (`oboe` / `newpipe` / `dlt-daemon` under `/mnt/x/code/corpora/`), picks a **real
  crash-plausible file + symbol** (verify by reading it — a native decode/flowgraph path in oboe; a real
  extractor/player class+method in newpipe; a real message/segment handler in dlt-daemon).
- [ ] Writes `_oracle/oracle.json`: `owning_repo`, `expected_files=[<real file>]`, `required_apis=[<real symbol>]`,
  `fix_patch="fix.diff"`, `owning_repo_sha` (from `git -C <repo> rev-parse HEAD`), `is_answerable=true`,
  `bug_kind="crash"`.
- [ ] Writes `logs/crash.txt`: a **real-shaped** crash log (native backtrace for oboe/dlt, Java stacktrace for
  newpipe) that **names the real symbol/class/`.so`** and is **leak-safe** (no repo name).
- [ ] Writes `ticket.json`: `id=<id>`, a realistic `summary`+`description` (leak-safe), `logs` embedding
  `logs/crash.txt`'s content, `component=""`, `status="Open"`.
- [ ] Writes `fix.diff`: a **plausible unified diff** touching the real `expected_files`, adding the `required_apis`
  on a real code line (e.g. a null/bounds guard) — a coherent edit to the real file (need not be the upstream fix).
- [ ] Runs `python -c "from groundloop.mine.authored import validate_authored_case; ...; print(validate_authored_case(<dir>, '/mnt/x/code/corpora'))"` → must print `[]`.

- [ ] **After all 3 pass author+verify:** write `groundloop/mine/data/authored/catalog.json` (the fleet the matcher
  ranks over — prefer the real fleet catalog from `/mnt/x/code/corpora/atlas.toml`/`corpus.toml` so match ranks
  against confusable repos, not a trivial 3-way) and a `README.md` stating the **`[authored]`** framing (designed,
  not observed; mechanics test, not effectiveness; never `[production]`).

- [ ] **Verify + commit.** Full suite green (the cases are data; the validator test still passes) · ruff ·
  `git diff --stat -- groundloop/core groundloop/engines/atlas/store.py` empty. A quick re-run of
  `validate_authored_case` over all 3 committed dirs prints `[]` each.
```bash
git add groundloop/mine/data/authored/
git commit -m "feat(corpus): 3 authored, grounded, Tier-B crash cases (oboe/newpipe/dlt-daemon)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Docs — the authored corpus + its honest role

**Files:** `docs/evaluation.md`, `docs/STATUS.md`.

- [ ] **Step 1: `docs/evaluation.md`** — under the e2e-corpus material, add the **`[authored]` corpus**: 3
  grounded, validated, full-Tier-B cases; its role is a **mechanics/capability test** (does the loop carry a
  realistic crash end-to-end over real code), **NOT** an effectiveness measurement; labeled `[authored]`, never
  `[production]`, never blended with the mined `[proxy]` reads; the validator is the anti-fabrication gate.

- [ ] **Step 2: `docs/STATUS.md`** — dated `### ... authored Tier-B cases (2026-07-20) ✅` entry: the validator +
  the 3 grounded cases committed (the first *owned, reproducible* end-to-end substrate), the honest `[authored]`
  framing, and the **OPEN gated follow-up** — run `render_e2e_funnel` over the 3 cases (match+localize vs the real
  fleet atlas; fix vs the gateway). Add to `## Next steps`.

- [ ] **Step 3: Verify + commit.** `.venv/bin/python -m pytest -q` (green) · re-read for no overclaim (`[authored]`,
  mechanics-not-effectiveness, no live read run).
```bash
git add docs/evaluation.md docs/STATUS.md
git commit -m "docs: record the [authored] Tier-B corpus + its mechanics-test role

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:** §4 validator → Task 1; §3 case anatomy + §2 the 3 cases → Task 2 (author→verify Workflow with
  the validator + adversarial grounding-check as the gate); §1/§5/§6 honest framing + labeling → Task 2 README +
  Task 3 docs. §5 "run" (the funnel read) is the gated follow-up, in Task 3's Next-steps, not a merge gate.
- **Anti-fabrication:** the whole risk of authored cases is invented grounding; Task 1's validator + Task 2's
  adversarial verifier + `owning_repo_sha` (reproducible re-validation) are the three guards.
- **No placeholders:** the real file/symbol per case is chosen at authoring time and gated by the validator — a
  spec/plan can't hardcode them without reading real source, and doing so ungrounded would defeat the point.
- **Merge gate = hermetic suite green + ruff + boundary + validator `[]` on all 3 committed cases + core/schema
  zero-diff.** The live funnel read is gated.
