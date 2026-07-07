"""Per-claim placebo control (Phase C1). Mirrors tests for kb/placebo.build_placebo but at Claim
granularity: one placebo Claim per candidate, SAME applies_when + type (fires on the identical cases),
empty grounding_refs, length-matched IRRELEVANT content that is leak-safe vs the real owner denylist."""
from groundloop.kb.claim import Claim
from groundloop.kb.claim_placebo import build_claim_placebo
from groundloop.kb.validate import owner_denylist


def _claim(cid="c-seg", **over) -> Claim:
    base = dict(id=cid, applies_when={"any_text": ["sigsegv", "segv_maperr"]}, type="fix_step",
                content="Reject a 0 nativePtr handle at native method entry before dereferencing it.",
                grounding_refs=("GetLongField",), provenance="native-null-deref-segv",
                tier="candidate", evidence={})
    base.update(over)
    return Claim(**base)


def test_one_placebo_per_claim_same_predicate_and_type():
    src = {"c-seg": _claim()}
    pl = build_claim_placebo(src)
    assert set(pl) == {"placebo-c-seg"}
    p = pl["placebo-c-seg"]
    assert p.id == "placebo-c-seg"
    assert p.applies_when == src["c-seg"].applies_when      # fires on the IDENTICAL cases
    assert p.type == src["c-seg"].type                      # same advice slot (grouped identically)
    assert p.grounding_refs == ()                           # cites nothing
    assert p.tier == "candidate"                            # injectable at the eval floor (same as source)


def test_placebo_content_is_length_matched_and_leak_safe():
    c = _claim(content="Guard the native peer handle before the JNI call resolves the field id here now.")
    p = build_claim_placebo({c.id: c})["placebo-" + c.id]
    assert p.content != c.content                           # different wording (the treatment isolate)
    assert len(p.content) == max(len(c.content), 40)        # exactly length-matched (floored)
    hay = p.content.lower()
    assert not any(tok in hay for tok in owner_denylist())  # no fleet-owner leak


def test_short_content_is_floored_to_forty_chars():
    p = build_claim_placebo({"c": _claim("c", content="tiny")})["placebo-c"]
    assert len(p.content) == 40                             # floor so a 4-char claim still gets real filler


def test_empty_input_is_empty_output():
    assert build_claim_placebo({}) == {}
