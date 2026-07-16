"""Dev-Labs @base=fix^ materializer for the fix-eval runner.

Check out the commit BEFORE a case's fix SHA (`sha^` — the standard "buggy state" premise) into a
fresh per-case work-tree, so the fix stage runs against the REAL buggy source and becomes gradeable.
The fix SHA rides in the case's hidden oracle (`_oracle/oracle.json:owning_repo_sha`) and is used ONLY
to build this downstream fix substrate — the matcher has already run and never sees it
(docs/fix-loop.md §0, §3). Oracle-side substrate construction, never a matcher input.

Fail-safe: ANY failure returns None, so the case stays ungradeable exactly as before.

Recipe: an isolated copy of the local clone (source untouched) + `git checkout sha^`. Shallow clones
(the fleet corpora are 1-commit shallow clones) lack the fix SHA's parent locally, so a `git fetch
--depth 2 origin <sha>` lands `sha` + its parent first. NOTE this reuses full history rather than the
§3 history-scrub (archive -> fresh single-commit init); the fix engine reads files (not `git log`), so
no fix leaks through `propose`. A strict scrub is a follow-up.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

GitRunner = Callable[..., subprocess.CompletedProcess]


def _default_git(args: Sequence[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Mirror groundloop.build.clone_fleet._git (args, cwd=None) so a test can inject a fake runner."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def checkout_base(repo_source: str, sha: str, dest: str, *, git: GitRunner = _default_git) -> str | None:
    """Materialize `sha^` from the local clone `repo_source` into `dest`. Returns `dest` on success,
    None on any failure (fail-safe)."""
    src = Path(repo_source)
    dst = Path(dest)
    if not sha or not src.is_dir():
        return None
    parent = f"{sha}^"
    try:
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)                              # isolated copy; source clone untouched
        # Ensure the fix SHA's PARENT OBJECT is present (shallow clones lack it -> depth-2 fetch).
        if git(["cat-file", "-e", parent], cwd=str(dst)).returncode != 0:
            if git(["fetch", "--depth", "2", "origin", sha], cwd=str(dst)).returncode != 0:
                shutil.rmtree(dst, ignore_errors=True)
                return None
            if git(["cat-file", "-e", parent], cwd=str(dst)).returncode != 0:
                shutil.rmtree(dst, ignore_errors=True)
                return None
        if git(["checkout", "--detach", "-q", parent], cwd=str(dst)).returncode != 0:
            shutil.rmtree(dst, ignore_errors=True)
            return None
        return str(dst)
    except Exception:                                          # noqa: BLE001 — never raise into the loop
        shutil.rmtree(dst, ignore_errors=True)
        return None
