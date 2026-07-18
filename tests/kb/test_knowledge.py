"""Round-trip + defaulting contract for the knowledge store (Phase A, distilled KB).
Mirrors tests/kb/test_provenance.py: save->load equals, tuple fields survive JSON, missing file is an
empty store, unknown keys dropped + id defaulted from the dict key."""
import json

from groundloop.kb.knowledge import Knowledge, KnowledgePlaybook, load_knowledge, save_knowledge


def _knowledge() -> Knowledge:
    return Knowledge(
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
    k = _knowledge()
    p = tmp_path / "knowledge.json"
    save_knowledge(str(p), {k.id: k})
    back = load_knowledge(str(p))
    assert back == {k.id: k}
    # grounding_refs must survive JSON (list) -> tuple reconstruction, else frozen equality fails
    assert isinstance(back[k.id].grounding_refs, tuple)


def test_missing_file_is_empty_store(tmp_path):
    assert load_knowledge(str(tmp_path / "nope.json")) == {}


def _playbook() -> KnowledgePlaybook:
    return KnowledgePlaybook(
        id="fragment-view-after-destroy-npe",
        applies_when={"any_text": ["onDestroyView"], "any_errors": ["NullPointerException"]},
        signature="NPE on a view/binding; stack through Fragment.onDestroyView; "
                   "a callback fires after teardown",
        localize=("onDestroyView", "retained listener/handler/coroutine fields"),
        fix=("null out the ViewBinding in onDestroyView", "cancel the async callback post-teardown"),
        required_apis=("onDestroyView", "Job.cancel"),
        grounding_refs=("onDestroyView", "Job.cancel"),
        provenance="fragment-view-after-destroy-npe", tier="candidate",
        evidence={"measured_lift": {}, "wilson95": None, "validating_case_ids": [], "fail_count": 0,
                  "demotions": []},
    )


def test_playbook_save_then_load_round_trips_all_fields(tmp_path):
    k = _playbook()
    p = tmp_path / "knowledge.json"
    save_knowledge(str(p), {k.id: k})
    back = load_knowledge(str(p))
    assert back == {k.id: k}
    for tf in ("localize", "fix", "required_apis", "grounding_refs"):
        assert isinstance(getattr(back[k.id], tf), tuple)


def test_unknown_keys_dropped_and_id_defaulted(tmp_path):
    p = tmp_path / "knowledge.json"
    p.write_text(json.dumps({
        "c1": {"applies_when": {"any_text": ["anr"]}, "type": "localize_hint",
               "content": "Look in the foreground-service start path.", "grounding_refs": ["startForeground"],
               "provenance": "foreground-service-not-started", "tier": "candidate", "evidence": {},
               "bogus": 123}}))          # id omitted in the body; 'bogus' is unknown
    back = load_knowledge(str(p))
    assert back["c1"].id == "c1"                          # id defaulted from the dict key
    assert not hasattr(back["c1"], "bogus")              # unknown key dropped
    assert back["c1"].grounding_refs == ("startForeground",)
