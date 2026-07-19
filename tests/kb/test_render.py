"""render_playbooks — one bounded block per KnowledgePlaybook (KB playbook redesign, Task 2). Construct
KnowledgePlaybook inline. Empty in -> "" (byte-identical to no injection); shape mirrors
skills/base.render_skills (leading "\\n\\n# ..."). Each field is whitespace-collapsed to a single line so a
multi-line signature/localize/fix/required_apis value cannot smuggle a stray markdown header (## / #) into
the preamble the renderer is meant to control."""
from groundloop.kb.render import render_playbooks
from groundloop.kb.knowledge import KnowledgePlaybook


def _pb(pid, **over):
    base = dict(id=pid, applies_when={"any_text": ["x"]}, signature="sig one\n## Injected\nsig two",
                localize=("look here",), fix=("do this",), required_apis=("Api.call",),
                grounding_refs=("Api.call",), provenance="p", tier="validated", evidence={})
    base.update(over)
    return KnowledgePlaybook(**base)


def test_renders_one_block_per_playbook_bounded_and_injection_safe():
    out = render_playbooks([_pb("fragment-npe")])
    assert out.startswith("\n\n# Grounded playbooks")
    assert "# Crash playbook: fragment-npe" in out
    assert "Signature: sig one ## Injected sig two" in out   # multi-line collapsed to one line
    assert "Look at: look here" in out and "Fix: do this" in out and "APIs: Api.call" in out
    assert out.count("# Grounded playbooks") == 1


def test_empty_is_empty_string():
    assert render_playbooks([]) == ""
