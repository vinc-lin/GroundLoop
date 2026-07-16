"""A synchronous, loop-blind live-CBM query facade for the run-time localize/fix stages.

CBM's client + tools are async and today CBM is used only at atlas-BUILD time
(`engines/atlas/index.py`, one-shot `asyncio.run` per repo). The (synchronous) localize/fix
stages need to query CBM's live code-graph at RUN time — this module is the missing sync bridge.

Design — the async->sync bridge
-------------------------------
A build-time `asyncio.run(...)` opens a fresh loop, runs one coroutine, and closes it. That is
WRONG for a long-lived query client: an mcp stdio client is bound to the loop it started on, and
a fresh `asyncio.run` per call would kill the subprocess. Instead this facade owns a dedicated
background thread running its own persistent event loop; the CBM client is created and always used
on THAT loop. Each synchronous query method submits its coroutine with
`run_coroutine_threadsafe(coro, self._loop).result(timeout=...)`. The synchronous loop of
`gloop run` is therefore never blocked by a nested loop.

Fail-safe contract
-------------------
Every public method catches broadly and returns an empty result — a CBM error NEVER propagates
into the loop. When the facade is not `available` (never started, or start failed), all queries
return empty immediately. This makes CBM a best-effort *enrichment* the loop can always degrade
past.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
from typing import Callable, Optional

from groundloop.engines.lore.graph import forward

# Result-shape parsing keys for a code snippet (get_code_snippet's shape is not pinned by the
# forward wrapper, so we probe the common keys defensively).
_SNIPPET_KEYS = ("snippet", "code", "source", "content", "text")


def _rows(resp) -> list:
    """search_graph rows, tolerant of a non-dict result."""
    return resp.get("results", []) if isinstance(resp, dict) else []


def _collect_qns(obj, out: list) -> None:
    """Recursively collect every qualified_name (or name) string found in a graph result.

    trace_path's exact result shape is not pinned here, so we walk the structure defensively
    (paths/nodes/edges/callers/callees all reduce to node dicts carrying a qualified_name)."""
    if isinstance(obj, dict):
        qn = obj.get("qualified_name") or obj.get("name")
        if isinstance(qn, str) and qn:
            out.append(qn)
        for value in obj.values():
            _collect_qns(value, out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_qns(item, out)


def _extract_snippet(resp) -> str:
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for key in _SNIPPET_KEYS:
            value = resp.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


class CBMLiveGraph:
    """Synchronous, fail-safe facade over a persistent live CBM stdio subprocess.

    Construction stores config only; `start()` spins up the loop-thread + client. All queries are
    no-ops returning empty until `available`. Inject a fake async client via `client_factory` for
    hermetic tests (avoids a real subprocess)."""

    def __init__(self, repo_path: str, *, call_timeout: float = 30.0,
                 client_factory: Optional[Callable[[], object]] = None):
        self._repo_path = repo_path
        self._call_timeout = call_timeout
        # generous ceiling for the sync .result() wait so a busy CBM call never spuriously trips it;
        # the CBMClient enforces its own per-call read timeout underneath.
        self._result_timeout = call_timeout + 15.0
        self._client_factory = client_factory
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client = None
        self._project: Optional[str] = None
        self._available = False
        self._started = False

    # -- lifecycle ---------------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> bool:
        """Start the loop-thread + CBM client and resolve the project id. Fail-safe + idempotent."""
        if self._started:
            return self._available
        self._started = True
        try:
            self._start_loop_thread()
            self._client = self._make_client()
            self._project = self._submit(self._bootstrap())
            self._available = bool(self._project)
        except Exception:
            self._available = False
        if not self._available:
            # tear down anything we spun up so we never leak a loop-thread on failure.
            # `_started` stays True, so the failed verdict is sticky (start() is idempotent).
            self.close()
        return self._available

    def close(self) -> None:
        """Stop the client + loop-thread. Safe to call multiple times / when never started."""
        loop = self._loop
        client = self._client
        if loop is not None and client is not None:
            try:
                fut = asyncio.run_coroutine_threadsafe(client.aclose(), loop)
                fut.result(timeout=self._call_timeout)
            except Exception:
                pass
        self._client = None
        self._available = False
        self._stop_loop_thread()

    # -- queries (all fail-safe) -------------------------------------------------------------

    def symbol_sites(self, names: list[str]) -> dict[str, tuple[str, list[int]]]:
        """Resolve symbol short-names -> (file_path, [start_line, end_line]).

        Missing / failed names are simply absent from the returned dict."""
        if not self._available:
            return {}
        try:
            return self._submit(self._symbol_sites_coro(list(names)))
        except Exception:
            return {}

    def call_neighbors(self, qualified_name: str, *, direction: str = "both",
                       depth: int = 1) -> list[str]:
        """Flat, deduped list of call-graph neighbor qualified_names. Empty on any failure."""
        if not self._available:
            return []
        try:
            return self._submit(self._neighbors_coro(qualified_name, direction, depth))
        except Exception:
            return []

    def snippet(self, qualified_name: str) -> str:
        """Source text for a symbol. Empty string on any failure."""
        if not self._available:
            return ""
        try:
            return self._submit(self._snippet_coro(qualified_name))
        except Exception:
            return ""

    # -- coroutines (run on the background loop) ---------------------------------------------

    async def _bootstrap(self) -> Optional[str]:
        await self._client.start()
        idx = await forward.index_repository(self._client, repo_path=self._repo_path)
        return idx.get("project") if isinstance(idx, dict) else None

    async def _symbol_sites_coro(self, names: list[str]) -> dict[str, tuple[str, list[int]]]:
        out: dict[str, tuple[str, list[int]]] = {}
        for name in names:
            if not name:
                continue
            try:
                short = name.rsplit(".", 1)[-1]
                resp = await forward.search_graph(
                    self._client, project=self._project,
                    name_pattern=f"^{re.escape(short)}$", limit=1)
                rows = _rows(resp)
                if not rows:
                    continue
                row = rows[0]
                file_path = row.get("file_path") or row.get("file") or ""
                if not file_path:
                    continue
                start = int(row.get("start_line") or 0)
                end = int(row.get("end_line") or 0)
                out[name] = (file_path, [start, end])
            except Exception:
                # a single bad name must not sink the batch — leave it absent
                continue
        return out

    async def _neighbors_coro(self, qualified_name: str, direction: str, depth: int) -> list[str]:
        resp = await forward.trace_path(self._client, project=self._project,
                                        function_name=qualified_name, direction=direction,
                                        depth=depth)
        collected: list[str] = []
        _collect_qns(resp, collected)
        # dedupe (preserve order) and drop the source symbol itself
        seen: set = set()
        out: list[str] = []
        for qn in collected:
            if qn == qualified_name or qn in seen:
                continue
            seen.add(qn)
            out.append(qn)
        return out

    async def _snippet_coro(self, qualified_name: str) -> str:
        resp = await forward.get_code_snippet(self._client, project=self._project,
                                              qualified_name=qualified_name)
        return _extract_snippet(resp)

    # -- internals ---------------------------------------------------------------------------

    def _make_client(self):
        if self._client_factory is not None:
            return self._client_factory()
        # Lazy import: keep the module import cheap and mcp-free until a real client is needed.
        from groundloop.engines.lore.deploy import resolve_launch_spec
        from groundloop.engines.lore.graph.client import CBMClient
        spec = resolve_launch_spec(environ=os.environ)
        return CBMClient(spec.command, env=spec.env, cwd=spec.cwd,
                         call_timeout=self._call_timeout)

    def _submit(self, coro):
        """Run a coroutine on the background loop and block for its result."""
        if self._loop is None:
            raise CBMBridgeError("CBM loop not running")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=self._result_timeout)

    def _start_loop_thread(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="cbm-live-loop", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _stop_loop_thread(self) -> None:
        loop = self._loop
        thread = self._thread
        self._loop = None
        self._thread = None
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=5.0)
        if loop is not None:
            try:
                loop.close()
            except Exception:
                pass


class CBMBridgeError(RuntimeError):
    """Internal: the sync bridge could not submit a coroutine (loop not running)."""


def open_cbm(repo_path: str, *, call_timeout: float = 30.0,
             client_factory: Optional[Callable[[], object]] = None) -> Optional[CBMLiveGraph]:
    """Construct + start a CBMLiveGraph; return None if CBM is unavailable.

    A composition-root convenience so callers can fail-safe/degrade past CBM in one check."""
    graph = CBMLiveGraph(repo_path, call_timeout=call_timeout, client_factory=client_factory)
    if graph.start():
        return graph
    graph.close()
    return None
