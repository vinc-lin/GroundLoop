"""LLM-propose decomposition of a feedstock Skill into candidate Knowledge (Phase A3). Hermetic: a scripted
CannedModel stands in for the LLM; grounding uses a fake resolver. Asserts the tolerant parse never raises,
candidates are typed + content-derived-id'd at tier=candidate, applies_when defaults to the Skill's
[skill.match], and extract_to_store grounds + merges."""
from groundloop.adapters.mock.model import CannedModel
from groundloop.kb.extract import extract_to_store, knowledge_from_skill, parse_knowledge

_SKILL = {"id": "native-null-deref-segv", "guidance": "Signature: SIGSEGV.\nFix: guard nativePtr.",
          "hint_apis": ["GetLongField"], "match": {"any_text": ["sigsegv"]}}

_GOOD = ('```json\n{"claims": [{"type": "fix_step", "content": "Guard the 0 nativePtr handle at entry.",'
         ' "grounding_refs": ["GetLongField"], "applies_when": {"any_text": ["sigsegv"]}}]}\n```')


def test_parse_knowledge_is_tolerant():
    assert parse_knowledge("") == []
    assert parse_knowledge("no json here") == []
    assert parse_knowledge("{ broken json") == []
    parsed = parse_knowledge(_GOOD)
    assert parsed[0]["type"] == "fix_step"


def test_knowledge_from_skill_builds_candidates():
    items = knowledge_from_skill(_SKILL, CannedModel({"default": _GOOD}))
    assert len(items) == 1
    k = items[0]
    assert k.tier == "candidate"
    assert k.type == "fix_step"
    assert k.provenance == "native-null-deref-segv"
    assert k.grounding_refs == ("GetLongField",)
    assert k.applies_when == {"any_text": ["sigsegv"]}
    assert k.id.startswith("native-null-deref-segv-fix_step-")   # content-derived, provenance-prefixed


def test_knowledge_from_skill_defaults_applies_when_to_skill_match():
    resp = ('{"claims": [{"type": "localize_hint", "content": "Look in the native translation unit.", '
            '"grounding_refs": ["GetLongField"]}]}')                # no applies_when in the proposal
    items = knowledge_from_skill(_SKILL, CannedModel({"default": resp}))
    assert items[0].applies_when == {"any_text": ["sigsegv"]}       # fell back to the Skill's [skill.match]


def test_extract_to_store_grounds_and_merges():
    store, rejected = extract_to_store([_SKILL], CannedModel({"default": _GOOD}),
                                       resolver=lambda ref: ref == "GetLongField")
    assert len(store) == 1 and rejected == []
    (item,) = store.values()
    assert item.tier == "candidate"
    # a candidate whose refs don't resolve is REJECTED (not stored)
    store2, rejected2 = extract_to_store([_SKILL], CannedModel({"default": _GOOD}),
                                         resolver=lambda ref: False)
    assert store2 == {} and len(rejected2) == 1


def test_extract_to_store_is_idempotent_on_re_extract():
    """content-derived ids are stable, so re-extracting over the prior store keeps the first (setdefault)
    and never duplicates — the docstring's merge contract."""
    def resolver(ref):
        return ref == "GetLongField"
    store1, _ = extract_to_store([_SKILL], CannedModel({"default": _GOOD}), resolver=resolver)
    store2, rejected2 = extract_to_store([_SKILL], CannedModel({"default": _GOOD}), resolver=resolver,
                                         existing=store1)
    assert store2 == store1 and rejected2 == []       # same store, no new candidates, no growth
    assert len(store2) == 1


class _BoomModel:
    """A model whose completion always fails (mimics a live GatewayModel timeout)."""
    def complete(self, prompt: str) -> str:
        raise TimeoutError("gateway timed out")


def test_extract_to_store_skips_a_skill_whose_model_call_fails(capsys):
    """One skill's model failure must NOT abort the batch or lose the survivors of other skills."""
    good = {"id": "other-skill", "guidance": "Signature: x.\nFix: y.", "hint_apis": ["GetLongField"],
            "match": {"any_text": ["sigsegv"]}}

    class _MixedModel:                                 # boom on _SKILL (its guidance names nativePtr), good elsewhere
        def complete(self, prompt: str) -> str:
            if "nativePtr" in prompt:                  # unique to _SKILL's guidance
                raise TimeoutError("gateway timed out")
            return _GOOD

    store, rejected = extract_to_store([_SKILL, good], _MixedModel(),
                                       resolver=lambda ref: ref == "GetLongField")
    assert len(store) == 1                              # the second skill still contributed a candidate
    (item,) = store.values()
    assert item.provenance == "other-skill"
    assert "extraction failed" in capsys.readouterr().out
