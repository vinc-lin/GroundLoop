"""Extract of _resolve_repo_head from knowledgeloop/lore/server.py (no FastMCP dependency)."""
from __future__ import annotations

import subprocess
from typing import Mapping, Optional

from groundloop.engines._envcompat import getenv_compat


def _resolve_repo_head(repo_path: Optional[str],
                       environ: Mapping[str, str]) -> Optional[str]:
    """The freshness anchor: HEAD SHA of the repo CBM indexes.

    REPO_MEMORY_REPO_HEAD wins (escape hatch / detached checkouts); otherwise
    `git rev-parse HEAD` of repo_path. Returns None if unset and repo_path is
    not a git repo (or git is unavailable), so freshness degrades to
    'unverified' rather than raising.
    """
    override = getenv_compat("KNOWLEDGELOOP_REPO_HEAD", "REPO_MEMORY_REPO_HEAD", environ=environ)
    if override:
        return override
    if not repo_path:
        return None
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_path, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return out.decode().strip() or None
