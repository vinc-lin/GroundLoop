"""Hermetic tests for engines/lore/deploy.py — resolve_launch_spec only.

Does NOT start CBM; purely validates that resolve_launch_spec returns the
expected LaunchSpec shape given a controlled environ dict.
"""

from __future__ import annotations

import pytest


def test_resolve_launch_spec_default_dev_profile():
    """Default (no env overrides) produces a LaunchSpec with the installed binary."""
    from groundloop.engines.lore.deploy import (
        resolve_launch_spec,
        DEFAULT_CBM_VERSION,
        LaunchSpec,
    )

    spec = resolve_launch_spec(environ={})
    assert isinstance(spec, LaunchSpec)
    # The installed binary, not uvx
    assert spec.command[0] != "uvx", "default command must use installed binary, not uvx"
    assert isinstance(spec.command, list) and len(spec.command) >= 1
    assert spec.env == {}  # dev profile has no extra env by default
    assert DEFAULT_CBM_VERSION == "0.8.1"


def test_resolve_launch_spec_command_override():
    """KNOWLEDGELOOP_CBM_COMMAND env override replaces the default command."""
    from groundloop.engines.lore.deploy import resolve_launch_spec

    spec = resolve_launch_spec(environ={"KNOWLEDGELOOP_CBM_COMMAND": "/opt/cbm/bin/cbm --debug"})
    assert spec.command == ["/opt/cbm/bin/cbm", "--debug"]


def test_resolve_launch_spec_version_in_spec():
    """DEFAULT_CBM_VERSION is 0.8.1 and no uvx network call is made."""
    from groundloop.engines.lore.deploy import resolve_launch_spec, DEFAULT_CBM_VERSION

    assert DEFAULT_CBM_VERSION == "0.8.1"
    spec = resolve_launch_spec(environ={})
    # installed binary: no @version suffix in argv
    joined = " ".join(spec.command)
    assert "@" not in joined, f"command must not use uvx @version syntax; got {spec.command!r}"


def test_resolve_launch_spec_cbm_knobs_forwarded():
    """CBM_* env knobs are forwarded to the launch spec env."""
    from groundloop.engines.lore.deploy import resolve_launch_spec

    spec = resolve_launch_spec(environ={"CBM_LOG_LEVEL": "debug", "CBM_WORKERS": "4"})
    assert spec.env.get("CBM_LOG_LEVEL") == "debug"
    assert spec.env.get("CBM_WORKERS") == "4"


def test_resolve_launch_spec_shared_profile_requires_cache_dir():
    """'shared' profile requires a cache_dir; omitting raises DeployConfigError."""
    from groundloop.engines.lore.deploy import resolve_launch_spec, DeployConfigError

    with pytest.raises(DeployConfigError):
        resolve_launch_spec(profile_name="shared", environ={})


def test_resolve_launch_spec_shared_profile_with_cache_dir():
    """'shared' profile succeeds when cache_dir is supplied."""
    from groundloop.engines.lore.deploy import resolve_launch_spec, LaunchSpec

    spec = resolve_launch_spec(profile_name="shared", environ={}, cache_dir="/tmp/cbm_cache")
    assert isinstance(spec, LaunchSpec)
    assert spec.env.get("CBM_CACHE_DIR") == "/tmp/cbm_cache"


def test_resolve_launch_spec_cwd_from_env():
    """KNOWLEDGELOOP_CBM_CWD sets the cwd in the LaunchSpec."""
    from groundloop.engines.lore.deploy import resolve_launch_spec

    spec = resolve_launch_spec(environ={"KNOWLEDGELOOP_CBM_CWD": "/workspace/myrepo"})
    assert spec.cwd == "/workspace/myrepo"
