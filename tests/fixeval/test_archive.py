# tests/fixeval/test_archive.py
import json
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.archive import archive_plans


def _rec(case_id, plan):
    return FixRecord(case_id=case_id, arm="plan", predicted_repo="r", locations=[], patch_diff="",
                     patch_files=[], patch_emitted=bool(plan), patch_applies=bool(plan),
                     abstained=not plan, abstain_reason=None, refine_iters=0, cost_usd=0.0,
                     plan=plan, groundedness=1.0 if plan else None, replans=0)


def test_archive_writes_only_planned_cases(tmp_path):
    recs = [_rec("c1", {"root_cause": "rc", "targets": []}), _rec("c2", None)]
    n = archive_plans(recs, str(tmp_path))
    assert n == 1
    files = list((tmp_path / "plans").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["case_id"] == "c1" and payload["outcome"]["patch_applies"] is True
    assert payload["schema"] == 1


def test_archive_sanitizes_slashed_case_id(tmp_path):
    recs = [_rec("owner/repo#1", {"root_cause": "rc", "targets": []})]
    n = archive_plans(recs, str(tmp_path))
    assert n == 1
    files = list((tmp_path / "plans").glob("*.json"))
    assert len(files) == 1 and "/" not in files[0].name       # no path escape / crash
    assert json.loads(files[0].read_text())["case_id"] == "owner/repo#1"   # id preserved in payload


def test_archive_planless_only_creates_no_dir(tmp_path):
    n = archive_plans([_rec("c1", None), _rec("c2", None)], str(tmp_path))
    assert n == 0
    assert not (tmp_path / "plans").exists()
