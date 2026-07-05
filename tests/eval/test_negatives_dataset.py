import json
from pathlib import Path

from groundloop.eval.dataset import CaseRef, load_eval_oracle
from groundloop.eval.dataset import case_catalog


def _write_case(root: Path, cid: str, oracle: dict) -> CaseRef:
    d = root / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d", "logs": []}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle))
    return CaseRef(case_id=cid, case_dir=str(d))


def test_load_eval_oracle_reads_negative_fields(tmp_path):
    case = _write_case(tmp_path, "neg-1", {
        "owning_repo": "__OUT_OF_FLEET__", "is_answerable": False,
        "negative_class": "out_of_fleet", "expected_files": []})
    ev = load_eval_oracle(case)
    assert ev.is_answerable is False
    assert ev.negative_class == "out_of_fleet"
    assert ev.owning_repo == "__OUT_OF_FLEET__"


def test_load_eval_oracle_defaults_positive(tmp_path):
    case = _write_case(tmp_path, "pos-1", {"owning_repo": "cameraview", "expected_files": ["a.kt"]})
    ev = load_eval_oracle(case)
    assert ev.is_answerable is True and ev.negative_class is None
    assert ev.expected_files == ("a.kt",)


def test_case_catalog_reads_per_case_override(tmp_path):
    d = tmp_path / "oof-1"
    d.mkdir()
    (d / "ticket.json").write_text(json.dumps({"id": "oof-1", "logs": []}))
    (d / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "cameraview"}]))
    cat = case_catalog(CaseRef(case_id="oof-1", case_dir=str(d)))
    assert [r.name for r in cat] == ["organicmaps", "cameraview"]


def test_case_catalog_absent_returns_none(tmp_path):
    d = tmp_path / "pos-1"
    d.mkdir()
    (d / "ticket.json").write_text(json.dumps({"id": "pos-1", "logs": []}))
    assert case_catalog(CaseRef(case_id="pos-1", case_dir=str(d))) is None
