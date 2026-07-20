"""RerankLocalizeIndex — the opt-in `--localize rerank` arm.

Targets the rank-1 precision gap (localize is ~7/10 file@5 but ~1/10 file@1): a `CodeIndex` that
generates a candidate file POOL via hybrid retrieval, gathers per-candidate code-understanding context
(a source snippet + the CodeWiki module summary + the live CBM graph), reranks the pool with an LLM judge
that SEES that context, and returns a GROUNDED file list — the judge may only REORDER the pool, never add.

Shape (SignalQueryIndex template): `rank_repos` delegates to the MATCH index and stashes the signals so
`retrieve` can key candidate-gen on the extracted CODE tokens (not just the prose query); `retrieve` does
the pool-gen + context + rerank. In the run it is wrapped in a `SplitIndex(match, rerank)` (rank from the
match arm); in the grade-run isolated diagnostic it is used directly and seeded via `note_signals`.

Fail-safe throughout: any missing dependency (no judge / no embedder / CBM down / model error / bad map)
degrades to the base pool order (or the match index's own retrieve) without crashing. Opt-in Candidate,
never a default. No `core/` or schema edit.

Doc→source & the source snippet
--------------------------------
A `doc`-kind hit's `.file` is a WIKI basename, never a source path; it is rewritten to real source
file(s) via the `entity_map` (module→files). Unmappable doc hits are DROPPED from the file pool (a wiki
basename must never leak as a localize target). Symbol hits keep their real `.file`. The `CodeIndex.retrieve`
contract carries no worktree handle, so the SOURCE snippet is read via an injected `source_reader(repo,
file)` (over `<repos_root>/<repo>/<file>`), falling back to the atlas-stored hit snippet when no reader/source.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, Sequence

from groundloop.adapters.index.labs.atlas_judge import _parse_order
from groundloop.core.types import RepoRef, RepoScore, Signals
from groundloop.domains.android_ivi.functional_signals import code_query
from groundloop.eval.cost import cost_of


class FileJudge(Protocol):
    """Reorders candidate source files given each file's code-understanding context.

    `candidates` is a list of `(path, context_block)`; returns the paths in ranked (best-first) order."""
    def rerank(self, query: str, candidates: list[tuple[str, str]]) -> list[str]: ...


class StubFileJudge:
    """Hermetic double. `order` returns a fixed path list for ANY candidates; else `verdicts` keys a
    reorder by the candidate-path tuple; unmapped -> the candidate order unchanged. The adapter GROUNDS
    whatever comes back, so a fixed `order` may name non-pool / partial paths for tests."""
    def __init__(self, order: Optional[list[str]] = None, verdicts: Optional[dict] = None):
        self._order = order
        self._v = verdicts or {}

    def rerank(self, query: str, candidates: list[tuple[str, str]]) -> list[str]:
        paths = [p for p, _ in candidates]
        if self._order is not None:
            return list(self._order)
        return list(self._v.get(tuple(paths), paths))


class GatewayFileJudge:
    """LLM file-rerank via the gateway chat endpoint (temperature 0). Mirrors atlas_judge.GatewayJudge
    but the prompt carries each candidate's code-understanding context so the model reasons about the
    real code, not just a path. Fail-safe: returns the input path order on any malformed/error response
    (never sinks localize). Tracks cumulative USD in `.cost_usd`."""
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self.cost_usd = 0.0
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def rerank(self, query: str, candidates: list[tuple[str, str]]) -> list[str]:
        import httpx
        self.calls += 1
        paths = [p for p, _ in candidates]
        blocks = "\n\n".join(f"[{i + 1}] {p}\n{ctx}".rstrip()
                             for i, (p, ctx) in enumerate(candidates))
        prompt = (
            "A defect ticket must be localized to the source file that most likely OWNS the bug. "
            "Below are candidate files, each with a source snippet, its module summary, and call-graph "
            "context. Rank the files from MOST to LEAST likely to own the defect. Answer ONLY a "
            "comma-separated list of the file paths in ranked order, nothing else.\n\n"
            f"TICKET: {query}\n\nCANDIDATES:\n{blocks}\n\nRanked file paths:")
        try:
            resp = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}"},
                              json={"model": self._model, "temperature": 0,
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            self.input_tokens += pt
            self.output_tokens += ct
            self.cost_usd += cost_of(pt, ct, self._model)
        except Exception:      # noqa: BLE001 — never sink localize on a judge hiccup
            return list(paths)
        return _parse_order(text, paths)


class RerankLocalizeIndex:
    def __init__(self, match_index, *, store, embedder=None, judge: Optional[FileJudge] = None,
                 cbm=None, entity_map=None, source_reader=None, pool_index=None, k: int = 20,
                 max_context_chars: int = 800):
        self._match = match_index
        self.store = store
        self.embedder = embedder
        self.judge = judge
        # pool_index: an optional CodeIndex whose retrieve() supplies the recall POOL (a recall-first
        # cascade) INSTEAD of _gen_hits; None (default) keeps the byte-identical _gen_hits path.
        self._pool_index = pool_index
        # cbm: a live graph object (single-repo, `.snippet`/`.call_neighbors`) OR a callable
        # repo_name -> CBMLiveGraph|None (multi-repo, resolved per candidate repo like entity_map).
        self.cbm = cbm
        # entity_map: an EntityMap (single-repo) OR a callable repo_name -> EntityMap|None (multi-repo).
        self.entity_map = entity_map
        # source_reader: callable (repo_name, file) -> source text | None.
        self.source_reader = source_reader
        self.k = k
        self._ctx = max_context_chars
        self._last_signals: Signals | None = None
        self._lut_cache: dict[int, dict[str, list[str]]] = {}
        # count of live embed-lane failures that degraded a candidate-gen to keyword-only. Non-zero means
        # the vector signal was silently missing for some repos — a rerank scorecard is then suspect.
        self.embed_failures = 0

    # -- CodeIndex surface -------------------------------------------------------------------

    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]:
        self._last_signals = signals
        return self._match.rank_repos(signals, catalog)

    def note_signals(self, signals: Signals) -> None:
        """Seed the stashed signals for out-of-loop callers (grade-run's isolated diagnostic)."""
        self._last_signals = signals

    @property
    def cost_usd(self) -> float:
        """Cumulative USD spent by the LLM file-judge (0.0 when there is no gateway judge). The run cost
        plane sums this alongside the fixer model's cost so the reranker's spend counts toward $/ticket."""
        return float(getattr(self.judge, "cost_usd", 0.0) or 0.0)

    # calls / input_tokens / output_tokens proxy the judge so _CombinedCostModel counts the judge's
    # activity in the run-record (else model_calls shows only the fixer's calls and the judge reads as
    # "never fired" — the Tier-1 cost-accounting blind spot). 0 when there is no gateway judge.
    @property
    def calls(self) -> int:
        return int(getattr(self.judge, "calls", 0) or 0)

    @property
    def input_tokens(self) -> int:
        return int(getattr(self.judge, "input_tokens", 0) or 0)

    @property
    def output_tokens(self) -> int:
        return int(getattr(self.judge, "output_tokens", 0) or 0)

    def retrieve(self, repo: RepoRef, query: str) -> list[str]:
        try:
            return self._retrieve(repo, query)
        except Exception:      # noqa: BLE001 — candidate-gen must never sink localize
            return self._fallback(repo, query)

    # -- internals ---------------------------------------------------------------------------

    def _retrieve(self, repo: RepoRef, query: str) -> list[str]:
        q = code_query(self._last_signals) if self._last_signals is not None else ""
        query_str = q or query
        if self._pool_index is not None:
            hits = self._pool_index_hits(repo, query, query_str)
        else:
            hits = self._gen_hits(repo.name, query_str)
        em = self._entity_map_for(repo.name)
        pool, qns_by_file, snip_by_file, wiki_by_file = self._build_pool(hits, em)
        if not pool:
            return self._fallback(repo, query)
        if self.judge is None or len(pool) <= 1:
            return pool
        cbm = self._cbm_for(repo.name)     # resolve the per-repo live graph once (a CBMLiveGraph is 1-repo)
        candidates = [(f, self._context_for(repo.name, f, qns_by_file, snip_by_file, wiki_by_file, cbm))
                      for f in pool]
        try:
            order = self.judge.rerank(query, candidates)
        except Exception:      # noqa: BLE001 — an LLM error degrades to the base pool order
            return pool
        return self._ground(order, pool)

    def _gen_hits(self, repo_name: str, query_str: str) -> list[dict]:
        """Hybrid symbol+doc candidate hits. Uses find_related_units (keyword+vector RRF) when an
        embedder is present; degrades to keyword-only when it is not (find_related_units needs the
        embedder). Any failure -> keyword-only, then []."""
        if self.embedder is not None:
            import asyncio
            from groundloop.engines.atlas.retrieve import find_related_units
            try:
                return asyncio.run(find_related_units(
                    self.store, self.embedder, query_str, repos=[repo_name],
                    kinds=["symbol", "doc"], k=self.k))
            except Exception as e:  # noqa: BLE001 — count+log, then degrade to keyword-only (never silent)
                self.embed_failures += 1
                logging.getLogger("groundloop.localize").warning(
                    "rerank embed lane failed (%s); degrading to keyword-only for repo=%s", e, repo_name)
        return self._keyword_hits(repo_name, query_str)

    def _keyword_hits(self, repo_name: str, query_str: str) -> list[dict]:
        hits: list[dict] = []
        try:
            rows = self.store.keyword_search(query_str, k=self.k, repos=[repo_name],
                                             kinds=["symbol", "doc"])
        except Exception:      # noqa: BLE001
            return hits
        for u, _rank in rows:
            hits.append({"kind": u.kind, "file": u.file, "qualified_name": u.qualified_name,
                         "snippet": (u.text or "")[:400], "meta": u.meta or {}})
        return hits

    def _pool_index_hits(self, repo: RepoRef, query: str, query_str: str) -> list[dict]:
        """Recall pool from the injected CodeIndex (e.g. the cascade) as symbol hits, PLUS a doc lane so
        _build_pool can rewrite doc units -> source and stash CodeWiki summaries for the judge context.
        The injected index gets the PROSE query + the stashed signals (it runs its own code_query/anchors);
        symbol hits are listed FIRST so the pool cap keeps the recall candidates over doc-rewritten ones."""
        if hasattr(self._pool_index, "note_signals"):
            self._pool_index.note_signals(self._last_signals)
        try:
            files = list(self._pool_index.retrieve(repo, query))
        except Exception:      # noqa: BLE001 — a pool-source failure degrades to the doc lane, never sinks localize
            files = []
        sym = [{"kind": "symbol", "file": f, "qualified_name": "", "snippet": "", "meta": {}} for f in files]
        return sym + self._doc_hits(repo.name, query_str)

    def _doc_hits(self, repo_name: str, query_str: str) -> list[dict]:
        hits: list[dict] = []
        try:
            rows = self.store.keyword_search(query_str, k=self.k, repos=[repo_name], kinds=["doc"])
        except Exception:      # noqa: BLE001
            return hits
        for u, _rank in rows:
            hits.append({"kind": u.kind, "file": u.file, "qualified_name": u.qualified_name,
                         "snippet": (u.text or "")[:400], "meta": u.meta or {}})
        return hits

    def _build_pool(self, hits, em):
        """Ordered, deduped source-file pool (capped at k) + per-file context maps. Symbol hits keep
        their real .file; doc hits are rewritten to source via the entity_map (dropped if unmappable)."""
        pool: list[str] = []
        seen: set[str] = set()
        qns_by_file: dict[str, list[str]] = {}
        snip_by_file: dict[str, str] = {}
        wiki_by_file: dict[str, str] = {}

        def _add(f: str) -> None:
            if f and f not in seen:
                seen.add(f)
                pool.append(f)

        for hit in hits:
            if hit.get("kind") == "doc":
                text = hit.get("snippet") or ""
                for sf in self._doc_sources(em, hit):
                    if sf and sf not in wiki_by_file:
                        wiki_by_file[sf] = text
                    _add(sf)
            else:
                f = hit.get("file")
                if not f:
                    continue
                qn = hit.get("qualified_name")
                if qn:
                    qns_by_file.setdefault(f, []).append(qn)
                if f not in snip_by_file:
                    snip_by_file[f] = hit.get("snippet") or ""
                _add(f)
        return pool[: self.k], qns_by_file, snip_by_file, wiki_by_file

    def _context_for(self, repo_name, file, qns_by_file, snip_by_file, wiki_by_file, cbm=None) -> str:
        parts: list[str] = []
        src = None
        if self.source_reader is not None:
            try:
                src = self.source_reader(repo_name, file)
            except Exception:  # noqa: BLE001
                src = None
        if not src:
            src = snip_by_file.get(file, "")
        if src:
            parts.append("SOURCE:\n" + src[: self._ctx])
        wiki = wiki_by_file.get(file, "")
        if wiki:
            parts.append("WIKI:\n" + wiki[: self._ctx])
        if cbm is not None:
            cbm_bits: list[str] = []
            for qn in qns_by_file.get(file, [])[:2]:
                try:
                    snip = cbm.snippet(qn)
                except Exception:  # noqa: BLE001
                    snip = ""
                if snip:
                    cbm_bits.append(snip[: self._ctx])
                try:
                    neigh = cbm.call_neighbors(qn)
                except Exception:  # noqa: BLE001
                    neigh = []
                if neigh:
                    cbm_bits.append("calls: " + ", ".join(neigh[:8]))
            if cbm_bits:
                parts.append("CBM:\n" + "\n".join(cbm_bits)[: self._ctx])
        return "\n".join(parts)[: self._ctx * 3]

    def _doc_sources(self, em, hit) -> list[str]:
        """Rewrite a doc hit -> its module's source files via the entity_map. [] when no map / unmappable."""
        if em is None:
            return []
        lut = self._module_lut(em)
        keys: list[str] = []
        module = (hit.get("meta") or {}).get("module")
        if module:
            keys.append(module)
        f = hit.get("file")
        if f:
            keys.append(f)
            base = f.rsplit("/", 1)[-1]
            keys.append(base)
            if "." in base:
                keys.append(base.rsplit(".", 1)[0])
        for key in keys:
            if key in lut:
                return lut[key]
        return []

    def _module_lut(self, em) -> dict[str, list[str]]:
        """module-key / wiki-page / basename / stem -> ordered unique source files. Cached per map."""
        cached = self._lut_cache.get(id(em))
        if cached is not None:
            return cached
        lut: dict[str, list[str]] = {}
        for mm in getattr(em, "modules", []) or []:
            files: list[str] = []
            for e in mm.entries:
                if e.file and e.file not in files:
                    files.append(e.file)
            wp = mm.wiki_page or ""
            stem = wp.rsplit(".", 1)[0] if "." in wp else wp
            for key in (mm.module, wp, wp.rsplit("/", 1)[-1] if wp else "", stem):
                if key and key not in lut:
                    lut[key] = files
        self._lut_cache[id(em)] = lut
        return lut

    def _entity_map_for(self, repo_name: str):
        em = self.entity_map
        if callable(em):
            try:
                return em(repo_name)
            except Exception:  # noqa: BLE001
                return None
        return em

    def _cbm_for(self, repo_name: str):
        """Resolve the live CBM graph for a candidate repo. A `CBMLiveGraph` is bound to ONE repo, but the
        index spans repos, so `cbm` may be a callable repo_name -> CBMLiveGraph|None (mirrors entity_map).
        Fail-safe: a raising/absent provider -> None -> the reranker simply drops the CBM context block."""
        cbm = self.cbm
        if callable(cbm):
            try:
                return cbm(repo_name)
            except Exception:  # noqa: BLE001
                return None
        return cbm

    @staticmethod
    def _ground(order, pool) -> list[str]:
        """Keep only pool files, in the judge's order; append any pool file the judge omitted."""
        pool_set = set(pool)
        out: list[str] = []
        seen: set[str] = set()
        for p in order:
            if p in pool_set and p not in seen:
                out.append(p)
                seen.add(p)
        for p in pool:
            if p not in seen:
                out.append(p)
                seen.add(p)
        return out

    def _fallback(self, repo: RepoRef, query: str) -> list[str]:
        try:
            if hasattr(self._match, "retrieve"):
                return self._match.retrieve(repo, query)
        except Exception:      # noqa: BLE001
            pass
        return []
