from groundloop.skills.base import Skill, NullSkillRegistry, render_skills


def _skill(sid):
    return Skill(id=sid, applies_to=lambda ctx: True, guidance=f"do {sid}",
                 signals=("x",), provenance="test")


def test_render_skills_emits_playbook_header():
    out = render_skills([_skill("a"), _skill("b")])
    assert out.startswith("\n\n# Applicable playbooks")
    assert "## Skill: a" in out and "do a" in out and "## Skill: b" in out


def test_render_skills_empty_is_empty_string():
    assert render_skills([]) == ""


def test_null_registry_selects_nothing():
    assert NullSkillRegistry().select(object()) == []


def test_skill_carries_new_provenance_and_signals_fields():
    s = _skill("a")
    assert s.signals == ("x",) and s.provenance == "test" and s.hint_apis == ()
