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
