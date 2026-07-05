# Type-2 SP1b — Leak-Tight Typed Negative Mining (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute in **two review batches**: Phase 1 (Tasks 1–5) then Phase 2 (Tasks 6–10). Phase 1 MUST complete before Phase 2 (negatives are only trustworthy once the scrubber is leak-tight).

**Goal:** Make `gloop mine` (a) leak-tight — opaque `case_id`, hardened scrub, and a closed-loop real-matcher reject that drops any case whose true owner is still identifiable from the sanitized ticket — and (b) able to emit the four typed negative classes (insufficient_signal, out_of_fleet, coverage_gap, not_a_defect) that SP1a's merged eval layer already knows how to score.

**Architecture:** All changes live in `groundloop/mine/{gh_miner,harvest,scrub,emit}.py`, `groundloop/domains/android_ivi/owner_tokens.py`, and the `mine` subparser in `groundloop/cli/__init__.py`. `core/` and the SQLite schema are FROZEN. The eval read-seams already exist on master (SP1a): `dataset.load_eval_oracle` reads `is_answerable`/`negative_class`; `dataset.case_catalog` reads a per-case `catalog.json`; the runner/scorecard consume them. This plan only makes the **producer** write leak-clean typed cases.

**Tech Stack:** Python 3.12, `.venv` (uv), pytest, ruff (line length 110). Test: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check groundloop tests`. The mine tests inject a fake `gh` callable (see `tests/mine/test_gh_miner.py`); no network.

**Spec:** `docs/superpowers/specs/2026-07-05-type2-negatives-fixloop-kb-design.md` §1.2 (sources), §1.3 (schema + Tier-0 wiring). **This plan supersedes the spec's §1.3 "wire the real PR diff into fix_patch" leak-closure** — a workflow verifier empirically proved that insufficient (an owner-custom exception named in prose but absent from the fix diff still reaches the matcher). The closed-loop reject below is the corrected approach.

## Design decisions (read before implementing)

- **D1 — Closed-loop reject is the primary leak gate.** After scrubbing, the miner runs the real matcher over the sanitized ticket and **rejects the case if the true owner still ranks top-1**. This is the only mechanism that closes owner-custom-identifier leaks (e.g. `ExoPlaybackException`). The deterministic scrub fixes (Tasks 2–3) are a cheap first pass; the closed-loop reject (Task 4) is the backstop. **We do NOT wire `fix_patch`/PR-diff** — the reject subsumes it and avoids over-redaction.
- **D2 — Drop, don't over-redact (realism).** We keep generic diagnostic vocabulary (a real triager legitimately uses exception types) and instead DROP cases the matcher can still solve. This keeps the benchmark no harder than real triage.
- **D3 — Side-channel residual (documented, not fully closed here).** Hold-out cases emit a per-case `catalog.json` (owner excluded, length N−1) while other cases do not (global length N). Presence+length correlate with the OOF subclass. The current rankers score each repo independently and read neither `len(catalog)` nor the file's presence, so this is **latent, not exploited**. Flagged as a follow-up (uniform per-case catalogs); NOT closed in this plan.
- **D4 — `owning_repo` conventions per class.** hold-out OOF keeps the **real** owner in `_oracle/oracle.json` (+ `held_out_repo`) — so its ticket MUST be scrubbed of that owner (invariant #2). `not_a_defect` uses the sentinel `__NOT_A_DEFECT__` (no real owner). `insufficient_signal`/`coverage_gap` keep the real owner.
- **D5 — Atlas dependency for the closed-loop reject.** The miner gains `leak_index=None`; when None, no closed-loop check runs (back-compat). Hermetic tests pass a fixture index (`build_atlas_fixture`); the CLI passes `AtlasIndex(atlas_db)` for real mining (already Tier-1-gated — no new blocker).
- **D6 — coverage_gap is a temporal proxy.** `--coverage-cutoff <ISO date>`: a case whose `merged_at` postdates the atlas's indexed SHA has its fix absent from the index (stale-index coverage gap). The exact per-file SHA-existence check needs a checkout and is deferred; flag coverage_gap slices directional.
- **D7 — not_a_defect capped.** `--not-a-defect-limit` (keep ≤~10% per spec §1.4/§5).

## File structure
**Modify:** `groundloop/mine/gh_miner.py` (opaque id, closed-loop reject, 4-way source branch, mine knobs), `groundloop/mine/harvest.py` (`harvest_nondefects`), `groundloop/mine/scrub.py` (slug/org/.so fixes), `groundloop/mine/emit.py` (MinedCase negative fields + per-case catalog), `groundloop/domains/android_ivi/owner_tokens.py` (cameraview slug + `missing_owner_rows`), `groundloop/cli/__init__.py` (`mine` flags + `leak_index`).
**Create tests:** `tests/mine/test_mine_leak_invariants.py`, plus additions to `tests/mine/{test_gh_miner,test_harvest,test_scrub,test_owner_tokens,test_emit}.py`.

## Shared test fixture (add once to `tests/mine/conftest.py`, or reuse the equivalents already in `tests/mine/test_gh_miner.py`)

Every task's `_fake_gh_*(...)` helper is a one-liner built from these. They reproduce the exact GraphQL page shape `harvest.py` consumes (`data.repository.issues.{pageInfo,nodes}`; each node has `number/title/body/createdAt/url/labels.nodes/closedByPullRequestsReferences.nodes`):

```python
_PRODFILE = {"path": "src/main/java/app/A.java", "changeType": "MODIFIED", "additions": 3, "deletions": 1}


