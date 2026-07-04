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


def test_runner_exception_is_isolated(tmp_path):
    e = _entry(tmp_path, "x")

    def raising_runner(entry, *, concurrency, env):
        raise OSError("cannot spawn")

    results = produce_fleet([e], jobs=1, runner=raising_runner)

    assert results["x"].status == "failed"
    assert results["x"].returncode == -1
    assert "OSError" in results["x"].detail


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

    threading.Thread(target=lambda: (gate.wait(0.2), gate.set())).start()
    produce_fleet(entries, jobs=2, runner=fake_runner)

    assert state["peak"] <= 2
    assert state["peak"] == 2
