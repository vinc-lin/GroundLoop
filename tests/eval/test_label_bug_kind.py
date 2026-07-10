import json
from pathlib import Path

from groundloop.eval.label_bug_kind import stamp_bug_kind


def _case(root, cid, oracle):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle))
    return d


def test_stamp_crash_when_fault_frame_present(tmp_path):
    _case(tmp_path, "crash1", {"owning_repo": "oboe", "fault_frame": "a.B.c"})
    _case(tmp_path, "func1", {"owning_repo": "newpipe"})
    n = stamp_bug_kind(str(tmp_path))
    assert n == 2
    crash = json.loads((tmp_path / "crash1" / "_oracle" / "oracle.json").read_text())
    func = json.loads((tmp_path / "func1" / "_oracle" / "oracle.json").read_text())
    assert crash["bug_kind"] == "crash"
    assert func["bug_kind"] == "functional"


def test_stamp_is_idempotent_and_preserves_keys(tmp_path):
    _case(tmp_path, "c", {"owning_repo": "oboe", "expected_files": ["x.java"], "fault_frame": "a.B.c"})
    stamp_bug_kind(str(tmp_path))
    stamp_bug_kind(str(tmp_path))
    o = json.loads((tmp_path / "c" / "_oracle" / "oracle.json").read_text())
    assert o["bug_kind"] == "crash" and o["expected_files"] == ["x.java"]


def test_cli_label_bugkind(tmp_path, capsys):
    from groundloop.cli import main
    _case(tmp_path, "c", {"owning_repo": "oboe", "fault_frame": "a.B.c"})
    assert main(["label-bugkind", "--dataset", str(tmp_path)]) == 0
    assert "stamped 1" in capsys.readouterr().out
