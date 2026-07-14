"""kb-ab retargeted to Knowledge: _registry_for builds a KnowledgeRegistry (not a raw-Skill registry);
an empty knowledge store -> every arm selects nothing (byte-identical to none); a populated store ->
kb selects the item and placebo selects its length-matched control."""
from __future__ import annotations

from groundloop.core.types import Signals
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.registry import KnowledgeRegistry
from groundloop.skills.ctx import SkillCtx


def _ctx() -> SkillCtx:
    # SkillCtx(signals, repo, text) — loop-visible only (see groundloop/skills/ctx.py)
    return SkillCtx(signals=Signals(), repo="r", text="segv null deref crash")


def _k(kid="k-seg") -> Knowledge:
    return Knowledge(id=kid, applies_when={"always": True}, type="fix_step",
                     content="Reject the 0 handle at entry.", grounding_refs=(), provenance="skill-x",
                     tier="candidate", evidence={})


def test_none_arm_is_none(monkeypatch):
    from groundloop.kb import ab
    assert ab._registry_for("none", None) is None


def test_empty_store_every_arm_selects_nothing(monkeypatch):
    from groundloop.kb import ab
    monkeypatch.setattr(ab, "load_knowledge", lambda path=None: {})
    kb = ab._registry_for("kb", None)
    placebo = ab._registry_for("placebo", None)
    assert isinstance(kb, KnowledgeRegistry) and isinstance(placebo, KnowledgeRegistry)
    assert kb.select(_ctx(), "candidate") == []       # empty store -> byte-identical to none
    assert placebo.select(_ctx(), "candidate") == []


def test_populated_store_kb_and_placebo_fire(monkeypatch):
    from groundloop.kb import ab
    monkeypatch.setattr(ab, "load_knowledge", lambda path=None: {"k-seg": _k()})
    kb_sel = ab._registry_for("kb", None).select(_ctx(), "candidate")
    pl_sel = ab._registry_for("placebo", None).select(_ctx(), "candidate")
    assert [k.id for k in kb_sel] == ["k-seg"]
    assert len(pl_sel) == 1 and pl_sel[0].id == "placebo-k-seg"
    assert pl_sel[0].content != kb_sel[0].content     # placebo is scrambled/irrelevant


def test_run_ab_threads_knowledge_not_skills(monkeypatch, tmp_path):
    """run_ab constructs FixEvalRunner with knowledge=..., never skills=... (the retarget)."""
    from groundloop.kb import ab
    seen = {}

    class _Spy:
        def __init__(self, **kw):
            seen.update(kw)
        def run(self, *a, **k):
            return []
    monkeypatch.setattr(ab, "FixEvalRunner", _Spy)
    monkeypatch.setattr(ab, "_make_fixer", lambda: object())
    monkeypatch.setattr(ab, "grade_fix_all", lambda records, oracle_by_case=None: {"arms": {}})
    monkeypatch.setattr(ab, "load_cases", lambda ds: [])
    monkeypatch.setattr(ab, "load_eval_oracle", lambda c: None)
    monkeypatch.setattr(ab, "build_arms", lambda membership_index=None: [])
    monkeypatch.setattr(ab, "AtlasIndex", lambda db: object())
    monkeypatch.setattr(ab, "MockJira", lambda ds: object())
    monkeypatch.setattr(ab, "GitFixtureEstate", lambda r, w: object())
    monkeypatch.setattr(ab, "load_knowledge", lambda path=None: {})
    cat = tmp_path / "catalog.json"
    cat.write_text('[{"name": "r"}]')
    ab.run_ab(dataset="d", repos="r", index_db="a.db", catalog_path=str(cat),
              out_dir=str(tmp_path / "o"), arms=("kb",))
    assert "knowledge" in seen and "skills" not in seen
    assert seen["knowledge_tier_floor"] == "candidate"
