"""Hermetic tests for _resolve_repo_head extracted from lore/server.py."""
from __future__ import annotations

import subprocess

from groundloop.engines.lore.repo_head import _resolve_repo_head


def test_returns_head_sha_of_tmp_git_repo(tmp_path):
    """Should return the HEAD sha of a real git repo."""
    subprocess.check_call(["git", "init", str(tmp_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.check_call(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
        },
    )
    sha = _resolve_repo_head(str(tmp_path), {})
    assert sha is not None
    assert len(sha) == 40
    # Should be a valid hex SHA
    int(sha, 16)


def test_returns_none_for_non_repo(tmp_path):
    """Should return None (sentinel) for a directory that is not a git repo."""
    result = _resolve_repo_head(str(tmp_path), {})
    assert result is None


def test_returns_none_when_repo_path_is_none():
    """Should return None when repo_path is not provided."""
    result = _resolve_repo_head(None, {})
    assert result is None


def test_env_override_wins(tmp_path):
    """KNOWLEDGELOOP_REPO_HEAD env var overrides git HEAD lookup."""
    result = _resolve_repo_head(str(tmp_path), {"KNOWLEDGELOOP_REPO_HEAD": "abc123"})
    assert result == "abc123"
