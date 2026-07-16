"""Optional live smoke for the CBMLiveGraph facade against a REAL codebase-memory-mcp.

Skipped by default (mirrors the tests/e2e/ gating). Declare the CBM backend ready + point at a
real repo to exercise the persistent stdio client + the sync bridge end-to-end::

    KLOOP_CBM_READY=1 KLOOP_CBM_SMOKE_REPO=/path/to/repo \\
    pytest tests/e2e/test_cbm_live_smoke.py -v
"""
from __future__ import annotations

import os

import pytest

_CBM_READY = os.environ.get("KLOOP_CBM_READY", "").strip() in ("1", "true", "yes")
_REPO = os.environ.get("KLOOP_CBM_SMOKE_REPO", "").strip()
_GATE = bool(_CBM_READY and _REPO and os.path.isdir(_REPO))

_SKIP_REASON = (
    "Live CBM not declared ready — set KLOOP_CBM_READY=1 + KLOOP_CBM_SMOKE_REPO=<real repo>"
)


@pytest.mark.skipif(not _GATE, reason=_SKIP_REASON)
def test_cbm_live_graph_smoke():
    """Start a real CBM subprocess, resolve the project, and run one of each query."""
    from groundloop.adapters.graph.cbm_live import open_cbm  # noqa: PLC0415

    graph = open_cbm(_REPO, call_timeout=1800.0)
    assert graph is not None, "CBM did not become available for the smoke repo"
    try:
        assert graph.available is True
        # Queries must never raise; on a real graph at least one should be non-trivial, but we
        # only assert type-safety + fail-safety here (repo contents are unknown).
        sites = graph.symbol_sites(["main"])
        assert isinstance(sites, dict)
        for qn, (file_path, lines) in sites.items():
            assert isinstance(file_path, str)
            assert isinstance(lines, list) and len(lines) == 2
            neigh = graph.call_neighbors(qn)
            assert isinstance(neigh, list)
            snip = graph.snippet(qn)
            assert isinstance(snip, str)
            break
    finally:
        graph.close()
