"""LLM-propose decomposition of a feedstock Skill into candidate Claims (Phase A3). Hermetic: a scripted
CannedModel stands in for the LLM; grounding uses a fake resolver. Asserts the tolerant parse never raises,
candidates are typed + content-derived-id'd at tier=candidate, applies_when defaults to the Skill's
[skill.match], and extract_to_store grounds + merges."""
from groundloop.adapters.mock.model import CannedModel
from groundloop.kb.extract import claims_from_skill, extract_to_store, parse_claims

_SKILL = {"id": "native-null-deref-segv", "guidance": "Signature: SIGSEGV.\nFix: guard nativePtr.",
          "hint_apis": ["GetLongField"], "match": {"any_text": ["sigsegv"]}}

_GOOD = ('```json\n{"claims": [{"type": "fix_step", "content": "Guard the 0 nativePtr handle at entry.",'
         ' "grounding_refs": ["GetLongField"], "applies_when": {"any_text": ["sigsegv"]}}]}\n```')


def test_parse_claims_is_tolerant():
    assert parse_claims("") == []
    assert parse_claims("no json here") == []
    assert parse_claims("{ broken json") == []
    parsed = parse_claims(_GOOD)
    assert parsed[0]["type"] == "fix_step"


def test_claims_from_skill_builds_candidates():
    claims = claims_from_skill(_SKILL, CannedModel({"default": _GOOD}))
    assert len(claims) == 1
    c = claims[0]
    assert c.tier == "candidate"
    assert c.type == "fix_step"
    assert c.provenance == "native-null-deref-segv"
    assert c.grounding_refs == ("GetLongField",)
    assert c.applies_when == {"any_text": ["sigsegv"]}
    assert c.id.startswith("native-null-deref-segv-fix_step-")   # content-derived, provenance-prefixed


def test_claims_from_skill_defaults_applies_when_to_skill_match():
    resp = ('{"claims": [{"type": "localize_hint", "content": "Look in the native translation unit.", '
            '"grounding_refs": ["GetLongField"]}]}')                # no applies_when in the proposal
    claims = claims_from_skill(_SKILL, CannedModel({"default": resp}))
    assert claims[0].applies_when == {"any_text": ["sigsegv"]}      # fell back to the Skill's [skill.match]


def test_extract_to_store_grounds_and_merges():
    store, rejected = extract_to_store([_SKILL], CannedModel({"default": _GOOD}),
                                       resolver=lambda ref: ref == "GetLongField")
    assert len(store) == 1 and rejected == []
    (claim,) = store.values()
    assert claim.tier == "candidate"
    # a candidate whose refs don't resolve is REJECTED (not stored)
    store2, rejected2 = extract_to_store([_SKILL], CannedModel({"default": _GOOD}),
                                         resolver=lambda ref: False)
    assert store2 == {} and len(rejected2) == 1
