"""Round-trip + defaulting contract for the KB provenance sidecar (Phase B, GATED on Phase-A accept)."""
import json
from pathlib import Path

from groundloop.kb.provenance import (
    SIDECAR_PATH,
    ProvenanceRecord,
    load_sidecar,
    save_sidecar,
)


def _full_record() -> ProvenanceRecord:
    return ProvenanceRecord(
        id="native-null-deref-segv",
        tier="validated",
        lineage="cold-start-author",
        validating_case_ids=("case-001", "case-017"),
        measured_lift={"phi_1.0": 0.31, "resolved_delta": 0.12, "proxy": True},
        evidence_context={"atlas_sha": "abc123", "embed": "bge-m3", "date": "2026-07-06"},
        fail_count=2,
        demotions=("2026-07-06:validated->applied",),
        leak_check="clean",
    )


def test_save_then_load_round_trips_all_fields(tmp_path):
    rec = _full_record()
    p = tmp_path / "provenance.json"
    save_sidecar(str(p), {rec.id: rec})
    back = load_sidecar(str(p))
    assert back == {rec.id: rec}
    # tuple fields must survive JSON (list) -> tuple reconstruction, else equality would fail
    assert isinstance(back[rec.id].validating_case_ids, tuple)
    assert isinstance(back[rec.id].demotions, tuple)


def test_missing_optional_fields_default_and_unknown_ignored(tmp_path):
    p = tmp_path / "prov.json"
    p.write_text(
        json.dumps(
            {
                "skill-x": {
                    "id": "skill-x",
                    "tier": "candidate",
                    "lineage": "harvest",
                    "validating_case_ids": ["c1"],
                    "measured_lift": {},
                    "evidence_context": {},
                    "future_field": "should-be-ignored",  # unknown key -> dropped, not crash
                }
            }
        ),
        encoding="utf-8",
    )
    rec = load_sidecar(str(p))["skill-x"]
    assert rec.fail_count == 0
    assert rec.demotions == ()
    assert rec.leak_check == ""
    assert not hasattr(rec, "future_field")


def test_missing_file_returns_empty(tmp_path):
    assert load_sidecar(str(tmp_path / "does-not-exist.json")) == {}


def test_record_is_frozen():
    rec = _full_record()
    try:
        rec.tier = "canonical"  # type: ignore[misc]
    except Exception as e:  # FrozenInstanceError is an AttributeError subclass
        assert e.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("ProvenanceRecord must be frozen")


def test_default_sidecar_path_points_at_kb_data():
    p = Path(SIDECAR_PATH)
    assert p.name == "provenance.json"
    assert p.parent.name == "data"
    assert p.parent.parent.name == "kb"
