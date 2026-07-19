"""PlaybookRegistry.select — predicate filter + tier-floor gate + optional bge-m3 rerank over
`signature` (KB playbook redesign, Task 5; was KnowledgeRegistry reranking over `content`). Mirrors
tests/skills/test_mock_registry.py: construct KnowledgePlaybook inline + a SkillCtx directly
(oracle-blind). The tier ladder gates candidates out of the production `validated` floor; `retired` (a
tier outside TIERS) never fires at any floor; the default top_k is now 2 (was 3); the optional
StubEmbedder rerank is deterministic, orders by `signature` relevance, and is capped to top_k.
`KnowledgeRegistry` stays a transitional alias for `PlaybookRegistry` so existing importers
(cli/__init__.py::_load_knowledge, kb/ab.py, fixeval) keep working unchanged."""
from groundloop.core.types import Signals
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.kb.knowledge import KnowledgePlaybook
from groundloop.kb.registry import KnowledgeRegistry, PlaybookRegistry
from groundloop.skills.ctx import SkillCtx


def _ctx(text):
    return SkillCtx(signals=Signals(), repo="r", text=text)


def _ctx_matching_all():
    # matches every _pb() default predicate (any_text=("segv",))
    return _ctx("fatal signal 11 (sigsegv), segv_maperr")


def _pb(pid, *, tier="candidate", any_text=("segv",), signature="c", **over):
    base = dict(id=pid, applies_when={"any_text": list(any_text)}, signature=signature,
                localize=("look here",), fix=("do this",), required_apis=(),
                grounding_refs=(), provenance="p", tier=tier, evidence={})
    base.update(over)
    return KnowledgePlaybook(**base)


def test_select_fires_on_predicate_match():
    reg = PlaybookRegistry([_pb("c-seg", any_text=("segv",)),
                            _pb("c-anr", any_text=("anr",))])
    hit = [p.id for p in reg.select(_ctx("fatal signal 11 (sigsegv), segv_maperr"), "candidate")]
    assert hit == ["c-seg"]                         # segv matches; the anr item stays silent


def test_empty_match_is_empty_selection():
    reg = PlaybookRegistry([_pb("c-seg", any_text=("segv",))])
    assert reg.select(_ctx("ui freezes; no crash"), "candidate") == []   # -> empty preamble -> none arm


def test_tier_floor_gates_candidate_out_of_validated():
    cand = _pb("c-cand", tier="candidate")
    val = _pb("c-val", tier="validated")
    canon = _pb("c-canon", tier="canonical")
    reg = PlaybookRegistry([cand, val, canon], top_k=10)   # generous cap: this isolates the tier gate, not the top_k bound
    ctx = _ctx("boom segv here")
    at_cand = {p.id for p in reg.select(ctx, "candidate")}
    at_val = {p.id for p in reg.select(ctx, "validated")}
    assert at_cand == {"c-cand", "c-val", "c-canon"}     # eval floor: all three fire
    assert at_val == {"c-val", "c-canon"}                # production floor: candidate excluded


def test_retired_never_fires_at_any_floor():
    reg = PlaybookRegistry([_pb("c-ret", tier="retired")])
    ctx = _ctx("boom segv here")
    assert reg.select(ctx, "candidate") == []            # retired is outside TIERS -> filtered first
    assert reg.select(ctx, "validated") == []


def test_predicate_only_order_is_deterministic():
    reg = PlaybookRegistry([_pb("c1"), _pb("c2"), _pb("c3")])
    ctx = _ctx("segv")
    assert [p.id for p in reg.select(ctx, "candidate")] == [p.id for p in reg.select(ctx, "candidate")]


def test_select_respects_tier_floor_and_caps_at_top_k_2():
    reg = PlaybookRegistry([_pb("a", tier="validated"), _pb("b", tier="validated"),
                            _pb("c", tier="candidate")])           # default top_k=2
    out = reg.select(_ctx_matching_all(), "validated")
    assert {p.id for p in out} <= {"a", "b"} and len(out) <= 2


def test_no_embedder_path_is_capped_at_top_k():
    # 3 firing validated playbooks, NO embedder -> the predicate/tier fail-safe path must STILL cap at
    # top_k=2 (spec §4: a bounded retriever, not a firehose; the offline/fail-safe decorator path).
    reg = PlaybookRegistry([_pb("a", tier="validated"), _pb("b", tier="validated"),
                            _pb("c", tier="validated")])           # default top_k=2, no embedder
    out = reg.select(_ctx_matching_all(), "validated")
    assert reg.embedder is None and len(out) == 2                  # capped even without a rerank


def test_default_top_k_is_2():
    reg = PlaybookRegistry([_pb("a")])
    assert reg.top_k == 2


def test_optional_embedder_rerank_is_deterministic_and_capped():
    items = [_pb("c1", signature="guard native peer handle"),
             _pb("c2", signature="reject zero nativePtr"),
             _pb("c3", signature="check weak_ptr lock")]
    reg = PlaybookRegistry(items, embedder=StubEmbedder(), top_k=1)
    out = reg.select(_ctx("segv nativePtr"), "candidate")
    assert len(out) == 1
    out2 = PlaybookRegistry(items, embedder=StubEmbedder(), top_k=1).select(
        _ctx("segv nativePtr"), "candidate")
    assert [p.id for p in out] == [p.id for p in out2]


def test_rerank_orders_by_signature():
    # signature drives the rerank: an item whose signature echoes the query text must outrank one whose
    # signature is unrelated.
    items = [_pb("near", signature="segv nativePtr guard"),
             _pb("far", signature="unrelated ui layout freeze")]
    reg = PlaybookRegistry(items, embedder=StubEmbedder(), top_k=1)
    out = reg.select(_ctx("segv nativePtr"), "candidate")
    assert [p.id for p in out] == ["near"]


def test_knowledge_registry_alias_still_works():
    assert KnowledgeRegistry is PlaybookRegistry
