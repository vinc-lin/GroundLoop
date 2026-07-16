"""Run `gloop produce` for a whole registry, bounded-parallel by repo.

Each repo's produce is an isolated subprocess (produce owns its own asyncio.run),
so failures are isolated and there is no shared-state contention. Total in-flight
DeepSeek requests ~= jobs * concurrency.
"""
from __future__ import annotations

import json
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
    """True only if metadata.json lists at least one generated file.

    An EMPTY produce run also writes metadata.json ({"files_generated": []}), so mere
    presence over-counts the empty fleet wikis as "built" and wrongly skips them. Require a
    non-empty files_generated list; treat a missing/unreadable/malformed metadata.json as
    not-ready (never raises)."""
    meta = Path(wiki_dir) / "metadata.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get("files_generated"))


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
