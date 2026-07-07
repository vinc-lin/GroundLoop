"""Round-trip + defaulting contract for the claim store (Phase A, claim-centric distilled KB).
Mirrors tests/kb/test_provenance.py: save->load equals, tuple fields survive JSON, missing file is an
empty store, unknown keys dropped + id defaulted from the dict key."""
import json

from groundloop.kb.claim import Claim, load_claims, save_claims


def _claim() -> Claim:
    return Claim(
        id="native-null-deref-segv-fix_step-abc12345",
        applies_when={"any_text": ["sigsegv", "segv_maperr"]},
        type="fix_step",
        content="Reject a 0 nativePtr handle at native method entry before dereferencing it.",
        grounding_refs=("GetLongField", "std::weak_ptr::lock"),
        provenance="native-null-deref-segv",
        tier="candidate",
        evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [],
                  "fail_count": 0, "demotions": []},
    )


def test_save_then_load_round_trips_all_fields(tmp_path):
    c = _claim()
    p = tmp_path / "claims.json"
    save_claims(str(p), {c.id: c})
    back = load_claims(str(p))
    assert back == {c.id: c}
    # grounding_refs must survive JSON (list) -> tuple reconstruction, else frozen equality fails
    assert isinstance(back[c.id].grounding_refs, tuple)


def test_missing_file_is_empty_store(tmp_path):
    assert load_claims(str(tmp_path / "nope.json")) == {}


def test_unknown_keys_dropped_and_id_defaulted(tmp_path):
    p = tmp_path / "claims.json"
    p.write_text(json.dumps({
        "c1": {"applies_when": {"any_text": ["anr"]}, "type": "localize_hint",
               "content": "Look in the foreground-service start path.", "grounding_refs": ["startForeground"],
               "provenance": "foreground-service-not-started", "tier": "candidate", "evidence": {},
               "bogus": 123}}))          # id omitted in the body; 'bogus' is unknown
    back = load_claims(str(p))
    assert back["c1"].id == "c1"                          # id defaulted from the dict key
    assert not hasattr(back["c1"], "bogus")              # unknown key dropped
    assert back["c1"].grounding_refs == ("startForeground",)
