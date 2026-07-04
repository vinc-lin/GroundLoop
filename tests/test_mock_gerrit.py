import json
from pathlib import Path
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.jira import MockJira
from groundloop.core.types import RepoRef, Patch, Ticket


def test_submit_makes_changeid_and_bind_writes_ledger(tmp_path):
    (tmp_path / "GP-1").mkdir()
    (tmp_path / "GP-1" / "ticket.json").write_text(json.dumps({"id": "GP-1", "summary": "s", "description": "d"}))
    jira = MockJira(str(tmp_path))
    ger = MockGerrit(str(tmp_path / "changes.jsonl"), jira)
    ch = ger.submit(RepoRef("android-gpuimage-plus"), Patch("diff", ("f.cpp",)), Ticket("GP-1", "s", "d"))
    assert ch.change_id.startswith("I") and len(ch.change_id) == 41 and "GP-1" in ch.commit_subject
    ch2 = ger.submit(RepoRef("android-gpuimage-plus"), Patch("diff", ("f.cpp",)), Ticket("GP-1", "s", "d"))
    assert ch2.change_id == ch.change_id                       # deterministic (content-hashed)
    ger.bind(ch, Ticket("GP-1", "s", "d"))
    rows = [json.loads(x) for x in Path(tmp_path / "changes.jsonl").read_text().splitlines()]
    assert any(r.get("change_id") == ch.change_id and r.get("ticket") == "GP-1" for r in rows)
    ledger = (tmp_path / "GP-1" / "ledger.jsonl").read_text()
    assert "Resolved" in ledger                                 # bind transitioned the ticket
