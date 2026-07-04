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