def _node(number, *, title="t", body="", labels=(), closer=None, merged_at="2026-01-01T00:00:00Z"):
    """One issue node. closer=None → no linked PR; else dict {slug, files, merged=True, oid, mergedAt}."""
    closers = []
    if closer is not None:
        closers = [{"number": 1, "merged": closer.get("merged", True),
                    "mergedAt": closer.get("mergedAt", merged_at),
                    "mergeCommit": {"oid": closer.get("oid", "abc123")},
                    "repository": {"nameWithOwner": closer["slug"]},
                    "files": {"totalCount": len(closer.get("files", [])), "nodes": closer.get("files", [])}}]
    return {"number": number, "title": title, "body": body, "createdAt": "2026-01-01T00:00:00Z",
            "url": f"https://github.com/x/y/issues/{number}",
            "labels": {"nodes": [{"name": n} for n in labels]},
            "closedByPullRequestsReferences": {"nodes": closers}}


def _gql_page(nodes):
    return {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}


def _fake(nodes):
    """A fake gh callable that returns one page for any graphql args (matches harvest.py's gh(args) API)."""
    return lambda _args: _gql_page(nodes)
```

Example wrappers (define each task's helper inline, one line each): a clean positive = `_fake([_node(101, body="java.lang.IllegalStateException at app.A.f(A.java:5)", closer={"slug": "TeamNewPipe/NewPipe", "files": [_PRODFILE]})])`; a prose-only case = same but `body="The list is occasionally empty after refresh."`; two positives = `_fake([_node(101, ...), _node(102, ...)])`; a dated case = pass `merged_at=` on the closer; a not_a_defect issue = `_node(200, labels=["enhancement"], closer=None)`; the leak case = `body=` the adversarial owner-symbol prose. The closed-loop test (T4) additionally passes `leak_index=AtlasIndex(build_atlas_fixture(...))`.

---

# PHASE 1 — Leak-tight foundation (Tasks 1–5)

### Task 1: Opaque `case_id` (strip the owner from ids + dir names)

**Files:** Modify `groundloop/mine/gh_miner.py`; Test: `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/mine/test_gh_miner.py`:

```python
def test_case_id_is_opaque_no_owner_leak():
    # reuse this file's existing fake-gh page helper (a single newpipe positive under src/main)
    report = mine(["TeamNewPipe/NewPipe"], _OUT, gh=_fake_gh_single(), repo_name="newpipe",
                  fleet_names=["newpipe", "osmand", "media3"], limit=5)
    import re
    from pathlib import Path
    dirs = [p for p in Path(_OUT).iterdir() if p.is_dir()]
    assert dirs, "expected at least one emitted case"
    for d in dirs:
        assert re.match(r"^gl-[0-9a-f]{12}$", d.name), f"case dir not opaque: {d.name}"
        assert "newpipe" not in d.name
        assert "newpipe" not in (d / "ticket.json").read_text()   # invariant #2 over mined output
        # mapping preserved oracle-side:
        import json
        assert json.loads((d / "_oracle" / "oracle.json").read_text())["owning_repo"] == "newpipe"
```

If `tests/mine/test_gh_miner.py` has no reusable single-positive fake-gh + `_OUT` tmp helper, add small module-level helpers `_OUT` (a tmp dir via `tempfile.mkdtemp()`) and `_fake_gh_single()` returning one GraphQL page with a merged same-repo closer touching `src/main/java/A.java` — mirror the existing `_page`/`_fake` fixtures already in that file.

- [ ] **Step 2: Run — expect FAIL** (`Run: .venv/bin/python -m pytest tests/mine/test_gh_miner.py::test_case_id_is_opaque_no_owner_leak -v`): dir name is `newpipe-<n>`, so the regex + `"newpipe" not in name` assertions fail.

- [ ] **Step 3: Implement** — in `groundloop/mine/gh_miner.py`, add at top `import hashlib`, and a helper near `_oracle_for`:

```python
def _opaque_id(slug: str, num: int) -> str:
    """Owner-free stable case id (spec §1.3 item-6 BLOCKER: {repo}-{n} leaks the owner in the dir name)."""
    return "gl-" + hashlib.sha1(f"{slug}#{num}".encode()).hexdigest()[:12]
```

Then replace the `case_id=f"{repo_name}-{cand.issue_number}"` argument in the `MinedCase(...)` construction with `case_id=_opaque_id(slug, cand.issue_number)`.

- [ ] **Step 4: Run — expect PASS.** Also run the whole mine suite to confirm `tests/mine/test_dataset_integrity.py` (it iterates emitted case dirs) stays green: `.venv/bin/python -m pytest tests/mine -q`.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/gh_miner.py tests/mine/test_gh_miner.py
git commit -m "feat(mine): opaque gl-<sha1> case_id (closes the owner-in-dir-name leak)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Scrub slug fixes — bare `cameraview` + GitHub org (`TeamNewPipe`)

**Files:** Modify `groundloop/domains/android_ivi/owner_tokens.py`, `groundloop/mine/scrub.py`, `groundloop/mine/gh_miner.py`; Test: `tests/mine/test_scrub.py`.

- [ ] **Step 1: Write failing tests** — append to `tests/mine/test_scrub.py`:

```python
from groundloop.mine.scrub import build_owner_tokens, scrub


def test_scrub_redacts_cameraview_token_but_not_generic_camera():
    tok = build_owner_tokens({"owning_repo": "cameraview", "owner_slugs": ["cameraview"],
                              "owner_namespaces": ["com.otaliastudios.cameraview"], "owner_sonames": [],
                              "expected_files": [], "fix_patch": ""})
    out = scrub("The CameraView preview is black; cameraview crashed", tok)
    assert "CameraView" not in out and "cameraview" not in out
    assert "camera" in scrub("the camera failed to open", tok)   # generic word NOT over-redacted


