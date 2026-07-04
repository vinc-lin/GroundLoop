"""Gated live acceptance test for gloop produce.

Skipped unless KLOOP_PRODUCE_READY=1 is set in the environment.
When enabled, this test generates a wiki for a tiny real repo and asserts:
  - overview.md exists
  - module_tree.json exists and is non-empty

Usage (on a machine configured with an LLM API key):
    KLOOP_PRODUCE_READY=1 pytest tests/e2e/test_produce_live.py -v
"""
from __future__ import annotations

import json
import os
import pytest


KLOOP_PRODUCE_READY = os.environ.get("KLOOP_PRODUCE_READY", "").strip() in ("1", "true", "yes")


@pytest.mark.skipif(not KLOOP_PRODUCE_READY, reason="KLOOP_PRODUCE_READY not set — live test skipped")
def test_produce_live_generates_wiki(tmp_path):
    """Live: gloop produce runs on a tiny repo and produces overview.md + module_tree.json."""
    import subprocess
    import sys

    # Use the GroundLoop repo itself as a small real target
    repo_path = os.environ.get("KLOOP_PRODUCE_TEST_REPO", str(tmp_path / "repo"))
    out_dir = tmp_path / "wiki"
    out_dir.mkdir()

    # If no repo override, create a minimal stub repo for the test
    if not os.path.isdir(repo_path):
        import subprocess as sp
        sp.run(["git", "init", repo_path], check=True)
        stub = os.path.join(repo_path, "main.py")
        with open(stub, "w") as f:
            f.write("def hello(): pass\n")

    result = subprocess.run(
        [sys.executable, "-m", "groundloop.cli", "produce",
         "--repo", repo_path,
         "--out", str(out_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"gloop produce exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    overview = out_dir / "overview.md"
    assert overview.exists(), "overview.md was not generated"

    module_tree = out_dir / "module_tree.json"
    assert module_tree.exists(), "module_tree.json was not generated"
    data = json.loads(module_tree.read_text())
    assert data, "module_tree.json is empty"
