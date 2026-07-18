import json
from pathlib import Path
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.record import RunRecordIO, MaterializeOutcome, ORACLE_KEYS


def _rec():
    patch = Patch(diff="--- a/x.kt\n+++ b/x.kt\n@@ -1 +1 @@\n-a\n+b\n", files=("x.kt",))
    return RunRecord(
        ticket_id="GEI-1",
        ranked=[RepoScore(RepoRef("engineering"), 0.9, ("ev",)), RepoScore(RepoRef("other"), 0.1)],
        chosen=RepoRef("engineering"), locations=["x.kt", "y.kt"], patch=patch,
        change=Change(change_id="gl-1", commit_subject="fix", ticket_id="GEI-1", patch=patch),
        bound=True, events=["intake", "match"])


def test_roundtrip(tmp_path):
    mo = MaterializeOutcome(repo="engineering", path="/w/engineering", present=True, n_files=3)
    p = tmp_path / "runs" / "GEI-1.json"
    RunRecordIO.write(str(p), _rec(), materialize=mo, match_arm="component", patch_applies=True)
    doc = RunRecordIO.read(str(p))
    assert doc.ticket_id == "GEI-1"
    assert doc.chosen == "engineering"
    assert doc.ranked[0]["repo"] == "engineering" and doc.ranked[0]["score"] == 0.9
    assert doc.locations == ["x.kt", "y.kt"]
    assert doc.patch["files"] == ["x.kt"]
    assert doc.patch_applies is True
    assert doc.match_arm == "component"
    assert doc.materialize.present is True and doc.materialize.n_files == 3


def test_record_marks_bind_as_mock(tmp_path):
    mo = MaterializeOutcome(repo="engineering", path="/w/engineering", present=True, n_files=3)
    p = tmp_path / "runs" / "GEI-1.json"
    RunRecordIO.write(str(p), _rec(), materialize=mo, match_arm="component",
                      patch_applies=True, bind_kind="mock")
    doc = RunRecordIO.read(str(p))
    assert doc.bind_kind == "mock"
    raw = json.loads(p.read_text())
    assert raw["bind_kind"] == "mock"


def test_record_carries_no_oracle(tmp_path):
    p = tmp_path / "runs" / "GEI-1.json"
    RunRecordIO.write(str(p), _rec(), materialize=MaterializeOutcome("engineering", "/w", False, 0),
                      match_arm="flood", patch_applies=False)
    blob = json.loads(Path(p).read_text())
    text = json.dumps(blob).lower()
    for k in ORACLE_KEYS:
        assert k not in blob
    assert "owning_repo" not in text and "expected_files" not in text
