"""Cheap oracle-blind per-claim archive screen (Phase C2). Fixture archive = plan payloads shaped exactly
like fixeval/archive.archive_plans output (fired_claims + outcome.groundedness). Asserts the pinned
fired-vs-non-fired groundedness-delta formula shortlists BOTH promising and suspicious claims, skips
no-contrast claims, and that load_archive tolerates a missing dir + malformed files."""
import json

from groundloop.kb.attribute import load_archive, screen_claims
from groundloop.kb.claim import Claim


def _payload(case, fired, groundedness):
    return {"schema": 1, "case_id": case, "arm": "membership+logs", "predicted_repo": "r",
            "plan": {"steps": []}, "fired_skills": [], "fired_claims": list(fired),
            "outcome": {"groundedness": groundedness, "replans": 0, "abstained": False,
                        "patch_emitted": True, "patch_applies": True}}


def _claim(cid):
    return Claim(id=cid, applies_when={"any_text": ["x"]}, type="fix_step", content="c",
                 grounding_refs=(), provenance="p", tier="candidate", evidence={})


def test_screen_shortlists_promising_and_suspicious():
    archive = [_payload("a", ["c-good"], 0.9), _payload("b", ["c-good"], 0.8),
               _payload("c", ["c-bad"], 0.1), _payload("d", ["c-bad"], 0.2),
               _payload("e", [], 0.5), _payload("f", [], 0.5)]
    claims = {"c-good": _claim("c-good"), "c-bad": _claim("c-bad")}
    sl = screen_claims(archive, claims, threshold=0.1)
    assert set(sl) == {"c-good", "c-bad"}          # high-lift (promising) AND negative-lift (suspicious)


def test_threshold_filters_weak_signal():
    archive = [_payload("a", ["c1"], 0.55), _payload("b", [], 0.5)]   # lift = +0.05
    assert screen_claims(archive, {"c1": _claim("c1")}, threshold=0.1) == []
    assert screen_claims(archive, {"c1": _claim("c1")}, threshold=0.0) == ["c1"]


def test_no_contrast_claim_is_skipped():
    archive = [_payload("a", ["c1"], 0.9), _payload("b", ["c1"], 0.9)]  # c1 fires everywhere -> no baseline
    assert screen_claims(archive, {"c1": _claim("c1")}, threshold=0.0) == []


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
