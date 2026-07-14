"""render_knowledge — the type-grouped PLAN-prompt preamble (Phase B2). Construct Knowledge inline. Empty
in -> "" (byte-identical to no injection); shape mirrors skills/base.render_skills (leading "\\n\\n# ...").
Groups render in the fixed localize_hint -> fix_step -> api_requirement order regardless of input order;
an off-taxonomy type contributes nothing (defensive — an item's content is the only text that reaches
the prompt)."""
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.render import render_knowledge


def _knowledge(kid, ktype, content):
    return Knowledge(id=kid, applies_when={"any_text": ["x"]}, type=ktype, content=content,
                     grounding_refs=(), provenance="p", tier="candidate", evidence={})


def test_empty_in_empty_out():
    assert render_knowledge([]) == ""


def test_groups_render_in_fixed_order_regardless_of_input():
    # fix_step passed BEFORE localize_hint; render must still emit localize before fix.
    out = render_knowledge([_knowledge("c-fix", "fix_step", "Reject the 0 handle at entry."),
                            _knowledge("c-loc", "localize_hint", "Look in the native translation unit.")])
    assert out.startswith("\n\n# Grounded knowledge")
    assert "Known localize hints for this crash class" in out
    assert "Known fix steps for this crash class" in out
    assert out.index("Known localize hints") < out.index("Known fix steps")   # fixed order


def test_only_present_groups_appear():
    out = render_knowledge([_knowledge("c-fix", "fix_step", "Reject the 0 handle at entry.")])
    assert out.startswith("\n\n# Grounded knowledge")
    assert "Known fix steps for this crash class" in out
    assert "Known localize hints" not in out and "Required APIs" not in out


def test_off_taxonomy_type_contributes_nothing():
    assert render_knowledge([_knowledge("c-bogus", "bogus_type", "should not render")]) == ""


def test_each_content_is_a_bulleted_line():
    out = render_knowledge([_knowledge("c-api", "api_requirement", "Call startForeground within 5s.")])
    assert "Required APIs for this crash class" in out
    assert "- Call startForeground within 5s." in out


def test_multiline_content_is_collapsed_to_one_bullet():
    # an item whose content smuggles a markdown header must NOT break the preamble structure.
    out = render_knowledge([_knowledge("c-inj", "fix_step", "step one\n## Injected Header\nstep two")])
    assert "- step one ## Injected Header step two" in out    # single-line bullet, whitespace collapsed
    assert "\n## Injected Header" not in out                  # no stray group-level header
    assert out.count("# Grounded knowledge") == 1             # only the renderer's own top header
