"""Anti-fabrication validator for hand-authored Tier-B cases.

An *authored* case (unlike a mined one) is typed by hand against real fleet source, so the risk is
fabricated grounding: claiming a file/symbol exists (or a log/ticket stays leak-safe) when it doesn't.
`validate_authored_case` checks every oracle field against the real repo tree and returns problem
strings (empty = valid). Fixture repo: tests/fixtures/authored_repo/demo-lib/.
"""
import json
from pathlib import Path

from groundloop.mine.authored import validate_authored_case

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "authored_repo"

GOOD_TICKET = {
    "id": "demo-1",
    "summary": "Native crash decoding a frame",
    "description": "App crashes on a malformed frame.",
    "component": "",
    "status": "Open",
    "comments": [],
    "logs": [{
        "path": "logs/crash.txt",
        "kind": "native",
        "content": "F DEBUG: #00 pc 00001a2b  /system/lib/libdemo.so (decode_frame+18)",
    }],
}

GOOD_ORACLE = {
    "owning_repo": "demo-lib",
    "expected_files": ["src/decoder.c"],
    "required_apis": ["decode_frame"],
    "fix_patch": "fix.diff",
    "owning_repo_sha": "deadbeef",
    "is_answerable": True,
    "bug_kind": "crash",
}

GOOD_DIFF = """--- a/src/decoder.c
+++ b/src/decoder.c
@@ -1,6 +1,7 @@
 #include <stddef.h>
 int decode_frame(const unsigned char *buf, int len) {
+    if (buf == NULL) return -1;  /* decode_frame: guard against a NULL frame buffer */
     int header = buf[0];
"""


def _write_case(tmp_path, name, *, ticket=None, oracle=None, fix_diff=None):
    d = tmp_path / name
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps(ticket if ticket is not None else GOOD_TICKET))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle if oracle is not None else GOOD_ORACLE))
    (d / "fix.diff").write_text(fix_diff if fix_diff is not None else GOOD_DIFF)
    return d


def test_good_case_is_valid(tmp_path):
    good_dir = _write_case(tmp_path, "good")
    assert validate_authored_case(good_dir, FIXTURES_ROOT) == []


def test_missing_expected_file_is_flagged(tmp_path):
    oracle = dict(GOOD_ORACLE, expected_files=["src/missing.c"])
    bad_dir = _write_case(tmp_path, "bad-missing-file", oracle=oracle)
    problems = validate_authored_case(bad_dir, FIXTURES_ROOT)
    assert problems
    assert any("src/missing.c" in p for p in problems)


def test_missing_required_api_is_flagged(tmp_path):
    oracle = dict(GOOD_ORACLE, required_apis=["no_such_fn"])
    bad_dir = _write_case(tmp_path, "bad-missing-api", oracle=oracle)
    problems = validate_authored_case(bad_dir, FIXTURES_ROOT)
    assert problems
    assert any("no_such_fn" in p for p in problems)


def test_ungrounded_log_is_flagged(tmp_path):
    ticket = json.loads(json.dumps(GOOD_TICKET))
    ticket["logs"] = [{"path": "logs/crash.txt", "kind": "native", "content": "some unrelated text"}]
    bad_dir = _write_case(tmp_path, "bad-ungrounded-log", ticket=ticket)
    problems = validate_authored_case(bad_dir, FIXTURES_ROOT)
    assert problems
    assert any("log" in p.lower() for p in problems)


def test_owning_repo_leak_is_flagged(tmp_path):
    ticket = json.loads(json.dumps(GOOD_TICKET))
    ticket["description"] = "App crashes decoding a frame in demo-lib."
    bad_dir = _write_case(tmp_path, "bad-leak", ticket=ticket)
    problems = validate_authored_case(bad_dir, FIXTURES_ROOT)
    assert problems
    assert any("leak" in p.lower() for p in problems)


def test_owning_repo_leak_via_ticket_id_is_flagged(tmp_path):
    ticket = json.loads(json.dumps(GOOD_TICKET))
    ticket["id"] = "demo-lib-1"
    bad_dir = _write_case(tmp_path, "bad-leak-id", ticket=ticket)
    problems = validate_authored_case(bad_dir, FIXTURES_ROOT)
    assert problems
    assert any("leak" in p.lower() for p in problems)


def test_fix_diff_touching_wrong_file_is_flagged(tmp_path):
    diff = """--- a/src/other.c
+++ b/src/other.c
@@ -1,2 +1,3 @@
 int other(void) {
+    return 0;
     return 1;
"""
    bad_dir = _write_case(tmp_path, "bad-fix-wrong-file", fix_diff=diff)
    problems = validate_authored_case(bad_dir, FIXTURES_ROOT)
    assert problems
    assert any("fix" in p.lower() or "diff" in p.lower() for p in problems)
