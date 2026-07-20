import json
from groundloop.adapters.mock.jira import MockJira


def _seed(tmp_path):
    case = tmp_path / "GP-1"
    (case / "logs").mkdir(parents=True)
    (case / "logs" / "crash.txt").write_text("boom org.wysaid.X")
    (case / "ticket.json").write_text(json.dumps({
        "id": "GP-1", "summary": "s", "description": "d", "component": "",
        "logs": [{"path": "logs/crash.txt", "kind": "logcat"}]}))
    return tmp_path


def test_fetch_loads_logs_and_writeback_appends_ledger(tmp_path):
    root = _seed(tmp_path)
    j = MockJira(str(root))
    t = j.fetch("GP-1")
    assert t.logs[0].content.startswith("boom") and t.logs[0].kind == "logcat" and t.component == ""
    j.post_comment("GP-1", "matched")
    j.transition("GP-1", "Resolved")
    ledger = (root / "GP-1" / "ledger.jsonl").read_text().strip().splitlines()
    assert any('"transition"' in ln and "Resolved" in ln for ln in ledger)


def test_fetch_tolerates_non_utf8_log_bytes(tmp_path):
    """A real logcat can carry non-UTF-8 bytes; fetch must not raise UnicodeDecodeError (errors='replace').
    Byte-identical for well-formed UTF-8; an invalid byte becomes U+FFFD rather than aborting intake."""
    case = tmp_path / "GP-2"
    (case / "logs").mkdir(parents=True)
    (case / "logs" / "crash.txt").write_bytes(b"boom \xad frame org.x")   # 0xad = invalid UTF-8
    (case / "ticket.json").write_text(json.dumps({
        "id": "GP-2", "summary": "s", "description": "d", "component": "",
        "logs": [{"path": "logs/crash.txt", "kind": "logcat"}]}))
    t = MockJira(str(tmp_path)).fetch("GP-2")            # must NOT raise
    assert t.logs[0].content.startswith("boom") and "�" in t.logs[0].content
