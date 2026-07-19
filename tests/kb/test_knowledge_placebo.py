"""Per-item placebo control (Phase C1, retargeted to playbooks in Task 7). Mirrors tests for
kb/placebo.build_placebo but at Knowledge granularity: one placebo KnowledgePlaybook per candidate, SAME
applies_when (fires on the identical cases), empty grounding_refs/required_apis, and length-matched
IRRELEVANT signature/fix text that is leak-safe vs the real owner denylist."""
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.knowledge_placebo import build_knowledge_placebo
from groundloop.kb.validate import owner_denylist


def _knowledge(kid="c-seg", **over) -> Knowledge:
    base = dict(id=kid, applies_when={"any_text": ["sigsegv", "segv_maperr"]},
                signature="Native SIGSEGV null-pointer deref crash at a JNI method boundary",
                fix=("Reject a 0 nativePtr handle at native method entry before dereferencing it.",),
                grounding_refs=("GetLongField",), provenance="native-null-deref-segv",
                tier="candidate", evidence={})
    base.update(over)
    return Knowledge(**base)


def test_one_placebo_per_item_same_predicate_and_firing():
    src = {"c-seg": _knowledge()}
    pl = build_knowledge_placebo(src)
    assert set(pl) == {"placebo-c-seg"}
    p = pl["placebo-c-seg"]
    assert p.id == "placebo-c-seg"
    assert p.applies_when == src["c-seg"].applies_when      # fires on the IDENTICAL cases
    assert p.grounding_refs == ()                           # cites nothing
    assert p.required_apis == ()                            # asserts no checkable API
    assert p.tier == "candidate"                            # injectable at the eval floor (same as source)


def test_placebo_signature_and_fix_are_length_matched_and_leak_safe():
    k = _knowledge(signature="A crash signature naming the affected JNI boundary and native call path",
                   fix=("Guard the native peer handle before the JNI call resolves the field id here now.",))
    p = build_knowledge_placebo({k.id: k})["placebo-" + k.id]
    assert p.signature != k.signature                       # different wording (the treatment isolate)
    assert p.fix != k.fix
    assert len(p.signature) == max(len(k.signature), 40)    # exactly length-matched (floored)
    assert len(p.fix[0]) == max(len("".join(k.fix)), 40)
    hay = (p.signature + " " + " ".join(p.fix)).lower()
    assert not any(tok in hay for tok in owner_denylist())  # no fleet-owner leak


def test_short_fields_are_floored_to_forty_chars():
    p = build_knowledge_placebo({"c": _knowledge("c", signature="tiny", fix=("tiny",))})["placebo-c"]
    assert len(p.signature) == 40                           # floor so a short item still gets real filler
    assert len(p.fix[0]) == 40


def test_empty_input_is_empty_output():
    assert build_knowledge_placebo({}) == {}
