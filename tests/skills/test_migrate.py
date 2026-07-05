from pathlib import Path

from groundloop.adapters.skills.migrate import migrate_markdown_skills, triggers_to_spec

MD = Path(__file__).parent.parent / "fixtures" / "skills" / "md"


def test_triggers_to_spec_translates_foreign_vocab():
    spec = triggers_to_spec(["native-crash", "so-load-failure"])
    assert "any_text" in spec and "unsatisfiedlinkerror" in spec["any_text"]
    assert any("lib" in r for r in spec.get("any_text_regex", []))


def test_triggers_to_spec_unknown_trigger_raises():
    import pytest
    with pytest.raises(KeyError):
        triggers_to_spec(["not-a-real-trigger"])


def test_migrate_markdown_produces_skills():
    skills = {s.id: s for s in migrate_markdown_skills(str(MD))}
    assert "aaos-native-lib-load-failure" in skills and "jni-native-handle-lifecycle" in skills
    n = skills["aaos-native-lib-load-failure"]
    assert n.provenance == "md-fixture:native" and callable(n.applies_to) and n.guidance
