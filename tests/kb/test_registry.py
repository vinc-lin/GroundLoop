"""ClaimRegistry.select — predicate filter + tier-floor gate + optional bge-m3 rerank (Phase B1).
Mirrors tests/skills/test_mock_registry.py: construct Claims inline + a SkillCtx directly (oracle-blind).
The tier ladder gates candidates out of the production `validated` floor; `retired` (a tier outside
TIERS) never fires at any floor; the optional StubEmbedder rerank is deterministic and capped to top_k."""
from groundloop.core.types import Signals
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.kb.claim import Claim
from groundloop.kb.registry import ClaimRegistry
from groundloop.skills.ctx import SkillCtx


def _ctx(text):
    return SkillCtx(signals=Signals(), repo="r", text=text)


def _claim(cid, *, tier="candidate", any_text=("segv",), content="c"):
    return Claim(id=cid, applies_when={"any_text": list(any_text)}, type="fix_step",
                 content=content, grounding_refs=(), provenance="p", tier=tier, evidence={})


def test_select_fires_on_predicate_match():
    reg = ClaimRegistry([_claim("c-seg", any_text=("segv",)),
                         _claim("c-anr", any_text=("anr",))])
    hit = [c.id for c in reg.select(_ctx("fatal signal 11 (sigsegv), segv_maperr"), "candidate")]
    assert hit == ["c-seg"]                         # segv matches; the anr claim stays silent


def test_empty_match_is_empty_selection():
    reg = ClaimRegistry([_claim("c-seg", any_text=("segv",))])
    assert reg.select(_ctx("ui freezes; no crash"), "candidate") == []   # -> empty preamble -> none arm


def test_tier_floor_gates_candidate_out_of_validated():
    cand = _claim("c-cand", tier="candidate")
    val = _claim("c-val", tier="validated")
    canon = _claim("c-canon", tier="canonical")
    reg = ClaimRegistry([cand, val, canon])
    ctx = _ctx("boom segv here")
    at_cand = {c.id for c in reg.select(ctx, "candidate")}
    at_val = {c.id for c in reg.select(ctx, "validated")}
    assert at_cand == {"c-cand", "c-val", "c-canon"}     # eval floor: all three fire
    assert at_val == {"c-val", "c-canon"}                # production floor: candidate excluded


def test_retired_never_fires_at_any_floor():
    reg = ClaimRegistry([_claim("c-ret", tier="retired")])
    ctx = _ctx("boom segv here")
    assert reg.select(ctx, "candidate") == []            # retired is outside TIERS -> filtered first
    assert reg.select(ctx, "validated") == []


def test_predicate_only_order_is_deterministic():
    reg = ClaimRegistry([_claim("c1"), _claim("c2"), _claim("c3")])
    ctx = _ctx("segv")
    assert [c.id for c in reg.select(ctx, "candidate")] == [c.id for c in reg.select(ctx, "candidate")]


def test_optional_embedder_rerank_is_deterministic_and_capped():
    claims = [_claim("c1", content="guard native peer handle"),
              _claim("c2", content="reject zero nativePtr"),
              _claim("c3", content="check weak_ptr lock")]
    reg = ClaimRegistry(claims, embedder=StubEmbedder(), top_k=1)
    out = reg.select(_ctx("segv nativePtr"), "candidate")
    assert len(out) == 1
    out2 = ClaimRegistry(claims, embedder=StubEmbedder(), top_k=1).select(
        _ctx("segv nativePtr"), "candidate")
    assert [c.id for c in out] == [c.id for c in out2]
