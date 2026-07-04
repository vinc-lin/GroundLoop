# Type-2 Substrate Build (parallel `produce` on DeepSeek) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the real `atlas.db` for the 9-repo Type-2 IVI eval fleet by cloning each repo at a pinned SHA and running `gloop produce` **in parallel by repo on the DeepSeek gateway**, then `index` + `doctor` — a long-running, network/API-bound track that has **zero dependency on the eval harness code**, so it can start immediately and not block the timeline.

**Architecture:** A new edge-side `groundloop/build/` package with three thin, dependency-injected drivers — `clone_fleet` (shallow-clone at pinned SHA), `produce_fleet` (bounded-parallel `produce` **subprocesses**, one per repo, each also running the engine's intra-repo module concurrency), and `atlas_build` (orchestrates clone → produce → `gloop index` → `gloop doctor`). Subprocess-per-repo is used (not one shared event loop) because `produce.generate()` owns its own `asyncio.run`; this needs **zero edits to the migrated produce engine**, isolates per-repo failures, and gives no shared-state contention (per-repo `wiki_dir`). Total in-flight DeepSeek requests ≈ `jobs × concurrency`, one documented knob-pair kept under the gateway rate budget. `core/` is untouched; the only existing-code change is the composition root (`cli/__init__.py`).

**Tech Stack:** Python 3.12, `subprocess` + `concurrent.futures.ThreadPoolExecutor`, `argparse` CLI (`gloop`), `tomllib` registry (`corpora/atlas.toml` / `corpora/corpus.toml`), pytest (hermetic via injected runners — no network/LLM in tests). Reuses `groundloop.engines.atlas.registry.load_registry` and the existing `gloop index`/`gloop doctor` commands.

**Canonical design:** [`docs/type2-evaluation.md`](../../type2-evaluation.md) §5 (substrate build) + §8.1 (`build/` package). This plan is eval-harness stage **E1-A** (the substrate track); the miner (E1-B) and eval harness (E1-C) are separate plans.

---

## File Structure

- **Create** `groundloop/build/__init__.py` — package marker.
- **Create** `groundloop/build/clone_fleet.py` — `clone_fleet(repos, *, jobs, runner)` → shallow-clone each fleet repo at a pinned SHA (or HEAD), report the resolved SHA. One responsibility: get the source trees on disk at known SHAs.
- **Create** `groundloop/build/produce_fleet.py` — `produce_fleet(entries, *, jobs, concurrency, force, runner, env)` → run `gloop produce` per repo, up to `jobs` repos in parallel; skip already-built wikis. One responsibility: parallelize wiki generation.
- **Create** `groundloop/build/atlas_build.py` — `build_atlas(...)` orchestrating clone → produce → index → doctor + a `gloop build-atlas` entry. One responsibility: the end-to-end substrate build.
- **Modify** `groundloop/cli/__init__.py` — (a) add `--concurrency` to the `produce` subparser and thread it into `_run_produce`'s config dict; (b) register the `build-atlas` subcommand.
- **Modify** `corpora/corpus.toml` — add the 9 fleet repos (url + sha + path). *(A sibling dir at `/mnt/x/code/corpora`, not in the GroundLoop git repo — edited in place.)*
- **Modify** `corpora/atlas.toml` — add the 9 fleet `[[repo]]` registry entries (`repo_path` + `wiki_dir`).
- **Create** `tests/build/__init__.py`, `tests/build/test_produce_fleet.py`, `tests/build/test_clone_fleet.py`, `tests/build/test_atlas_build.py`, `tests/build/test_cli_produce_concurrency.py` — hermetic tests with injected runners (no network/LLM).

**Testing commands** (from repo root): single test `.venv/bin/python -m pytest tests/build/test_produce_fleet.py -q`; full suite `.venv/bin/python -m pytest -q`; lint `.venv/bin/ruff check groundloop tests` (line length 110).

---

## Task 1: Wire `--concurrency` through the `produce` CLI

`produce` already plumbs `concurrency` into the engine (`BackendConfig.from_cli(..., concurrency=self.config.get('concurrency', 1), ...)` → `documentation_generator.py:486` `asyncio.Semaphore`). The only gap: `_run_produce`'s config dict never sets it, so it is stuck at 1. Add the CLI flag + env override + config wiring.

**Files:**
- Modify: `groundloop/cli/__init__.py` (`_run_produce` config dict ~L111-121; `produce` subparser ~L154-156)
- Test: `tests/build/test_cli_produce_concurrency.py`

- [ ] **Step 1: Write the failing test**

Create `tests/build/__init__.py` (empty) and `tests/build/test_cli_produce_concurrency.py`:

```python
"""The produce CLI must expose --concurrency and feed it into the generator config."""
from __future__ import annotations

import groundloop.cli as cli


def test_produce_concurrency_flag_reaches_config(monkeypatch, tmp_path):
    captured = {}

    class _FakeGen:
        def __init__(self, *, repo_path, output_dir, config, verbose):
            captured["config"] = config

        def generate(self):
            return None

    # Intercept the generator so no real produce/LLM runs.
    monkeypatch.setattr(
        "groundloop.engines.produce.cli.adapters.doc_generator.CLIDocumentationGenerator",
        _FakeGen,
    )

    rc = cli.main(["produce", "--repo", str(tmp_path), "--out", str(tmp_path / "wiki"),
                   "--concurrency", "5"])

    assert rc == 0
    assert captured["config"]["concurrency"] == 5


def test_produce_concurrency_defaults_to_one(monkeypatch, tmp_path):
    captured = {}

    class _FakeGen:
        def __init__(self, *, repo_path, output_dir, config, verbose):
            captured["config"] = config

        def generate(self):
            return None

    monkeypatch.setattr(
        "groundloop.engines.produce.cli.adapters.doc_generator.CLIDocumentationGenerator",
        _FakeGen,
    )

    rc = cli.main(["produce", "--repo", str(tmp_path), "--out", str(tmp_path / "wiki")])

    assert rc == 0
    assert captured["config"]["concurrency"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/build/test_cli_produce_concurrency.py -q`
Expected: FAIL — `argparse` errors on the unknown `--concurrency` flag (SystemExit) for the first test; the second fails with `KeyError: 'concurrency'`.

- [ ] **Step 3: Add the flag to the `produce` subparser**

In `groundloop/cli/__init__.py`, find the `produce` subparser block:

```python
    prod = sub.add_parser("produce", help="generate a CodeWiki for a repo")
    prod.add_argument("--repo", required=True, help="path to the repository to document")
    prod.add_argument("--out", required=True, help="output directory for the generated wiki")
```

Add a `--concurrency` argument after `--out`:

```python
    prod = sub.add_parser("produce", help="generate a CodeWiki for a repo")
    prod.add_argument("--repo", required=True, help="path to the repository to document")
    prod.add_argument("--out", required=True, help="output directory for the generated wiki")
    prod.add_argument("--concurrency", type=int,
                      default=int(__import__("os").environ.get("KLOOP_PRODUCE_CONCURRENCY", "1")),
                      help="modules generated in parallel within this repo (default 1, "
                           "or KLOOP_PRODUCE_CONCURRENCY)")
```

- [ ] **Step 4: Thread it into `_run_produce`'s config dict**

In `_run_produce`, add one line to the `config = { ... }` dict (after `"aws_region": ...`):

```python
        "aws_region": os.environ.get("KLOOP_PRODUCE_AWS_REGION", "us-east-1"),
        "concurrency": getattr(args, "concurrency", 1) or 1,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/build/test_cli_produce_concurrency.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check groundloop tests
git add groundloop/cli/__init__.py tests/build/__init__.py tests/build/test_cli_produce_concurrency.py
git commit -m "feat(build): expose produce --concurrency (intra-repo module parallelism)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `produce_fleet` — bounded-parallel `produce` by repo

The core of the "start produce early" track: run `gloop produce` for each registry entry as an isolated subprocess, up to `jobs` repos concurrently, each with intra-repo `concurrency`. Skip repos whose wiki is already built. A dependency-injected `runner` keeps tests hermetic (no subprocess/LLM).

**Files:**
- Create: `groundloop/build/__init__.py` (empty)
- Create: `groundloop/build/produce_fleet.py`
- Test: `tests/build/test_produce_fleet.py`

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_produce_fleet.py`:

```python
"""produce_fleet runs one produce subprocess per repo, bounded by `jobs`, skipping built wikis."""
from __future__ import annotations

import subprocess
import threading

from groundloop.engines.atlas.registry import RepoEntry
from groundloop.build.produce_fleet import produce_fleet, ProduceResult


def _entry(tmp_path, name):
    return RepoEntry(name=name, repo_path=str(tmp_path / name),
                     wiki_dir=str(tmp_path / "_wiki" / name), entity_map="")


def test_runs_each_repo_and_reports_ok(tmp_path):
    entries = [_entry(tmp_path, "a"), _entry(tmp_path, "b")]
    seen = []

    def fake_runner(entry, *, concurrency, env):
        seen.append((entry.name, concurrency))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

    results = produce_fleet(entries, jobs=2, concurrency=4, runner=fake_runner)

    assert {n for n, _ in seen} == {"a", "b"}
    assert all(c == 4 for _, c in seen)
    assert results["a"] == ProduceResult("a", "ok", 0)
    assert results["b"].status == "ok"


def test_skips_already_built_wiki(tmp_path):
    e = _entry(tmp_path, "a")
    # A wiki is "built" when metadata.json exists.
    (tmp_path / "_wiki" / "a").mkdir(parents=True)
    (tmp_path / "_wiki" / "a" / "metadata.json").write_text("{}")
    called = []

    def fake_runner(entry, *, concurrency, env):
        called.append(entry.name)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    results = produce_fleet([e], jobs=1, runner=fake_runner)

    assert called == []                      # runner not invoked
    assert results["a"].status == "skipped"


def test_force_reruns_built_wiki(tmp_path):
    e = _entry(tmp_path, "a")
    (tmp_path / "_wiki" / "a").mkdir(parents=True)
    (tmp_path / "_wiki" / "a" / "metadata.json").write_text("{}")
    called = []

    def fake_runner(entry, *, concurrency, env):
        called.append(entry.name)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    produce_fleet([e], jobs=1, force=True, runner=fake_runner)

    assert called == ["a"]


def test_failure_is_isolated_not_fatal(tmp_path):
    entries = [_entry(tmp_path, "good"), _entry(tmp_path, "bad")]

    def fake_runner(entry, *, concurrency, env):
        if entry.name == "bad":
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    results = produce_fleet(entries, jobs=2, runner=fake_runner)

    assert results["good"].status == "ok"
    assert results["bad"].status == "failed"
    assert results["bad"].returncode == 1
    assert "boom" in results["bad"].detail


def test_respects_jobs_ceiling(tmp_path):
    entries = [_entry(tmp_path, f"r{i}") for i in range(6)]
    lock = threading.Lock()
    state = {"live": 0, "peak": 0}
    gate = threading.Event()

    def fake_runner(entry, *, concurrency, env):
        with lock:
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
        gate.wait(timeout=1.0)          # hold the slot so overlap is observable
        with lock:
            state["live"] -= 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    import threading as _t
    _t.Thread(target=lambda: (gate.wait(0.2), gate.set())).start()
    produce_fleet(entries, jobs=2, runner=fake_runner)

    assert state["peak"] <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/build/test_produce_fleet.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'groundloop.build'`.

- [ ] **Step 3: Write the implementation**

Create `groundloop/build/__init__.py` (empty file). Create `groundloop/build/produce_fleet.py`:

```python
"""Run `gloop produce` for a whole registry, bounded-parallel by repo.

Each repo's produce is an isolated subprocess (produce owns its own asyncio.run),
so failures are isolated and there is no shared-state contention. Total in-flight
DeepSeek requests ~= jobs * concurrency.
"""
from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from groundloop.engines.atlas.registry import RepoEntry


@dataclass(frozen=True)
class ProduceResult:
    name: str
    status: str            # "ok" | "skipped" | "failed"
    returncode: int
    detail: str = ""


def _wiki_ready(wiki_dir: str) -> bool:
    """produce always writes metadata.json on success (its reliable deliverable)."""
    return (Path(wiki_dir) / "metadata.json").is_file()


def _default_runner(entry: RepoEntry, *, concurrency: int,
                    env: dict) -> subprocess.CompletedProcess:
    """Run `gloop produce` for one repo as an isolated subprocess on DeepSeek."""
    Path(entry.wiki_dir).mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "groundloop.cli", "produce",
         "--repo", entry.repo_path, "--out", entry.wiki_dir,
         "--concurrency", str(concurrency)],
        capture_output=True, text=True, env=env,
    )


def produce_fleet(
    entries: Sequence[RepoEntry],
    *,
    jobs: int = 3,
    concurrency: int = 4,
    force: bool = False,
    runner: Callable[..., subprocess.CompletedProcess] = _default_runner,
    env: Optional[dict] = None,
) -> dict[str, ProduceResult]:
    """Produce a wiki for each entry, up to `jobs` repos in parallel.

    `concurrency` is passed through to each repo's produce for intra-repo module
    parallelism, so total in-flight LLM requests ~= jobs * concurrency. Repos whose
    wiki is already built are skipped unless `force`.
    """
    run_env = dict(os.environ if env is None else env)
    results: dict[str, ProduceResult] = {}
    todo: list[RepoEntry] = []
    for e in entries:
        if not force and _wiki_ready(e.wiki_dir):
            results[e.name] = ProduceResult(e.name, "skipped", 0, "wiki already built")
        else:
            todo.append(e)

    def _one(entry: RepoEntry) -> ProduceResult:
        try:
            cp = runner(entry, concurrency=concurrency, env=run_env)
        except Exception as exc:  # noqa: BLE001 — report, never sink the fleet
            return ProduceResult(entry.name, "failed", -1, f"{type(exc).__name__}: {exc}")
        if cp.returncode == 0:
            return ProduceResult(entry.name, "ok", 0)
        return ProduceResult(entry.name, "failed", cp.returncode, (cp.stderr or "")[-500:])

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            futures = {pool.submit(_one, e): e for e in todo}
            for fut in as_completed(futures):
                res = fut.result()
                results[res.name] = res
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/build/test_produce_fleet.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check groundloop tests
git add groundloop/build/__init__.py groundloop/build/produce_fleet.py tests/build/test_produce_fleet.py
git commit -m "feat(build): produce_fleet — bounded-parallel produce by repo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `clone_fleet` — shallow-clone the fleet at pinned SHAs

Get the 9 source trees on disk at known SHAs so `produce`/`index` have code to read. Shallow (`--depth 1`) at the pinned SHA, matching the `corpus.toml` convention. Dependency-injected git runner keeps tests hermetic (no network).

**Files:**
- Create: `groundloop/build/clone_fleet.py`
- Test: `tests/build/test_clone_fleet.py`

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_clone_fleet.py`:

```python
"""clone_fleet fetches each repo at its pinned SHA (or reports one already present)."""
from __future__ import annotations

from pathlib import Path

from groundloop.build.clone_fleet import clone_fleet, FleetRepo, CloneResult


def _repo(tmp_path, name, sha="cafe1234"):
    return FleetRepo(name=name, url=f"https://example.test/{name}.git",
                     sha=sha, dest=str(tmp_path / name))


def test_clones_missing_repo_and_reports_sha(tmp_path):
    r = _repo(tmp_path, "a", sha="deadbeef")
    calls = []

    def fake_git(repo):
        calls.append(repo.name)
        return CloneResult(repo.name, "cloned", repo.sha)

    results = clone_fleet([r], jobs=1, runner=fake_git)

    assert calls == ["a"]
    assert results["a"].status == "cloned"
    assert results["a"].sha == "deadbeef"


def test_present_repo_is_not_recloned(tmp_path):
    r = _repo(tmp_path, "a")

    def fake_git(repo):
        # runner decides present vs cloned; here simulate "already present"
        return CloneResult(repo.name, "present", "existingsha")

    results = clone_fleet([r], jobs=1, runner=fake_git)
    assert results["a"].status == "present"
    assert results["a"].sha == "existingsha"


def test_clone_failure_is_isolated(tmp_path):
    good, bad = _repo(tmp_path, "good"), _repo(tmp_path, "bad")

    def fake_git(repo):
        if repo.name == "bad":
            return CloneResult(repo.name, "failed", "", "network down")
        return CloneResult(repo.name, "cloned", repo.sha)

    results = clone_fleet([good, bad], jobs=2, runner=fake_git)
    assert results["good"].status == "cloned"
    assert results["bad"].status == "failed"
    assert "network down" in results["bad"].detail


def test_default_runner_reports_present_for_existing_checkout(tmp_path):
    # A dir with a .git subdir is treated as already present (no network).
    dest = tmp_path / "a"
    (dest / ".git").mkdir(parents=True)
    from groundloop.build.clone_fleet import _default_git_runner
    r = FleetRepo(name="a", url="https://example.test/a.git", sha="", dest=str(dest))
    # Should not raise and should classify as present (rev-parse may fail on a bare
    # .git skeleton, but status must be 'present', never 'cloned').
    res = _default_git_runner(r)
    assert res.status == "present"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/build/test_clone_fleet.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'groundloop.build.clone_fleet'`.

- [ ] **Step 3: Write the implementation**

Create `groundloop/build/clone_fleet.py`:

```python
"""Shallow-clone the eval fleet at pinned SHAs (produce/index need the tree, not history).

Mining fetches issue bodies online via gh; local history is not needed, so --depth 1
at the pinned SHA is sufficient and matches corpora/corpus.toml.
"""
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class FleetRepo:
    name: str
    url: str
    sha: str      # pinned SHA to check out; "" = default HEAD
    dest: str     # local checkout path


@dataclass(frozen=True)
class CloneResult:
    name: str
    status: str        # "cloned" | "present" | "failed"
    sha: str = ""
    detail: str = ""


def _git(args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _default_git_runner(repo: FleetRepo) -> CloneResult:
    """Real git: skip if a checkout already exists, else shallow-clone at the pinned SHA."""
    dest = Path(repo.dest)
    if (dest / ".git").exists():
        head = _git(["rev-parse", "HEAD"], cwd=str(dest))
        return CloneResult(repo.name, "present", head.stdout.strip())
    dest.parent.mkdir(parents=True, exist_ok=True)
    cl = _git(["clone", "--depth", "1", repo.url, str(dest)])
    if cl.returncode != 0:
        return CloneResult(repo.name, "failed", "", (cl.stderr or "")[-500:])
    if repo.sha:
        # Shallow clones may need an explicit fetch to land an exact SHA.
        fetch = _git(["fetch", "--depth", "1", "origin", repo.sha], cwd=str(dest))
        if fetch.returncode != 0:
            return CloneResult(repo.name, "failed", "", (fetch.stderr or "")[-500:])
        co = _git(["checkout", repo.sha], cwd=str(dest))
        if co.returncode != 0:
            return CloneResult(repo.name, "failed", "", (co.stderr or "")[-500:])
    head = _git(["rev-parse", "HEAD"], cwd=str(dest))
    return CloneResult(repo.name, "cloned", head.stdout.strip())


def clone_fleet(
    repos: Sequence[FleetRepo],
    *,
    jobs: int = 4,
    runner: Callable[[FleetRepo], CloneResult] = _default_git_runner,
) -> dict[str, CloneResult]:
    """Clone/verify each fleet repo, up to `jobs` in parallel. Failures are isolated."""
    results: dict[str, CloneResult] = {}

    def _one(repo: FleetRepo) -> CloneResult:
        try:
            return runner(repo)
        except Exception as exc:  # noqa: BLE001 — report, never sink the fleet
            return CloneResult(repo.name, "failed", "", f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(_one, r): r for r in repos}
        for fut in as_completed(futures):
            res = fut.result()
            results[res.name] = res
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/build/test_clone_fleet.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check groundloop tests
git add groundloop/build/clone_fleet.py tests/build/test_clone_fleet.py
git commit -m "feat(build): clone_fleet — shallow-clone eval fleet at pinned SHAs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Register the 9-repo fleet (`corpus.toml` + `atlas.toml`)

Define the fleet so `clone_fleet`/`produce_fleet`/`index` can consume it. These files live in the sibling `corpora/` dir (not the GroundLoop git repo), so this task edits files in place — there is no commit for the registry edits.

> **SHA pinning:** the SHAs below are **placeholders** (`PIN_AT_CLONE`). Pin them by cloning once and recording HEAD: after Task 5's first `build-atlas` run (or a manual `clone_fleet`), run `git -C /mnt/x/code/corpora/<name> rev-parse HEAD` for each repo and paste the value into `sha`. The recorded SHA becomes `owning_repo_sha` for the miner (plan E1-B).

**Files:**
- Modify: `/mnt/x/code/corpora/corpus.toml`
- Modify: `/mnt/x/code/corpora/atlas.toml`

- [ ] **Step 1: Add the 9 fleet repos to `corpus.toml`**

Append these `[[repo]]` blocks to `/mnt/x/code/corpora/corpus.toml` (keep the existing 3; `android-gpuimage-plus` is already present — do not duplicate it):

```toml
# ---- Type-2 IVI eval fleet (docs/type2-evaluation.md §3.1) ----
[[repo]]
name = "osmand"
url = "https://github.com/osmandapp/OsmAnd.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/osmand"
languages = ["java", "kotlin"]
role = "navigation — net.osmand; mine (filter to linked:pr; large support-forum tracker)"

[[repo]]
name = "organicmaps"
url = "https://github.com/organicmaps/organicmaps.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/organicmaps"
languages = ["cpp", "java", "kotlin"]
role = "navigation — app.organicmaps; strong issue<->PR linkage; C++ core + JVM app layer"

[[repo]]
name = "antennapod"
url = "https://github.com/AntennaPod/AntennaPod.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/antennapod"
languages = ["java", "kotlin"]
role = "media/audio — de.danoeh.antennapod; disciplined 'Fixes #' linkage"

[[repo]]
name = "newpipe"
url = "https://github.com/TeamNewPipe/NewPipe.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/newpipe"
languages = ["java", "kotlin"]
role = "media/audio — org.schabi.newpipe; built-in crash reporter (rich stack traces)"

[[repo]]
name = "oboe"
url = "https://github.com/google/oboe.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/oboe"
languages = ["cpp"]
role = "media/audio (native) — no JVM namespace; .so-keyed matching control (liboboe.so)"

[[repo]]
name = "cameraview"
url = "https://github.com/natario1/CameraView.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/cameraview"
languages = ["java", "kotlin"]
role = "camera/graphics — com.otaliastudios.cameraview; frozen/legacy but mineable"

[[repo]]
name = "dlt-daemon"
url = "https://github.com/COVESA/dlt-daemon.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/dlt-daemon"
languages = ["c"]
role = "automotive (native) — COVESA diagnostic log/trace daemon; genuine issue<->PR workflow"

[[repo]]
name = "media3"
url = "https://github.com/androidx/media.git"
sha = "PIN_AT_CLONE"
path = "~/code/corpora/media3"
languages = ["java", "kotlin"]
role = "media/audio — androidx.media3 (absorbed ExoPlayer); Gerrit-mirror, commit-trailer provenance"
```

- [ ] **Step 2: Add the 9 registry entries to `atlas.toml`**

Replace the (mostly commented-out) `[[repo]]` list in `/mnt/x/code/corpora/atlas.toml` with the full fleet (keep the header comment):

```toml
[[repo]]
name = "android-gpuimage-plus"
repo_path = "/mnt/x/code/corpora/android-gpuimage-plus"
wiki_dir = "/mnt/x/code/corpora/_wiki/android-gpuimage-plus"

[[repo]]
name = "osmand"
repo_path = "/mnt/x/code/corpora/osmand"
wiki_dir = "/mnt/x/code/corpora/_wiki/osmand"

[[repo]]
name = "organicmaps"
repo_path = "/mnt/x/code/corpora/organicmaps"
wiki_dir = "/mnt/x/code/corpora/_wiki/organicmaps"

[[repo]]
name = "antennapod"
repo_path = "/mnt/x/code/corpora/antennapod"
wiki_dir = "/mnt/x/code/corpora/_wiki/antennapod"

[[repo]]
name = "newpipe"
repo_path = "/mnt/x/code/corpora/newpipe"
wiki_dir = "/mnt/x/code/corpora/_wiki/newpipe"

[[repo]]
name = "oboe"
repo_path = "/mnt/x/code/corpora/oboe"
wiki_dir = "/mnt/x/code/corpora/_wiki/oboe"

[[repo]]
name = "cameraview"
repo_path = "/mnt/x/code/corpora/cameraview"
wiki_dir = "/mnt/x/code/corpora/_wiki/cameraview"

[[repo]]
name = "dlt-daemon"
repo_path = "/mnt/x/code/corpora/dlt-daemon"
wiki_dir = "/mnt/x/code/corpora/_wiki/dlt-daemon"

[[repo]]
name = "media3"
repo_path = "/mnt/x/code/corpora/media3"
wiki_dir = "/mnt/x/code/corpora/_wiki/media3"
```

- [ ] **Step 3: Verify the registry loads**

Run: `.venv/bin/python -c "from groundloop.engines.atlas.registry import load_registry; e=load_registry('/mnt/x/code/corpora/atlas.toml'); print(len(e), [x.name for x in e])"`
Expected: `9 ['android-gpuimage-plus', 'osmand', 'organicmaps', 'antennapod', 'newpipe', 'oboe', 'cameraview', 'dlt-daemon', 'media3']`

*(No git commit — these files are outside the GroundLoop repo.)*

---

## Task 5: `atlas_build` orchestrator + `gloop build-atlas`

Tie it together: clone → produce (parallel) → `gloop index` → `gloop doctor`, resumable and injectable. Reuses the existing `gloop index`/`doctor` subcommands by subprocess (so the whole wired Settings/Store/GatewayEmbedder path is reused unchanged).

**Files:**
- Create: `groundloop/build/atlas_build.py`
- Modify: `groundloop/cli/__init__.py` (register `build-atlas` subcommand + dispatch)
- Test: `tests/build/test_atlas_build.py`

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_atlas_build.py`:

```python
"""build_atlas orchestrates clone -> produce -> index -> doctor with injected steps."""
from __future__ import annotations

from groundloop.build.atlas_build import build_atlas, BuildReport


def _fake_toml(tmp_path):
    p = tmp_path / "atlas.toml"
    p.write_text(
        '[[repo]]\nname = "a"\nrepo_path = "%s/a"\nwiki_dir = "%s/_wiki/a"\n'
        % (tmp_path, tmp_path)
    )
    return str(p)


def test_happy_path_runs_all_steps_in_order(tmp_path):
    order = []

    def fake_clone(entries, **kw):
        order.append("clone")
        return {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()}

    def fake_produce(entries, **kw):
        order.append("produce")
        return {"a": type("R", (), {"status": "ok", "name": "a", "detail": ""})()}

    def fake_index(registry):
        order.append(("index", registry))
        return 0

    def fake_doctor():
        order.append("doctor")
        return 0

    report = build_atlas(
        _fake_toml(tmp_path), jobs=2, concurrency=4,
        clone_fn=fake_clone, produce_fn=fake_produce,
        index_fn=fake_index, doctor_fn=fake_doctor,
    )

    assert [o if isinstance(o, str) else o[0] for o in order] == \
        ["clone", "produce", "index", "doctor"]
    assert isinstance(report, BuildReport)
    assert report.ok is True


def test_produce_failure_stops_before_index(tmp_path):
    calls = []

    def fake_clone(entries, **kw):
        return {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()}

    def fake_produce(entries, **kw):
        return {"a": type("R", (), {"status": "failed", "name": "a", "detail": "boom"})()}

    def fake_index(registry):
        calls.append("index")
        return 0

    report = build_atlas(
        _fake_toml(tmp_path),
        clone_fn=fake_clone, produce_fn=fake_produce,
        index_fn=fake_index, doctor_fn=lambda: 0,
    )

    assert calls == []                 # index never ran
    assert report.ok is False
    assert "produce" in report.failed_stage


def test_index_nonzero_marks_build_failed(tmp_path):
    report = build_atlas(
        _fake_toml(tmp_path),
        clone_fn=lambda e, **k: {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()},
        produce_fn=lambda e, **k: {"a": type("R", (), {"status": "ok", "name": "a", "detail": ""})()},
        index_fn=lambda registry: 3,
        doctor_fn=lambda: 0,
    )
    assert report.ok is False
    assert report.failed_stage == "index"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/build/test_atlas_build.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'groundloop.build.atlas_build'`.

- [ ] **Step 3: Write the implementation**

Create `groundloop/build/atlas_build.py`:

```python
"""End-to-end substrate build: clone -> produce (parallel) -> index -> doctor.

Each stage is injectable for hermetic tests; the defaults call the real drivers
and reuse the existing `gloop index` / `gloop doctor` subcommands by subprocess.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from groundloop.engines.atlas.registry import RepoEntry, load_registry
from groundloop.build.clone_fleet import FleetRepo, clone_fleet
from groundloop.build.produce_fleet import produce_fleet


@dataclass
class BuildReport:
    ok: bool
    failed_stage: str = ""
    clone: dict = field(default_factory=dict)
    produce: dict = field(default_factory=dict)
    index_rc: Optional[int] = None
    doctor_rc: Optional[int] = None


def _entries_to_fleet(entries: list[RepoEntry],
                      corpus: Optional[dict] = None) -> list[FleetRepo]:
    """Map registry entries to clone targets. `corpus` maps name -> (url, sha)."""
    corpus = corpus or {}
    out: list[FleetRepo] = []
    for e in entries:
        url, sha = corpus.get(e.name, ("", ""))
        out.append(FleetRepo(name=e.name, url=url, sha=sha, dest=e.repo_path))
    return out


def _default_index(registry: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "groundloop.cli", "index", "--registry", registry]
    ).returncode


def _default_doctor() -> int:
    return subprocess.run([sys.executable, "-m", "groundloop.cli", "doctor"]).returncode


def build_atlas(
    registry_path: str,
    *,
    jobs: int = 3,
    concurrency: int = 4,
    force: bool = False,
    corpus: Optional[dict] = None,
    clone_fn: Callable = clone_fleet,
    produce_fn: Callable = produce_fleet,
    index_fn: Callable[[str], int] = _default_index,
    doctor_fn: Callable[[], int] = _default_doctor,
) -> BuildReport:
    """Clone -> produce -> index -> doctor. Stops at the first failed stage."""
    entries = load_registry(registry_path)

    clone_res = clone_fn(_entries_to_fleet(entries, corpus), jobs=jobs)
    if any(getattr(r, "status", "") == "failed" for r in clone_res.values()):
        return BuildReport(ok=False, failed_stage="clone", clone=clone_res)

    produce_res = produce_fn(entries, jobs=jobs, concurrency=concurrency, force=force)
    if any(getattr(r, "status", "") == "failed" for r in produce_res.values()):
        return BuildReport(ok=False, failed_stage="produce",
                           clone=clone_res, produce=produce_res)

    index_rc = index_fn(registry_path)
    if index_rc != 0:
        return BuildReport(ok=False, failed_stage="index", clone=clone_res,
                           produce=produce_res, index_rc=index_rc)

    doctor_rc = doctor_fn()
    return BuildReport(ok=(doctor_rc == 0),
                       failed_stage="" if doctor_rc == 0 else "doctor",
                       clone=clone_res, produce=produce_res,
                       index_rc=index_rc, doctor_rc=doctor_rc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/build/test_atlas_build.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Register the `build-atlas` subcommand**

In `groundloop/cli/__init__.py`, add a subparser next to the others (after the `produce` block):

```python
    ba = sub.add_parser("build-atlas", help="clone fleet + produce (parallel) + index + doctor")
    ba.add_argument("--registry", default="", help="path to atlas.toml (overrides KLOOP_REGISTRY)")
    ba.add_argument("--jobs", type=int, default=3, help="repos produced in parallel (default 3)")
    ba.add_argument("--concurrency", type=int, default=4,
                    help="modules per repo in parallel (default 4); total in-flight ~= jobs*concurrency")
    ba.add_argument("--force", action="store_true", help="re-produce even if a wiki exists")
```

Add a `_run_build_atlas` function:

```python
def _run_build_atlas(args) -> int:
    from groundloop.config.settings import Settings
    from groundloop.build.atlas_build import build_atlas

    settings = Settings.load()
    registry = args.registry or settings.registry
    if not registry:
        print("gloop build-atlas: --registry is required (or set KLOOP_REGISTRY)")
        return 2
    report = build_atlas(registry, jobs=args.jobs, concurrency=args.concurrency,
                         force=args.force)
    for name, r in report.produce.items():
        print(f"produce {name}: {getattr(r, 'status', '?')}")
    print(f"index rc={report.index_rc}  doctor rc={report.doctor_rc}")
    if not report.ok:
        print(f"build-atlas FAILED at stage: {report.failed_stage}")
        return 1
    print("build-atlas OK")
    return 0
```

And in `main`, add the dispatch (next to the other `if args.cmd == ...` blocks):

```python
    if args.cmd == "build-atlas":
        return _run_build_atlas(args)
```

- [ ] **Step 6: Verify the CLI wires up (help text, no execution)**

Run: `.venv/bin/gloop build-atlas --help`
Expected: usage text listing `--registry`, `--jobs`, `--concurrency`, `--force` (exit 0).

- [ ] **Step 7: Full suite + lint + commit**

Run: `.venv/bin/python -m pytest -q` — Expected: all green (including the new `tests/build/`).
Run: `.venv/bin/ruff check groundloop tests` — Expected: clean.

```bash
git add groundloop/build/atlas_build.py groundloop/cli/__init__.py tests/build/test_atlas_build.py
git commit -m "feat(build): build_atlas orchestrator + gloop build-atlas

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Kick off the real substrate build (the long-running, out-of-band step)

This is the actual "start early so it does not block" step — run once the code above is green. It is **live** (network + DeepSeek + bge-m3), so it is not a test; run it in a terminal (or `run_in_background`) and let it proceed while plans E1-B (miner) and E1-C (eval harness) are built.

- [ ] **Step 1: Source the live env + confirm the gateways are up**

```bash
cd /mnt/x/code/GroundLoop
set -a; . ./.env; set +a
# bge-m3 embed gate (prints 200 when up) — see docs/type2-eval-setup.md
curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 "${KLOOP_EMBED_BASE_URL%/}/embeddings" \
  -H "Authorization: Bearer $KLOOP_EMBED_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","input":"hi"}'
```
Expected: `200`. (DeepSeek/produce readiness per `docs/type2-eval-setup.md`.)

- [ ] **Step 2: Clone the fleet + pin SHAs (records `owning_repo_sha` for the miner)**

```bash
.venv/bin/python -c "
from groundloop.engines.atlas.registry import load_registry
from groundloop.build.atlas_build import _entries_to_fleet
from groundloop.build.clone_fleet import clone_fleet
e = load_registry('/mnt/x/code/corpora/atlas.toml')
res = clone_fleet(_entries_to_fleet(e), jobs=4)
for n, r in res.items(): print(n, r.status, r.sha)
"
```
Then paste each printed SHA into the matching `sha = \"PIN_AT_CLONE\"` in `corpus.toml` (Task 4).

- [ ] **Step 3: Run the parallel produce + index + doctor (long-running; background it)**

```bash
set -a; . ./.env; set +a
.venv/bin/gloop build-atlas --registry /mnt/x/code/corpora/atlas.toml --jobs 3 --concurrency 4
```
Expected: `produce <name>: ok` per repo, then `index rc=0  doctor rc=0`, then `build-atlas OK`. Watch cost/latency; tune `--jobs`/`--concurrency` down if the gateway rate-limits (note the working value in `docs/type2-eval-setup.md`). Large repos (`organicmaps`, `osmand`, `media3`) dominate wall-clock — this is exactly why the track starts early.

- [ ] **Step 4: Sanity-check the built atlas**

```bash
.venv/bin/gloop doctor --atlas-db "${KLOOP_ATLAS_DB:-$HOME/.groundloop/atlas.db}"
```
Expected: `repos: 9`, `units: > 0` per repo, embed gateway OK, CBM OK. This atlas.db is the Type-2 substrate consumed by the eval harness (plan E1-C).

---

## Self-Review

**Spec coverage (against `type2-evaluation.md` §5 / §8.1):** parallel-by-repo produce on DeepSeek (Tasks 1–2, 5) ✓; subprocess isolation + `jobs × concurrency` ceiling (Task 2) ✓; resumable/skip-fresh (Task 2 `_wiki_ready`, `--force`) ✓; clone at pinned SHA feeding `owning_repo_sha` (Tasks 3–4, 6) ✓; index + doctor reuse (Task 5) ✓; `manifest.json` stamping of pins/embed-model — **deferred to plan E1-C** (the harness owns provenance emission; noted here, not silently dropped). The `bge-m3` reuse contract is enforced by the existing `gloop index`/`doctor` path (unchanged), not re-implemented here.

**Placeholder scan:** the only intentional placeholder is `sha = "PIN_AT_CLONE"` in Task 4, explicitly resolved by Task 6 Step 2 (clone → `rev-parse` → paste). No `TODO`/"handle errors"/"similar to" placeholders; every code step is complete.

**Type consistency:** `RepoEntry(name, repo_path, wiki_dir, entity_map)` (from `load_registry`) used consistently; `ProduceResult(name, status, returncode, detail)` and `CloneResult(name, status, sha, detail)` and `FleetRepo(name, url, sha, dest)` and `BuildReport(ok, failed_stage, clone, produce, index_rc, doctor_rc)` are each defined once and referenced with matching fields; `build_atlas`'s injected `clone_fn`/`produce_fn`/`index_fn(registry)->int`/`doctor_fn()->int` signatures match the defaults `clone_fleet`/`produce_fleet`/`_default_index`/`_default_doctor`.

**Note on `_entries_to_fleet` + `corpus`:** Task 5's `build_atlas` accepts an optional `corpus` map (name → (url, sha)); Task 6 Step 2 calls `clone_fleet` directly for the initial pinning pass. A follow-up nicety (not required for E1-A) is to load `corpus.toml` into that `corpus` map so `gloop build-atlas` can clone from scratch on a fresh machine; today it assumes the fleet is already cloned (Task 6 Step 2) or present.
