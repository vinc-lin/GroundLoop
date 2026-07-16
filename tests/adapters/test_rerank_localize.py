"""RerankLocalizeIndex (--localize rerank): a grounded LLM file-reranker over a hybrid candidate pool.

Hermetic — no network / no real LLM / no live CBM. The atlas fixture carries BOTH symbol units (real
source files) and doc units (wiki basenames + module meta); a fixture entity_map rewrites doc modules to
source files; a StubFileJudge scripts the reorder. Candidate-gen runs keyword-only (embedder=None) so the
FTS pool is deterministic."""
from __future__ import annotations

import pytest

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.rerank_localize import (
    RerankLocalizeIndex,
    StubFileJudge,
)
from groundloop.core.types import RepoRef
from groundloop.engines.atlas.store import Store, Unit
from groundloop.engines.lore.bridge.schema import (
    CONFIDENCE,
    EntityEntry,
    EntityMap,
    ModuleMap,
)

REPO = "repoA"
ALPHA, BETA, GAMMA = "src/alpha.java", "src/beta.java", "src/gamma.java"
AUDIO_SRC = "src/audio_player.java"


def _build_atlas(db_path: str) -> str:
    s = Store(db_path)
    units = [
        Unit(repo=REPO, kind="symbol", name="Alpha", qualified_name="com.foo.Alpha",
             file=ALPHA, repo_head="h", text="class Alpha audio handler", meta={}),
        Unit(repo=REPO, kind="symbol", name="Beta", qualified_name="com.foo.Beta",
             file=BETA, repo_head="h", text="class Beta audio handler", meta={}),
        Unit(repo=REPO, kind="symbol", name="Gamma", qualified_name="com.foo.Gamma",
             file=GAMMA, repo_head="h", text="class Gamma audio handler", meta={}),
        # doc unit: .file is the WIKI basename, module rides in meta (mirrors chunk.doc_units)
        Unit(repo=REPO, kind="doc", name="Audio", qualified_name=None,
             file="audio.md", repo_head="h", text="Audio module handles playback",
             meta={"module": "audio", "ord": 0}),
    ]
    s.reindex_repo(REPO, list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return db_path


def _entity_map() -> EntityMap:
    entry = EntityEntry(symbol="AudioPlayer", file=AUDIO_SRC, cbm_node_id=None, lines=None,
                        match_strategy="file_only", confidence=CONFIDENCE["file_only"])
    return EntityMap(built_at_repo_head="h", wiki_commit=None, graph_commit=None,
                     modules=[ModuleMap(module="audio", wiki_page="audio.md", path="src",
                                        entries=[entry])])


QUERY = "Alpha Beta Gamma Audio"


@pytest.fixture()
def atlas(tmp_path):
    return _build_atlas(str(tmp_path / "atlas.db"))


def _rerank(atlas, **kw):
    store = Store(atlas)
    return RerankLocalizeIndex(AtlasIndex(atlas), store=store, embedder=None, **kw)


def test_splitindex_fires_reranker_signal_stash(atlas):
    """End-to-end: RerankLocalizeIndex runs wrapped in SplitIndex(match, rerank), and run_ticket calls
    rank_repos then retrieve on the SplitIndex. SplitIndex.rank_repos must propagate the signals into the
    reranker (note_signals) so retrieve keys candidate-gen on the extracted code tokens, not the prose."""
    from groundloop.adapters.index.split import SplitIndex
    from groundloop.core.types import Signals
    rer = _rerank(atlas, judge=None, entity_map=_entity_map())
    split = SplitIndex(AtlasIndex(atlas), rer)
    sig = Signals(classes=("com.foo.Alpha",), methods=("play",))
    split.rank_repos(sig, [RepoRef(REPO)])
    assert rer._last_signals == sig     # SplitIndex propagated note_signals into the reranker


def test_grounded_reorder(atlas):
    """The reranker returns the StubFileJudge's order, filtered to the real candidate pool."""
    order = [GAMMA, BETA, ALPHA, AUDIO_SRC]
    idx = _rerank(atlas, judge=StubFileJudge(order=order), entity_map=_entity_map())
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert out == order              # all four are in the pool -> exact scripted order
    assert "audio.md" not in out     # the wiki basename never leaks as a file


def test_non_pool_file_dropped(atlas):
    """A judge naming a file that is not in the candidate pool has it dropped from the result."""
    order = ["src/PHANTOM.java", BETA, ALPHA, GAMMA, AUDIO_SRC]
    idx = _rerank(atlas, judge=StubFileJudge(order=order), entity_map=_entity_map())
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert "src/PHANTOM.java" not in out
    assert out == [BETA, ALPHA, GAMMA, AUDIO_SRC]


def test_omitted_pool_file_appended(atlas):
    """Pool files the judge omits are appended (grounding never drops real candidates)."""
    idx = _rerank(atlas, judge=StubFileJudge(order=[GAMMA]), entity_map=_entity_map())
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert out[0] == GAMMA
    assert set(out) == {ALPHA, BETA, GAMMA, AUDIO_SRC}


def test_doc_rewritten_to_source(atlas):
    """A doc hit is rewritten to its module's source file via the entity_map (not the wiki basename)."""
    idx = _rerank(atlas, judge=None, entity_map=_entity_map())
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert AUDIO_SRC in out
    assert "audio.md" not in out


def test_doc_dropped_when_unmappable(atlas):
    """Without an entity_map a doc hit cannot be rewritten -> it is dropped (no wiki basename leaks)."""
    idx = _rerank(atlas, judge=None, entity_map=None)
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert "audio.md" not in out
    assert AUDIO_SRC not in out
    assert set(out) == {ALPHA, BETA, GAMMA}


def test_failsafe_no_judge(atlas):
    """judge=None -> the base pool order, no crash."""
    idx = _rerank(atlas, judge=None, entity_map=_entity_map())
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert out                       # non-empty
    assert all(not f.endswith(".md") for f in out)


def test_failsafe_judge_raises(atlas):
    """A judge that raises -> the base pool order, no crash (the LLM error never sinks localize)."""
    class _Boom:
        def rerank(self, query, candidates):
            raise RuntimeError("model down")

    idx = _rerank(atlas, judge=_Boom(), entity_map=_entity_map())
    out = idx.retrieve(RepoRef(REPO), QUERY)
    assert set(out) == {ALPHA, BETA, GAMMA, AUDIO_SRC}


def test_source_reader_and_cbm_feed_context(atlas):
    """The judge sees per-candidate context: source snippet (via source_reader) + live CBM. We capture
    the candidate blocks the judge received and assert the injected context reached it."""
    seen = {}

    class _CapJudge:
        def rerank(self, query, candidates):
            seen["candidates"] = candidates
            return [p for p, _ in candidates]

    def reader(repo_name, file):
        return f"SOURCE_OF::{file}" if file == ALPHA else None

    class _CBM:
        def snippet(self, qn):
            return f"cbmsnip::{qn}"

        def call_neighbors(self, qn, **kw):
            return ["com.foo.Neighbor"]

    idx = _rerank(atlas, judge=_CapJudge(), entity_map=_entity_map(),
                  source_reader=reader, cbm=_CBM())
    idx.retrieve(RepoRef(REPO), QUERY)
    ctx = dict(seen["candidates"])
    assert "SOURCE_OF::src/alpha.java" in ctx[ALPHA]       # source_reader fed the ALPHA block
    assert "cbmsnip::com.foo.Alpha" in ctx[ALPHA]          # live CBM snippet fed the ALPHA block
    assert "Neighbor" in ctx[ALPHA]                        # call-graph neighbors fed the block


def test_callable_cbm_resolves_per_repo(atlas):
    """`cbm` may be a callable repo_name -> CBMLiveGraph|None (a CBMLiveGraph is bound to ONE repo, but the
    index spans repos). The reranker resolves it per candidate repo and the resolved graph's context reaches
    the candidate blocks the judge sees — exactly like the callable entity_map path. No real CBM is opened."""
    seen = {}
    resolved_for: list[str] = []

    class _CapJudge:
        def rerank(self, query, candidates):
            seen["candidates"] = candidates
            return [p for p, _ in candidates]

    class _StubCBM:
        def __init__(self, repo_name):
            self._repo = repo_name

        def snippet(self, qn):
            return f"cbmsnip::{self._repo}::{qn}"

        def call_neighbors(self, qn, **kw):
            return ["com.foo.Neighbor"]

    def cbm_provider(repo_name):
        resolved_for.append(repo_name)
        return _StubCBM(repo_name)

    idx = _rerank(atlas, judge=_CapJudge(), entity_map=_entity_map(), cbm=cbm_provider)
    idx.retrieve(RepoRef(REPO), QUERY)
    assert resolved_for and resolved_for[0] == REPO      # the provider was called with the candidate repo
    ctx = dict(seen["candidates"])
    assert f"cbmsnip::{REPO}::com.foo.Alpha" in ctx[ALPHA]   # the per-repo graph fed the ALPHA block
    assert "Neighbor" in ctx[ALPHA]


def test_cbm_for_resolves_callable_and_object(atlas):
    """_cbm_for mirrors _entity_map_for: a callable is invoked with the repo name; a plain object passes
    through; a raising provider fails safe to None (no CBM context, never a crash)."""
    sentinel = object()
    idx = _rerank(atlas, judge=None, cbm=lambda repo: (sentinel if repo == REPO else None))
    assert idx._cbm_for(REPO) is sentinel
    assert idx._cbm_for("other") is None
    # a plain (non-callable) object passes through unchanged
    assert _rerank(atlas, judge=None, cbm=sentinel)._cbm_for(REPO) is sentinel

    def _boom(repo):
        raise RuntimeError("cbm provider down")

    assert _rerank(atlas, judge=None, cbm=_boom)._cbm_for(REPO) is None


def test_cost_usd_reads_judge(atlas):
    """cost_usd surfaces the judge's cumulative spend (0.0 without a gateway judge) so the run cost plane
    can count the reranker toward $/ticket."""
    assert _rerank(atlas, judge=None).cost_usd == 0.0

    class _PaidJudge:
        cost_usd = 0.0042

        def rerank(self, query, candidates):
            return [p for p, _ in candidates]

    assert _rerank(atlas, judge=_PaidJudge()).cost_usd == 0.0042


def test_note_signals_drives_code_query(atlas):
    """note_signals seeds the stashed signals so candidate-gen keys on the extracted code tokens
    (the grade-run isolated-diagnostic path), independent of the prose retrieve query."""
    from groundloop.core.types import Signals
    idx = _rerank(atlas, judge=None, entity_map=_entity_map())
    idx.note_signals(Signals(classes=("Gamma",)))
    out = idx.retrieve(RepoRef(REPO), "unrelated prose")   # prose ignored; code tokens used
    assert GAMMA in out


def test_rank_repos_delegates_and_stashes(atlas):
    """rank_repos delegates to the match index AND stashes the signals (SignalQueryIndex shape)."""
    from groundloop.core.types import Signals
    base = AtlasIndex(atlas)
    idx = RerankLocalizeIndex(base, store=Store(atlas), embedder=None, judge=None)
    sig = Signals(classes=("Alpha",))
    ranked = idx.rank_repos(sig, [RepoRef(REPO)])
    assert [r.repo.name for r in ranked] == [r.repo.name for r in base.rank_repos(sig, [RepoRef(REPO)])]
    assert idx._last_signals is sig
