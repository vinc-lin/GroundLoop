"""Hermetic tests for the synchronous live-CBM query facade (CBMLiveGraph).

No real subprocess / network: a StubCBM async client is injected via `client_factory`,
so the real async->sync bridge (background loop thread + run_coroutine_threadsafe) and the
real `forward`/`nodes` wrappers are exercised against canned graph payloads.
"""
from __future__ import annotations

from groundloop.adapters.graph.cbm_live import CBMLiveGraph, open_cbm
from groundloop.engines.lore.graph.client import CBMUnavailable


class StubCBM:
    """A fake async CBM client: dispatches call_tool_with_restart on canned payloads."""

    def __init__(self, *, payloads=None, fail_on=None, fail_start=False):
        self.payloads = payloads or {}
        self.fail_on = set(fail_on or ())
        self.fail_start = fail_start
        self._running = False
        self.closed = False
        self.started = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self.fail_start:
            raise CBMUnavailable("stub start failure")
        self._running = True
        self.started = True

    async def aclose(self) -> None:
        self._running = False
        self.closed = True

    async def call_tool_with_restart(self, name, arguments=None, **kwargs):
        if name in self.fail_on:
            raise CBMUnavailable(f"stub tool failure: {name}")
        payload = self.payloads.get(name)
        if callable(payload):
            return payload(arguments or {})
        return payload


def _search_payload(args):
    pat = args.get("name_pattern", "") or ""
    if "foo" in pat:
        return {"results": [{"name": "foo", "qualified_name": "pkg.foo",
                             "file_path": "a/foo.py", "start_line": 10, "end_line": 20}],
                "has_more": False}
    if "bar" in pat:
        return {"results": [{"name": "bar", "qualified_name": "pkg.bar",
                             "file_path": "a/bar.py", "start_line": 5, "end_line": 8}],
                "has_more": False}
    return {"results": [], "has_more": False}


def _good_payloads():
    return {
        "index_repository": {"project": "proj-1"},
        "search_graph": _search_payload,
        "trace_path": {"paths": [
            [{"qualified_name": "pkg.foo"}, {"qualified_name": "pkg.helper"}],
            [{"qualified_name": "pkg.other"}],
        ]},
        "get_code_snippet": {"snippet": "def foo():\n    return helper()"},
    }


def _factory(stub):
    return lambda: stub


# --------------------------------------------------------------------------- start / project


def test_start_resolves_project_and_available():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        assert g.start() is True
        assert g.available is True
        assert stub.started is True
    finally:
        g.close()


def test_start_is_idempotent():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        assert g.start() is True
        assert g.start() is True  # second call is a no-op, same verdict
        assert g.available is True
    finally:
        g.close()


def test_start_failsafe_when_backend_start_raises():
    stub = StubCBM(payloads=_good_payloads(), fail_start=True)
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        assert g.start() is False
        assert g.available is False
    finally:
        g.close()


def test_start_failsafe_when_no_project_returned():
    payloads = _good_payloads()
    payloads["index_repository"] = {}  # no project id
    stub = StubCBM(payloads=payloads)
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        assert g.start() is False
        assert g.available is False
    finally:
        g.close()


# --------------------------------------------------------------------------- symbol_sites


def test_symbol_sites_parses():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        sites = g.symbol_sites(["foo", "bar"])
        assert sites["foo"] == ("a/foo.py", [10, 20])
        assert sites["bar"] == ("a/bar.py", [5, 8])
    finally:
        g.close()


def test_symbol_sites_missing_name_absent():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        sites = g.symbol_sites(["foo", "does_not_exist"])
        assert "foo" in sites
        assert "does_not_exist" not in sites
    finally:
        g.close()


def test_symbol_sites_failsafe_on_backend_error():
    stub = StubCBM(payloads=_good_payloads(), fail_on={"search_graph"})
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        assert g.available is True  # start succeeded; only the query tool fails
        assert g.symbol_sites(["foo"]) == {}
    finally:
        g.close()


# --------------------------------------------------------------------------- call_neighbors


def test_call_neighbors_parses():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        neigh = g.call_neighbors("pkg.foo")
        assert set(neigh) == {"pkg.helper", "pkg.other"}
        assert "pkg.foo" not in neigh  # source excluded
    finally:
        g.close()


def test_call_neighbors_failsafe_on_backend_error():
    stub = StubCBM(payloads=_good_payloads(), fail_on={"trace_path"})
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        assert g.call_neighbors("pkg.foo") == []
    finally:
        g.close()


def test_call_neighbors_handles_alternate_shapes():
    payloads = _good_payloads()
    payloads["trace_path"] = {"nodes": [{"qualified_name": "pkg.a"}, {"name": "pkg.b"}]}
    stub = StubCBM(payloads=payloads)
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        assert set(g.call_neighbors("pkg.root")) == {"pkg.a", "pkg.b"}
    finally:
        g.close()


# --------------------------------------------------------------------------- snippet


def test_snippet_parses():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        assert g.snippet("pkg.foo") == "def foo():\n    return helper()"
    finally:
        g.close()


def test_snippet_accepts_plain_string_result():
    payloads = _good_payloads()
    payloads["get_code_snippet"] = "raw source text"
    stub = StubCBM(payloads=payloads)
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        assert g.snippet("pkg.foo") == "raw source text"
    finally:
        g.close()


def test_snippet_failsafe_on_backend_error():
    stub = StubCBM(payloads=_good_payloads(), fail_on={"get_code_snippet"})
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    try:
        g.start()
        assert g.snippet("pkg.foo") == ""
    finally:
        g.close()


# --------------------------------------------------------------------------- unavailable / close


def test_queries_empty_when_unavailable():
    stub = StubCBM(payloads=_good_payloads(), fail_start=True)
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    g.start()  # fails -> unavailable
    try:
        assert g.available is False
        assert g.symbol_sites(["foo"]) == {}
        assert g.call_neighbors("pkg.foo") == []
        assert g.snippet("pkg.foo") == ""
    finally:
        g.close()


def test_queries_empty_before_start():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    # never started
    assert g.available is False
    assert g.symbol_sites(["foo"]) == {}
    assert g.call_neighbors("pkg.foo") == []
    assert g.snippet("pkg.foo") == ""


def test_close_safe_when_never_started():
    g = CBMLiveGraph("/repo", client_factory=_factory(StubCBM()))
    g.close()  # must not raise
    g.close()  # idempotent


def test_close_calls_backend_aclose():
    stub = StubCBM(payloads=_good_payloads())
    g = CBMLiveGraph("/repo", client_factory=_factory(stub))
    g.start()
    g.close()
    assert stub.closed is True


# --------------------------------------------------------------------------- open_cbm convenience


def test_open_cbm_returns_graph_on_success():
    stub = StubCBM(payloads=_good_payloads())
    g = open_cbm("/repo", client_factory=_factory(stub))
    assert g is not None
    try:
        assert g.available is True
    finally:
        g.close()


def test_open_cbm_returns_none_when_start_fails():
    stub = StubCBM(payloads=_good_payloads(), fail_start=True)
    g = open_cbm("/repo", client_factory=_factory(stub))
    assert g is None
