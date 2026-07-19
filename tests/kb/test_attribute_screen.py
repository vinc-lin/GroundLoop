"""Cheap oracle-blind per-item archive screen (Phase C2). Fixture archive = plan payloads shaped exactly
like fixeval/archive.archive_plans output (fired_knowledge + outcome.groundedness/patch_applies). Asserts
the pinned fired-vs-non-fired screen_lift over the 0.5*groundedness + 0.5*patch_applies composite shortlists
BOTH promising and suspicious items, skips no-contrast items, and that load_archive tolerates a missing
dir + malformed files."""
import json

from groundloop.kb.attribute import load_archive, screen_knowledge
from groundloop.kb.knowledge import Knowledge


def _payload(case, fired, groundedness):
    return {"schema": 1, "case_id": case, "arm": "membership+logs", "predicted_repo": "r",
            "plan": {"steps": []}, "fired_skills": [], "fired_knowledge": list(fired),
            "outcome": {"groundedness": groundedness, "replans": 0, "abstained": False,
                        "patch_emitted": True, "patch_applies": True}}


def _knowledge(kid):
    return Knowledge(id=kid, applies_when={"any_text": ["x"]}, signature="c", fix=("c",),
                     grounding_refs=(), provenance="p", tier="candidate", evidence={})


def test_screen_shortlists_promising_and_suspicious():
    archive = [_payload("a", ["c-good"], 0.9), _payload("b", ["c-good"], 0.8),
               _payload("c", ["c-bad"], 0.1), _payload("d", ["c-bad"], 0.2),
               _payload("e", [], 0.5), _payload("f", [], 0.5)]
    knowledge = {"c-good": _knowledge("c-good"), "c-bad": _knowledge("c-bad")}
    sl = screen_knowledge(archive, knowledge, threshold=0.1)
    assert set(sl) == {"c-good", "c-bad"}          # high-lift (promising) AND negative-lift (suspicious)


def test_threshold_filters_weak_signal():
    archive = [_payload("a", ["c1"], 0.55), _payload("b", [], 0.5)]   # composite lift = +0.025 (patch True)
    assert screen_knowledge(archive, {"c1": _knowledge("c1")}, threshold=0.1) == []
    assert screen_knowledge(archive, {"c1": _knowledge("c1")}, threshold=0.0) == ["c1"]


def test_no_contrast_item_is_skipped():
    archive = [_payload("a", ["c1"], 0.9), _payload("b", ["c1"], 0.9)]  # c1 fires everywhere -> no baseline
    assert screen_knowledge(archive, {"c1": _knowledge("c1")}, threshold=0.0) == []


def test_load_archive_reads_payloads_and_tolerates_junk(tmp_path):
    d = tmp_path / "plans"
    d.mkdir()
    (d / "a__arm.json").write_text(json.dumps(_payload("a", ["c1"], 0.5)))
    (d / "b__arm.json").write_text(json.dumps(_payload("b", ["c2"], 0.4)))
    (d / "broken.json").write_text("{ not json")
    got = load_archive(str(d))
    assert {p["case_id"] for p in got} == {"a", "b"}       # malformed file skipped, not fatal


def test_load_archive_missing_dir_is_empty():
    assert load_archive("/no/such/plans/dir") == []


def test_screen_skips_retired_knowledge():
    # a retired item with lingering fired_knowledge in the archive must NOT consume a LOFO/--max-lofo slot.
    archive = [_payload("a", ["c1"], 0.9), _payload("b", [], 0.2)]         # strong contrast on paper
    retired = Knowledge(id="c1", applies_when={"any_text": ["x"]}, signature="c", fix=("c",),
                        grounding_refs=(), provenance="p", tier="retired", evidence={})
    assert screen_knowledge(archive, {"c1": retired}, threshold=0.0) == []    # retired never shortlisted


def test_screen_all_equal_signal_still_shortlisted_at_zero_threshold():
    archive = [_payload("a", ["c1"], 0.5), _payload("b", [], 0.5)]         # identical composite -> lift 0.0
    assert screen_knowledge(archive, {"c1": _knowledge("c1")}, threshold=0.0) == ["c1"]  # >= keeps a 0.0 lift


def test_screen_min_fired_zero_does_not_crash():
    archive = [_payload("a", [], 0.5)]                                     # c1 never fires -> fv empty
    assert screen_knowledge(archive, {"c1": _knowledge("c1")}, threshold=0.0, min_fired=0) == []   # no ZeroDiv


def test_screen_catches_patch_applies_lift_without_groundedness():
    # c1 fires where the patch APPLIES; the non-firing baseline does not apply — groundedness is FLAT (0.5).
    archive = [{"case_id": "a", "fired_knowledge": ["c1"],
                "outcome": {"groundedness": 0.5, "patch_applies": True}},
               {"case_id": "b", "fired_knowledge": [],
                "outcome": {"groundedness": 0.5, "patch_applies": False}}]
    # groundedness-only lift = 0.0 (would be filtered at threshold 0.1); the composite lifts via patch_applies.
    assert screen_knowledge(archive, {"c1": _knowledge("c1")}, threshold=0.1) == ["c1"]