def test_scrub_redacts_github_org_and_keeps_generic_org():
    tok = build_owner_tokens({"owning_repo": "newpipe", "owner_slugs": ["newpipe"],
                              "owner_github_slug": "TeamNewPipe/NewPipe", "owner_namespaces": [],
                              "owner_sonames": [], "expected_files": [], "fix_patch": ""})
    out = scrub("dup of https://github.com/TeamNewPipe/NewPipe/issues/900, filed by TeamNewPipe", tok)
    assert "TeamNewPipe" not in out
    tok2 = build_owner_tokens({"owning_repo": "media3", "owner_slugs": ["media3"],
                               "owner_github_slug": "androidx/media", "owner_namespaces": [],
                               "owner_sonames": [], "expected_files": [], "fix_patch": ""})
    # generic org 'androidx' must NOT be redacted
    assert "androidx.core.app.NotificationCompat" in scrub("uses androidx.core.app.NotificationCompat", tok2)
```

- [ ] **Step 2: Run — expect FAIL** (bare `cameraview` survives; `TeamNewPipe` survives — `\bNewPipe\b` can't match inside it and `owner_github_slug` is ignored).

- [ ] **Step 3: Implement**
  1. In `groundloop/domains/android_ivi/owner_tokens.py`, add `"cameraview"` to the cameraview row's `slugs` (remove the "bare cameraview is a generic word" exclusion comment). It is redacted case-insensitively and exact-word only, so generic `camera` is unaffected.
  2. In `groundloop/mine/scrub.py` `build_owner_tokens`, add the GitHub org/name to `REPO` from a new `owner_github_slug` key, minus a generic-org stoplist:
```python
_GENERIC_ORG = {"android", "androidx", "google", "com", "org", "io", "team", "app"}
# inside build_owner_tokens, after computing the REPO set:
gh_slug = oracle.get("owner_github_slug", "")
if gh_slug and "/" in gh_slug:
    org, name = gh_slug.split("/", 1)
    for part in (org, name):
        if part and part.lower() not in _GENERIC_ORG:
            tok_repo.add(part)          # tok_repo is the set you assign to "REPO"
```
  Ensure the scrub REPO pass already lowercases/word-boundaries (it does: `re.compile(rf"\b{re.escape(slug)}\b", re.I)`), so `TeamNewPipe` (a non-generic token) is redacted while generic `androidx` is never added.
  3. In `groundloop/mine/gh_miner.py` `_oracle_for`, pass the harvested slug through: add `"owner_github_slug": cand.owning_slug` to the returned dict (Candidate already carries `owning_slug` = "owner/name").

- [ ] **Step 4: Run — expect PASS.** Full mine suite green: `.venv/bin/python -m pytest tests/mine -q`.

- [ ] **Step 5: Commit**
```bash
git add groundloop/domains/android_ivi/owner_tokens.py groundloop/mine/scrub.py groundloop/mine/gh_miner.py tests/mine/test_scrub.py
git commit -m "feat(mine): scrub bare cameraview + GitHub org (TeamNewPipe) owner tells" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Un-enumerated `.so` flag + fleet-coverage guard

**Files:** Modify `groundloop/mine/scrub.py`, `groundloop/domains/android_ivi/owner_tokens.py`, `groundloop/mine/gh_miner.py`; Test: `tests/mine/test_scrub.py`, `tests/mine/test_owner_tokens.py`.

- [ ] **Step 1: Write failing tests**

Append to `tests/mine/test_scrub.py`:
```python
from groundloop.mine.scrub import leakage_flags


def test_unknown_owner_so_is_flagged_and_rejected():
    tok = build_owner_tokens({"owning_repo": "dlt-daemon", "owner_slugs": ["dlt"],
                              "owner_namespaces": [], "owner_sonames": ["libdlt.so"],
                              "expected_files": [], "fix_patch": ""})
    flags, _ = leakage_flags("native crash in libgadgetproto.so during startup", [], tok, "dlt-daemon")
    assert flags.get("unknown_so_in_text") is True
    flags2, _ = leakage_flags("libc.so and libGLESv2.so loaded", [], tok, "dlt-daemon")
    assert flags2.get("unknown_so_in_text") is False    # generic .so not flagged
```

Append to `tests/mine/test_owner_tokens.py`:
```python
from groundloop.domains.android_ivi.owner_tokens import missing_owner_rows, FLEET_OWNER_TOKENS


def test_missing_owner_rows_flags_uncovered_fleet_repo():
    assert missing_owner_rows(["newpipe", "car-samples"]) == ["car-samples"]
    assert missing_owner_rows(list(FLEET_OWNER_TOKENS)) == []
```

