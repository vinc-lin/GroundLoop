"""KnowledgeRegistry.select — predicate filter + tier-floor gate + optional bge-m3 rerank (Phase B1).
Mirrors tests/skills/test_mock_registry.py: construct Knowledge inline + a SkillCtx directly (oracle-blind).
The tier ladder gates candidates out of the production `validated` floor; `retired` (a tier outside
TIERS) never fires at any floor; the optional StubEmbedder rerank is deterministic and capped to top_k."""
from groundloop.core.types import Signals
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.registry import KnowledgeRegistry
from groundloop.skills.ctx import SkillCtx


def _ctx(text):
    return SkillCtx(signals=Signals(), repo="r", text=text)


def _knowledge(kid, *, tier="candidate", any_text=("segv",), content="c"):
    return Knowledge(id=kid, applies_when={"any_text": list(any_text)}, type="fix_step",
                     content=content, grounding_refs=(), provenance="p", tier=tier, evidence={})


def test_select_fires_on_predicate_match():
    reg = KnowledgeRegistry([_knowledge("c-seg", any_text=("segv",)),
                             _knowledge("c-anr", any_text=("anr",))])
    hit = [k.id for k in reg.select(_ctx("fatal signal 11 (sigsegv), segv_maperr"), "candidate")]
    assert hit == ["c-seg"]                         # segv matches; the anr item stays silent


def test_empty_match_is_empty_selection():
    reg = KnowledgeRegistry([_knowledge("c-seg", any_text=("segv",))])
    assert reg.select(_ctx("ui freezes; no crash"), "candidate") == []   # -> empty preamble -> none arm


def test_tier_floor_gates_candidate_out_of_validated():
    cand = _knowledge("c-cand", tier="candidate")
    val = _knowledge("c-val", tier="validated")
    canon = _knowledge("c-canon", tier="canonical")
    reg = KnowledgeRegistry([cand, val, canon])
    ctx = _ctx("boom segv here")
    at_cand = {k.id for k in reg.select(ctx, "candidate")}
    at_val = {k.id for k in reg.select(ctx, "validated")}
    assert at_cand == {"c-cand", "c-val", "c-canon"}     # eval floor: all three fire
    assert at_val == {"c-val", "c-canon"}                # production floor: candidate excluded


def test_retired_never_fires_at_any_floor():
    reg = KnowledgeRegistry([_knowledge("c-ret", tier="retired")])
    ctx = _ctx("boom segv here")
    assert reg.select(ctx, "candidate") == []            # retired is outside TIERS -> filtered first
    assert reg.select(ctx, "validated") == []


def test_predicate_only_order_is_deterministic():
    reg = KnowledgeRegistry([_knowledge("c1"), _knowledge("c2"), _knowledge("c3")])
    ctx = _ctx("segv")
    assert [k.id for k in reg.select(ctx, "candidate")] == [k.id for k in reg.select(ctx, "candidate")]


def test_optional_embedder_rerank_is_deterministic_and_capped():
    items = [_knowledge("c1", content="guard native peer handle"),
             _knowledge("c2", content="reject zero nativePtr"),
             _knowledge("c3", content="check weak_ptr lock")]
    reg = KnowledgeRegistry(items, embedder=StubEmbedder(), top_k=1)
    out = reg.select(_ctx("segv nativePtr"), "candidate")
    assert len(out) == 1
    out2 = KnowledgeRegistry(items, embedder=StubEmbedder(), top_k=1).select(
        _ctx("segv nativePtr"), "candidate")
    assert [k.id for k in out] == [k.id for k in out2]
