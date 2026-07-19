"""Migration parity: the native TOML seed and the migrated markdown Skills must select IDENTICALLY over a
discriminating ctx panel — proving the shipped transform reproduces author intent. NOT a general proof of
transform correctness (see docs/skill-kb-migration.md 'honesty ceiling'); it regression-guards the
transform + documents the contract. The negative control proves the assertion can fail."""
import dataclasses
from pathlib import Path

from groundloop.skills.adapters.migrate import migrate_markdown_skills
from groundloop.skills.adapters.mock import MockSkillRegistry, load_skills
from groundloop.skills.predicate import compile_predicate
from tests.fixtures.skills.panel import build_panel

FX = Path(__file__).parent.parent / "fixtures" / "skills"


def _ids(reg, ctx):
    return {s.id for s in reg.select(ctx)}


def test_panel_is_discriminating():
    # meta-assert: the panel is not all-empty and not all-match (else parity would be vacuously green)
    native = MockSkillRegistry(load_skills(str(FX / "seed.toml")))
    sizes = [len(native.select(c)) for c in build_panel()]
    assert min(sizes) == 0 and max(sizes) >= 1 and any(0 < s < len(native.skills) for s in sizes)


def test_native_and_migrated_select_identically():
    native = MockSkillRegistry(load_skills(str(FX / "seed.toml")))
    migrated = MockSkillRegistry(migrate_markdown_skills(str(FX / "md")))
    for ctx in build_panel():
        assert _ids(native, ctx) == _ids(migrated, ctx), f"parity break on: {ctx.text!r}"


def test_negative_control_broken_transform_fails_parity():
    # corrupt one migrated skill's predicate -> parity MUST break somewhere on the panel (test has teeth)
    native = MockSkillRegistry(load_skills(str(FX / "seed.toml")))
    skills = migrate_markdown_skills(str(FX / "md"))
    broken = [dataclasses.replace(s, applies_to=compile_predicate({"any_text": ["zzz-never"]}))
              if s.id == "aaos-native-lib-load-failure" else s for s in skills]
    broken_reg = MockSkillRegistry(broken)
    assert any(_ids(native, c) != _ids(broken_reg, c) for c in build_panel())