- [ ] **Step 2: Run — expect FAIL** (`unknown_so_in_text` and `missing_owner_rows` don't exist).

- [ ] **Step 3: Implement**
  1. `groundloop/mine/scrub.py` `leakage_flags` — add a flag that catches any `libXXX.so` in the text that is neither an enumerated owner soname nor in `GENERIC_SO_KEEP`:
```python
# inside leakage_flags, after building `flags`:
_ALL_SO = re.findall(r"\blib\w+\.so\b", text)
known = {s.lower() for s in tok["SO"]} | {s.lower() for s in GENERIC_SO_KEEP}
flags["unknown_so_in_text"] = any(s.lower() not in known for s in _ALL_SO)
```
  The existing `admit()` already returns REJECT when `any(flags.values())`, so an un-enumerated `.so` now rejects the case (conservative drop, per D2). *(Grow `GENERIC_SO_KEEP` as legitimately-generic libs like `libssl.so` appear — flagged as expected data loss.)*
  2. `groundloop/domains/android_ivi/owner_tokens.py` — add:
```python
def missing_owner_rows(fleet_names: list[str]) -> list[str]:
    """Fleet repos with no FLEET_OWNER_TOKENS row (their owner tells cannot be scrubbed)."""
    return [n for n in fleet_names if n not in FLEET_OWNER_TOKENS]
```
  3. `groundloop/mine/gh_miner.py` `mine()` — at the top (before harvesting), fail loud on uncovered repos:
```python
    from groundloop.domains.android_ivi.owner_tokens import missing_owner_rows
    missing = missing_owner_rows([repo_name])
    if missing:
        raise ValueError(f"no FLEET_OWNER_TOKENS row for {missing}; cannot scrub its owner tells")
```

- [ ] **Step 4: Run — expect PASS.** Full mine suite green.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/scrub.py groundloop/domains/android_ivi/owner_tokens.py groundloop/mine/gh_miner.py tests/mine/test_scrub.py tests/mine/test_owner_tokens.py
git commit -m "feat(mine): flag un-enumerated owner .so + guard uncovered fleet repos" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Closed-loop real-matcher reject (the primary leak gate)

**Files:** Modify `groundloop/mine/gh_miner.py`, `groundloop/cli/__init__.py`; Test: `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/mine/test_gh_miner.py` (uses the existing tiny fixture atlas):

```python
def test_closed_loop_rejects_owner_custom_exception_leak(tmp_path):
    from groundloop.adapters.index.atlas import AtlasIndex
    from tests.fixtures.atlas_fixture import build_atlas_fixture
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    # a gpuimage issue whose PROSE names an owner-custom symbol present in the fixture atlas
    # (build a fake-gh page whose merged PR touches a prod file, issue body = the leak prose).
    gh = _fake_gh_leak_case(prose="Crash: org.wysaid.nativePort.CGEImageHandler nativeCreateHandler failed")
    out = str(tmp_path / "ds")
    report = mine(["wysaid/android-gpuimage-plus"], out, gh=gh, repo_name="android-gpuimage-plus",
                  fleet_names=["android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview"],
                  limit=5, leak_index=AtlasIndex(db))
    # the case still lets the owner win over the fixture atlas -> REJECTED, nothing emitted
    from pathlib import Path
    assert report.get("rejected_leak", 0) >= 1
    assert not any(p.is_dir() for p in Path(out).iterdir()) if Path(out).exists() else True
```

Add a `_fake_gh_leak_case(prose)` helper mirroring the file's existing fake-gh page builder, with the issue `body=prose` and a merged PR touching a `src/main/...`-style prod path so `is_minable` admits it pre-check. *(If the scrub already redacts the namespaced form, keep a bare owner-symbol in the prose that the fixture atlas attributes to the owner, so the closed-loop check is what rejects it.)*

- [ ] **Step 2: Run — expect FAIL** (`mine` has no `leak_index` param → TypeError; and with no closed-loop gate the case is emitted).

- [ ] **Step 3: Implement**
  1. `groundloop/mine/gh_miner.py` — add `leak_index=None` to `mine(...)`. After the existing `admit()` decides ADMIT/BUCKET_PROSE_ONLY (i.e. the case passed the deterministic leak-flags), run the closed-loop check on the SANITIZED signals and drop if the owner still wins:
```python
def _owner_still_wins(leak_index, sanitized_desc, sanitized_logs, owning_repo, fleet_names) -> bool:
    from groundloop.core.types import LogAttachment, Ticket, RepoRef
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
    tk = Ticket(id="x", summary="", description=sanitized_desc)
    atts = tuple(LogAttachment(path=f"logs/{i}.txt", kind="other", content=b)
                 for i, b in enumerate(sanitized_logs))
    sig = AndroidSignalExtractor().extract(atts, tk)
    ranked = leak_index.rank_repos(sig, [RepoRef(n) for n in fleet_names])
    return bool(ranked) and ranked[0].repo.name == owning_repo and ranked[0].score > 0
```
  In `mine()`, after the deterministic admit passes (verdict != REJECT) and BEFORE building/emitting the case:
```python
        if leak_index is not None and _owner_still_wins(leak_index, s_desc, s_logs, repo_name, fleet_names):
            report["rejected_leak"] += 1     # grounding-over-narrative: the matcher can still ID the owner
            continue
```
  (Leave `leak_index=None` behaviour identical to today — the existing hermetic tests that don't pass an index are unaffected.)
  2. `groundloop/cli/__init__.py` `_run_mine` — build a leak index from the atlas and pass it:
```python
    leak_index = None
    if getattr(args, "index_db", "") :
        from groundloop.adapters.index.atlas import AtlasIndex
        leak_index = AtlasIndex(args.index_db)
    report = mine([args.slug], args.out, repo_name=args.repo_name, fleet_names=fleet,
                  limit=args.limit, max_files=args.max_files, leak_index=leak_index)
```
  Add the flag to the `mn` subparser: `mn.add_argument("--index-db", default="", help="atlas.db for the closed-loop leak reject (recommended for real mining)")`.

- [ ] **Step 4: Run — expect PASS.** Full suite: `.venv/bin/python -m pytest -q`. Ruff clean.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/gh_miner.py groundloop/cli/__init__.py tests/mine/test_gh_miner.py
git commit -m "feat(mine): closed-loop real-matcher reject (drops cases where the owner is still identifiable)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Leak red-test over `gloop mine` output (the integration guard)

**Files:** Create `tests/mine/test_mine_leak_invariants.py`.

- [ ] **Step 1: Write the test** — it runs the FULL miner over a fake gh whose issue carries adversarial owner tells, then asserts the emitted dataset is oracle-blind. Reuse the SP1a normalization idiom (extended to strip `.`/`/`):

```python
import json
from pathlib import Path

from groundloop.adapters.mock.jira import MockJira
from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.mine.gh_miner import mine

OWNER = "media3"
FLEET = ["media3", "newpipe", "osmand", "organicmaps"]


def _norm(s: str) -> str:
    return s.lower().replace(" ", "").replace("-", "").replace("_", "").replace(".", "").replace("/", "")


def _needles():
    row = owner_tokens_for(OWNER)
    return {_norm(t) for t in (list(row["slugs"]) + list(row["namespaces"]) + [OWNER]) if t}


def _fake_gh():
    # a media3 issue whose prose + logs leak owner tells (brand+digit 'ExoPlayer2', class 'Media3Player'),
    # closed by a merged same-repo PR touching a production file. Uses the shared _node/_fake/_PRODFILE.
    body = ("Crash after seeking. ExoPlayer2 threw in Media3Player.\n"
            "```\njava.lang.IllegalStateException\n  at app.player.Media3Player.seek(Media3Player.java:42)\n```")
    return _fake([_node(4242, title="Seek crash in ExoPlayer2", body=body,
                        closer={"slug": "androidx/media", "files": [_PRODFILE]})])


def _mine(tmp_path):
    out = str(tmp_path / "ds")
    mine(["androidx/media"], out, gh=_fake_gh(), repo_name=OWNER, fleet_names=FLEET, limit=5)
    return [p for p in Path(out).iterdir() if p.is_dir()]


def test_mine_admits_the_adversarial_case(tmp_path):
    assert _mine(tmp_path), "scrubber/gate regression dropped everything (non-vacuity guard)"


def test_mined_case_id_and_dir_are_opaque(tmp_path):
    needles = {_norm(n) for n in FLEET}
    for d in _mine(tmp_path):
        assert not any(n in _norm(d.name) for n in needles)
        assert not any(n in _norm(json.loads((d / "ticket.json").read_text())["id"]) for n in needles)


def test_no_owner_token_in_loop_visible_fields(tmp_path):
    needles = _needles()
    for d in _mine(tmp_path):
        raw = json.loads((d / "ticket.json").read_text())
        hay = _norm(raw.get("summary", "") + raw.get("description", "") + raw.get("component", ""))
        for lg in (d / "logs").glob("*.txt"):
            hay += _norm(lg.read_text())
        assert not any(n in hay for n in needles), f"owner token survived in {d.name}"


def test_extractor_over_emitted_ticket_yields_no_owner_tokens(tmp_path):
    needles = _needles()
    root = str((Path(tmp_path) / "ds"))
    dirs = _mine(tmp_path)
    for d in dirs:
        ticket = MockJira(root).fetch(d.name)
        sig = AndroidSignalExtractor().extract(ticket.logs, ticket)
        assert not any(any(n in _norm(t) for n in needles) for t in sig.tokens()), \
            f"owner token reached the matcher for {d.name}"


def test_no_hidden_oracle_key_is_loop_visible(tmp_path):
    for d in _mine(tmp_path):
        tj = (d / "ticket.json").read_text()
        for hidden in ("is_answerable", "negative_class", "held_out_repo", "owning_repo"):
            assert hidden not in tj
```

- [ ] **Step 2: Run.** With Tasks 1–4 landed these should PASS. If any is RED, the corresponding fix is incomplete — fix the production code (do NOT weaken the test). Run: `.venv/bin/python -m pytest tests/mine/test_mine_leak_invariants.py -v`.

- [ ] **Step 3: Full suite + ruff**, then commit:
```bash
.venv/bin/python -m pytest -q && .venv/bin/ruff check groundloop tests
git add tests/mine/test_mine_leak_invariants.py
git commit -m "test(mine): leak red-test over gloop mine output (opaque id, extractor-blindness)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

*(Phase 1 review batch ends here: the miner is now leak-tight over its POSITIVE output. Phase 2 adds typed negatives on top.)*

---

# PHASE 2 — Typed emit + the four negative sources (Tasks 6–10)

### Task 6: Emit the typed-negative schema (MinedCase + emit_case)

**Files:** Modify `groundloop/mine/emit.py`; Test: `tests/mine/test_emit.py`.

- [ ] **Step 1: Write failing tests** — append to `tests/mine/test_emit.py`:

```python
import json
from pathlib import Path
from groundloop.mine.emit import MinedCase, emit_case
from groundloop.eval.dataset import CaseRef, load_eval_oracle, case_catalog


def _neg(**kw):
    base = dict(case_id="gl-abc123def456", summary="s", description="d", logs=[],
               owning_repo="cameraview", expected_files=[], required_apis=[])
    base.update(kw)
    return MinedCase(**base)


def test_emit_oracle_carries_negative_fields(tmp_path):
    d = emit_case(str(tmp_path), _neg(is_answerable=False, negative_class="out_of_fleet",
                                      held_out_repo="cameraview", case_catalog=["organicmaps", "media3"]))
    o = json.loads((Path(d) / "_oracle" / "oracle.json").read_text())
    assert o["is_answerable"] is False and o["negative_class"] == "out_of_fleet" and o["held_out_repo"] == "cameraview"


def test_emit_holdout_writes_percase_catalog_excluding_owner(tmp_path):
    d = emit_case(str(tmp_path), _neg(is_answerable=False, negative_class="out_of_fleet",
                                      held_out_repo="cameraview", case_catalog=["organicmaps", "media3"]))
    ref = CaseRef(case_id=Path(d).name, case_dir=d)
    ev = load_eval_oracle(ref)
    assert ev.is_answerable is False and ev.negative_class == "out_of_fleet"
    names = [r.name for r in case_catalog(ref)]
    assert "cameraview" not in names and len(names) >= 2      # proves emit⇄SP1a-reader contract


def test_positive_emits_unchanged(tmp_path):
    d = emit_case(str(tmp_path), _neg())                       # defaults: positive
    assert not (Path(d) / "catalog.json").is_file()
    o = json.loads((Path(d) / "_oracle" / "oracle.json").read_text())
    assert o["negative_class"] is None and o["is_answerable"] is True
    assert case_catalog(CaseRef(case_id=Path(d).name, case_dir=d)) is None


def test_emit_rejects_unknown_negative_class(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        emit_case(str(tmp_path), _neg(negative_class="typo"))


def test_emit_rejects_owner_in_percase_catalog(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        emit_case(str(tmp_path), _neg(negative_class="out_of_fleet", held_out_repo="cameraview",
                                      case_catalog=["cameraview", "media3"]))
```

- [ ] **Step 2: Run — expect FAIL** (MinedCase has no `negative_class`/`held_out_repo`/`case_catalog`; oracle.json omits them; no per-case catalog).

- [ ] **Step 3: Implement** in `groundloop/mine/emit.py`:
  1. Add fields to `MinedCase` (after `is_answerable`): `negative_class: str | None = None`, `held_out_repo: str | None = None`, `case_catalog: list[str] | None = None`.
  2. Add a module constant and validation + writes in `emit_case`:
```python
_NEGATIVE_CLASSES = {None, "out_of_fleet", "coverage_gap", "insufficient_signal", "not_a_defect"}
# at the top of emit_case, before writing:
if case.negative_class not in _NEGATIVE_CLASSES:
    raise ValueError(f"unknown negative_class: {case.negative_class!r}")
if case.case_catalog is not None and case.held_out_repo in case.case_catalog:
    raise ValueError("held_out_repo must be EXCLUDED from the per-case catalog")
```
  3. In the `_write_json(d / "_oracle" / "oracle.json", {...})` dict add `"negative_class": case.negative_class` and `"held_out_repo": case.held_out_repo`.
  4. After the oracle writes, emit the loop-visible per-case catalog when present:
```python
    if case.case_catalog is not None:
        _write_json(d / "catalog.json", [{"name": n} for n in case.case_catalog])
```

- [ ] **Step 4: Run — expect PASS** (7 emit tests incl. the cross-layer contract). Existing `test_emit.py` tests stay green (positives unchanged). Full mine suite green.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/emit.py tests/mine/test_emit.py
git commit -m "feat(mine): emit typed-negative oracle fields + per-case hold-out catalog" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `insufficient_signal` — tag the existing prose-only bucket

**Files:** Modify `groundloop/mine/gh_miner.py`; Test: `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Write failing test** — append to `tests/mine/test_gh_miner.py`:

```python
def test_prose_only_tagged_insufficient_signal(tmp_path):
    # fake-gh: PR touches a real prod .java (is_minable OK) but the issue body is pure prose (no stack/log)
    gh = _fake_gh_prose_only(body="The list is occasionally empty after refresh.")
    out = str(tmp_path / "ds")
    report = mine(["TeamNewPipe/NewPipe"], out, gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand"], limit=5)
    import json
    from pathlib import Path
    d = next(p for p in Path(out).iterdir() if p.is_dir())
    o = json.loads((d / "_oracle" / "oracle.json").read_text())
    assert o["is_answerable"] is True and o["negative_class"] == "insufficient_signal"
    assert json.loads((d / "_oracle" / "provenance.json").read_text())["source_method"] == "prose_only"
    assert report["insufficient_signal"] == 1
```

- [ ] **Step 2: Run — expect FAIL** (`negative_class`/`source_method`/`report["insufficient_signal"]` absent).

- [ ] **Step 3: Implement** in `mine()`: extend `report` init with `"insufficient_signal": 0` (and `"oof": 0, "coverage_gap": 0, "not_a_defect": 0` for later tasks). In the `verdict == "BUCKET_PROSE_ONLY"` branch, set `neg_class = "insufficient_signal"`, `source_method = "prose_only"`, `report["insufficient_signal"] += 1` (keep `is_answerable=True`). Thread `negative_class=neg_class` into the `MinedCase(...)` and `"source_method": source_method` into `provenance`. Initialise `neg_class=None`, `source_method="github_linked_pr"` per candidate before the verdict branch.

- [ ] **Step 4: Run — expect PASS.** Existing mine tests green.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/gh_miner.py tests/mine/test_gh_miner.py
git commit -m "feat(mine): tag prose-only cases negative_class=insufficient_signal" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `out_of_fleet` — catalog hold-out from admitted positives

**Files:** Modify `groundloop/mine/gh_miner.py`, `groundloop/cli/__init__.py`; Test: `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Write failing test**:
```python
def test_holdout_frac_emits_out_of_fleet(tmp_path):
    gh = _fake_gh_two_positives()          # >=2 clean admittable newpipe positives
    out = str(tmp_path / "ds")
    report = mine(["TeamNewPipe/NewPipe"], out, gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand", "media3"], limit=10, holdout_frac=0.5)
    import json
    from pathlib import Path
    oof = [d for d in Path(out).iterdir() if d.is_dir()
           and json.loads((d / "_oracle" / "oracle.json").read_text())["negative_class"] == "out_of_fleet"]
    assert oof and report["oof"] >= 1
    o = json.loads((oof[0] / "_oracle" / "oracle.json").read_text())
    assert o["is_answerable"] is False and o["held_out_repo"] == "newpipe"
    names = [r["name"] for r in json.loads((oof[0] / "catalog.json").read_text())]
    assert "newpipe" not in names and set(names) <= {"osmand", "media3"}
```

- [ ] **Step 2: Run — expect FAIL** (`holdout_frac` unknown; no OOF emitted).

- [ ] **Step 3: Implement**
  1. `mine()` — add `holdout_frac: float = 0.0`; add `_should_hold_out`:
```python
def _should_hold_out(seq: int, frac: float) -> bool:
    if frac <= 0: return False
    if frac >= 1: return True
    stride = max(2, round(1 / frac))
    return seq % stride == 0
```
  Add `answerable_seq = 0` before the harvest loop. In the ADMIT branch (not prose-only), `answerable_seq += 1`, then:
```python
        if _should_hold_out(answerable_seq, holdout_frac):
            neg_class = "out_of_fleet"; answerable = False; held_out = repo_name
            owning = repo_name          # real owner rides oracle-side (already scrubbed from the ticket)
            case_catalog_names = [n for n in fleet_names if n != repo_name]
            source_method = "hold_out"; report["oof"] += 1
        else:
            report["admitted"] += 1
```
  (Default `owning=repo_name; answerable=True; held_out=None; case_catalog_names=None` per candidate.) Thread `owning_repo=owning, is_answerable=answerable, negative_class=neg_class, held_out_repo=held_out, case_catalog=case_catalog_names` into `MinedCase(...)`. **Note:** the hold-out ticket is already scrubbed against `repo_name`'s owner tokens (built in the existing flow), so invariant #2 holds.
  2. `groundloop/cli/__init__.py` — `mn.add_argument("--holdout-frac", type=float, default=0.0, ...)` and thread `holdout_frac=args.holdout_frac` into the `mine(...)` call.

- [ ] **Step 4: Run — expect PASS.** Full suite green.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/gh_miner.py groundloop/cli/__init__.py tests/mine/test_gh_miner.py
git commit -m "feat(mine): out_of_fleet hold-out negatives (--holdout-frac, per-case catalog)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `coverage_gap` — temporal (post-cutoff) proxy

**Files:** Modify `groundloop/mine/gh_miner.py`, `groundloop/cli/__init__.py`; Test: `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Write failing test**:
```python
def test_coverage_cutoff_emits_coverage_gap(tmp_path):
    gh = _fake_gh_dated(merged_at="2026-06-01T00:00:00Z")
    out = str(tmp_path / "ds")
    mine(["TeamNewPipe/NewPipe"], out, gh=gh, repo_name="newpipe", fleet_names=["newpipe", "osmand"],
         limit=5, coverage_cutoff="2026-03-01T00:00:00Z")
    import json
    from pathlib import Path
    d = next(p for p in Path(out).iterdir() if p.is_dir())
    o = json.loads((d / "_oracle" / "oracle.json").read_text())
    assert o["negative_class"] == "coverage_gap" and o["is_answerable"] is False and o["owning_repo"] == "newpipe"
    assert not (d / "catalog.json").is_file()          # owner stays in the GLOBAL catalog
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — `mine()` add `coverage_cutoff: str = ""`. In the ADMIT branch, BEFORE the hold-out check (a case can't be both), classify a post-cutoff case as coverage_gap (ISO-Zulu strings compare lexically):
```python
        if coverage_cutoff and cand.merged_at and cand.merged_at > coverage_cutoff:
            neg_class = "coverage_gap"; answerable = False; source_method = "temporal_gap"
            report["coverage_gap"] += 1        # owning stays repo_name; NO per-case catalog
        elif _should_hold_out(answerable_seq, holdout_frac):     # unchanged from Task 8
            neg_class = "out_of_fleet"; answerable = False; held_out = repo_name
            owning = repo_name
            case_catalog_names = [n for n in fleet_names if n != repo_name]
            source_method = "hold_out"; report["oof"] += 1
        else:
            report["admitted"] += 1
```
  CLI: `mn.add_argument("--coverage-cutoff", default="", ...)` + thread it through. Flag coverage_gap slices directional in the report/log.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/gh_miner.py groundloop/cli/__init__.py tests/mine/test_gh_miner.py
git commit -m "feat(mine): coverage_gap negatives via --coverage-cutoff temporal proxy" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `not_a_defect` — label-harvest of non-linked issues

**Files:** Modify `groundloop/mine/harvest.py`, `groundloop/mine/gh_miner.py`, `groundloop/cli/__init__.py`; Test: `tests/mine/test_harvest.py`, `tests/mine/test_gh_miner.py`.

- [ ] **Step 1: Write failing tests**

`tests/mine/test_harvest.py`:
```python
def test_harvest_nondefects_keeps_labeled_unlinked_drops_positives():
    from groundloop.mine.harvest import harvest_nondefects
    page = _page_with(  # build a GraphQL page (mirror the file's existing fixture) with 4 issues:
        enhancement_unlinked=True, bug_with_merged_closer=True, unlabeled_unlinked=True,
        question_unmerged_closer=True)
    got = harvest_nondefects("TeamNewPipe/NewPipe", gh=lambda _a: page, limit=10)
    kinds = {c.issue_number: c for c in got}
    assert len(got) == 2                       # enhancement-unlinked + question-unmerged-closer
    for c in got:
        assert c.pr_number == 0 and c.files == [] and c.merge_commit_sha == ""
```

`tests/mine/test_gh_miner.py`:
```python
def test_not_a_defect_harvest_emits_sentinel(tmp_path):
    gh = _fake_gh_nondefect(label="enhancement")
    out = str(tmp_path / "ds")
    report = mine(["TeamNewPipe/NewPipe"], out, gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand"], limit=5, not_a_defect_limit=5)
    import json
    from pathlib import Path
    nd = [d for d in Path(out).iterdir() if d.is_dir()
          and json.loads((d / "_oracle" / "oracle.json").read_text())["negative_class"] == "not_a_defect"]
    assert nd and report["not_a_defect"] == 1
    o = json.loads((nd[0] / "_oracle" / "oracle.json").read_text())
    assert o["owning_repo"] == "__NOT_A_DEFECT__" and o["is_answerable"] is False and o["expected_files"] == []
```

- [ ] **Step 2: Run — expect FAIL** (`harvest_nondefects` and the not_a_defect flow don't exist).

- [ ] **Step 3: Implement**
  1. `groundloop/mine/harvest.py` — add after `harvest_repo`:
```python
NOT_A_DEFECT_LABELS = {"enhancement", "question", "duplicate", "wontfix", "invalid",
                       "feature", "feature request", "documentation"}


def harvest_nondefects(slug, *, gh=_default_gh, limit=50):
    """Issues with NO same-repo merged closer AND a not-a-defect label (reuses _QUERY unchanged)."""
    owner, name = slug.split("/", 1)
    out, seen, cursor = [], set(), None
    while len(out) < limit:
        page = gh(_gql_args(owner, name, cursor))
        conn = page["data"]["repository"]["issues"]
        for node in conn["nodes"]:
            if node["number"] in seen:
                continue
            labels = {x["name"].lower() for x in node.get("labels", {}).get("nodes", [])}
            if _pick_closer(node, slug) is None and (labels & NOT_A_DEFECT_LABELS):
                seen.add(node["number"]); out.append(_to_nondefect_candidate(slug, node))
                if len(out) >= limit:
                    break
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return out


def _to_nondefect_candidate(slug, node):
    return Candidate(owning_slug=slug, issue_number=node["number"], issue_title=node.get("title", ""),
                     issue_body=node.get("body") or "", issue_url=node.get("url", ""),
                     labels=tuple(x["name"] for x in node.get("labels", {}).get("nodes", [])),
                     created_at=node.get("createdAt", ""), pr_number=0, merge_commit_sha="",
                     merged_at="", files_total=0, files=[])
```
  2. `groundloop/mine/gh_miner.py` — add `not_a_defect_limit: int = 0`; after the `for cand in harvest_repo(...)` loop (still inside `for slug in slugs`), add a guarded sub-loop:
```python
        if not_a_defect_limit > 0:
            from groundloop.mine.harvest import harvest_nondefects
            nd_kwargs = {"limit": not_a_defect_limit} if gh is None else {"gh": gh, "limit": not_a_defect_limit}
            for cand in harvest_nondefects(slug, **nd_kwargs):
                report["harvested"] += 1
                prose, logs = split_issue_body(cand.issue_body)
                tok = build_owner_tokens(_oracle_for(cand, repo_name, []))
                s_desc, s_summary = scrub(prose, tok), scrub(cand.issue_title, tok)
                s_logs = [scrub(lg["text"], tok) for lg in logs]
                emit_case(out, MinedCase(
                    case_id=_opaque_id(slug, cand.issue_number), summary=s_summary, description=s_desc,
                    logs=[{"kind": lg["kind"], "text": t} for lg, t in zip(logs, s_logs)],
                    owning_repo="__NOT_A_DEFECT__", expected_files=[], required_apis=[],
                    is_answerable=False, negative_class="not_a_defect",
                    provenance={"source_method": "label_harvest", "labels": list(cand.labels)}))
                report["not_a_defect"] += 1
```
  3. CLI: `mn.add_argument("--not-a-defect-limit", type=int, default=0, ...)` + thread through.

- [ ] **Step 4: Run — expect PASS.** Full suite + ruff.

- [ ] **Step 5: Commit**
```bash
git add groundloop/mine/harvest.py groundloop/mine/gh_miner.py groundloop/cli/__init__.py tests/mine/test_harvest.py tests/mine/test_gh_miner.py
git commit -m "feat(mine): not_a_defect label-harvest of non-linked issues (--not-a-defect-limit)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (against the spec + workflow verdicts)

**Spec coverage:** opaque case_id (§1.3-6 BLOCKER) → T1; leak red-test over mined output (§1.3-6) → T5; the four sources (§1.2) → insufficient_signal T7, out_of_fleet T8, coverage_gap T9, not_a_defect T10; typed oracle schema (§1.3) → T6. The §1.3 "fix_patch" leak-closure is **deliberately replaced** by the closed-loop reject (T4) per the verified insufficiency — noted at the top.

**Corrected leak model (verifier verdict OPEN):** the ExoPlaybackException-class leak is closed by T4's closed-loop reject (grounding-over-narrative), not by scrub rules alone; T2 (org/slug) + T3 (.so) close the specific deterministic tells; T5 guards the whole thing over MINED output.

**Emit⇄SP1a contract (verifier verdict PARTIAL):** T6 writes `negative_class`/`held_out_repo` + the per-case catalog that `load_eval_oracle`/`case_catalog` read (cross-layer test in T6); T8 sets `is_answerable=False` for hold-out (fixes the "hardcoded True" gap); positives emit unchanged (back-compat test in T6).

**Known residuals (flagged, not silently dropped):** (1) the OOF per-case-catalog **presence/length side-channel** is latent (no ranker reads catalog length/presence) — follow-up is uniform per-case catalogs; (2) coverage_gap is a temporal **proxy** (exact per-file SHA check deferred — needs a checkout) → flag those slices directional; (3) un-enumerated owner **namespaces** (vs `.so`) remain a residual — the closed-loop reject is the backstop; (4) the closed-loop reject requires an atlas → real full-fleet mining is Tier-1-gated (hermetic tests use the fixture atlas).

**Type consistency:** `_opaque_id` (T1) reused in T10; `MinedCase.{negative_class,held_out_repo,case_catalog}` (T6) written by T8/T10; `report` keys `insufficient_signal/oof/coverage_gap/not_a_defect` introduced in T7 and incremented in T7–T10; `leak_index` (T4) defaults None so T1–T3/T6–T10 hermetic tests (no index) are unaffected.
