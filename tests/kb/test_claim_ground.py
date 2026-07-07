"""Oracle-blind ground-check for candidate Claims (Phase A2). Hermetic: a fake resolver stands in for the
atlas; the leak red-test runs against the REAL FLEET_OWNER_TOKENS denylist (kb/validate.owner_denylist)."""
from groundloop.kb.claim import Claim
from groundloop.kb.claim_ground import atlas_resolver, check_claim_grounded


def _claim(**over) -> Claim:
    base = dict(id="c-guard", applies_when={"any_text": ["sigsegv"]}, type="fix_step",
                content="Reject a 0 handle at native method entry before dereferencing it.",
                grounding_refs=("GetLongField", "reinterpret_cast"),
                provenance="native-null-deref-segv", tier="candidate", evidence={})
    base.update(over)
    return Claim(**base)


def _resolver(known):
    s = set(known)
    return lambda ref: ref in s


def test_grounded_when_all_refs_resolve_and_no_leak():
    chk = check_claim_grounded(_claim(), _resolver(["GetLongField", "reinterpret_cast"]))
    assert chk.grounded is True
    assert chk.reasons == ()
    assert set(chk.resolved_refs) == {"GetLongField", "reinterpret_cast"}


def test_unresolved_ref_is_not_grounded():
    chk = check_claim_grounded(_claim(), _resolver(["GetLongField"]))     # reinterpret_cast missing
    assert chk.grounded is False
    assert chk.missing_refs == ("reinterpret_cast",)
    assert any(r.startswith("unresolved_refs:") for r in chk.reasons)


def test_owner_token_leak_is_rejected():
    # "exoplayer" is a media3 owner slug in FLEET_OWNER_TOKENS -> a leak even though the ref resolves.
    c = _claim(content="Guard the ExoPlayer native peer handle.", grounding_refs=("GetLongField",))
    chk = check_claim_grounded(c, _resolver(["GetLongField"]))
    assert chk.grounded is False
    assert "exoplayer" in chk.leak_tokens


def test_bad_type_and_empty_content_flagged():
    chk = check_claim_grounded(_claim(type="bogus", content="  "),
                               _resolver(["GetLongField", "reinterpret_cast"]))
    assert chk.grounded is False
    assert any(r.startswith("bad_type:") for r in chk.reasons)
    assert "empty_content" in chk.reasons


def test_empty_grounding_refs_not_grounded():
    chk = check_claim_grounded(_claim(grounding_refs=()), _resolver([]))
    assert chk.grounded is False
    assert "no_grounding_refs" in chk.reasons


def test_atlas_resolver_wraps_keyword_search():
    class FakeStore:                                  # stands in for engines/atlas/store.Store
        def __init__(self, hits): self.hits = set(hits)
        def keyword_search(self, query, k=1, repos=None, kinds=None):
            return [("unit", 0.0)] if query in self.hits else []
    resolve = atlas_resolver(FakeStore({"GetLongField"}))
    assert resolve("GetLongField") is True
    assert resolve("DoesNotExist") is False
    assert resolve("") is False
