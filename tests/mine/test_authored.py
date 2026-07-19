"""Anti-fabrication validator for hand-authored Tier-B cases.

An *authored* case (unlike a mined one) is typed by hand against real fleet source, so the risk is
fabricated grounding: claiming a file/symbol exists (or a log/ticket stays leak-safe) when it doesn't,
or a fix.diff that looks plausible but doesn't actually apply / only "fixes" a comment.
`validate_authored_case` checks every oracle field against the real repo tree and returns problem
strings (empty = valid). Fixture repo: tests/fixtures/authored_repo/demo-lib/.

The git-apply-check is validated against a REAL git checkout (not just a bare directory), so every
test builds one via the `repo_root` fixture: it copies the demo-lib fixture source into tmp_path and
commits it, then hands validate_authored_case that tmp git checkout as repo_root.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from groundloop.mine.authored import validate_authored_case

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "authored_repo"


@pytest.fixture
def repo_root(tmp_path):
    """A real git checkout of the demo-lib fixture under tmp_path/repo_root/demo-lib.

    validate_authored_case's git-apply-check needs a real `.git` to run `git apply --check` against;
    the on-disk fixture at FIXTURES_ROOT is deliberately NOT a git repo (it's just source-of-truth
    content), so each test copies it into a fresh tmp git checkout and commits it.
    """
    dest_root = tmp_path / "repo_root"
    dest = dest_root / "demo-lib"
    shutil.copytree(FIXTURES_ROOT / "demo-lib", dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=dest, check=True,
    )
    return dest_root


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
@@ -1,7 +1,8 @@
 #include <stddef.h>

 int decode_frame(const unsigned char *buf, int len) {
+    if (buf == NULL) return -1;  /* decode_frame: guard against a NULL frame buffer */
     int header = buf[0];      /* deref: crashes if buf is NULL */
     if (header < 0 || len <= 0) return -1;
     return header + len;
 }
"""

# Hunk header claims 7 old-lines / 8 new-lines but the body only supplies 6 — git apply --check
# hits EOF before satisfying the declared counts and reports a corrupt/inapplicable patch. This is
# the "hunk-offset defect" class: a diff that reads plausibly but was never actually verified against
# the real file.
BAD_APPLY_DIFF = """--- a/src/decoder.c
+++ b/src/decoder.c
@@ -1,7 +1,8 @@
 #include <stddef.h>

 int decode_frame(const unsigned char *buf, int len) {
+    if (buf == NULL) return -1;  /* decode_frame: guard against a NULL frame buffer */
     int header = buf[0];      /* deref: crashes if buf is NULL */
"""

# Applies clean, but the only added line referencing the required_api is a pure comment — the "fix"
# doesn't actually touch real code.
COMMENT_ONLY_API_DIFF = """--- a/src/decoder.c
+++ b/src/decoder.c
@@ -1,7 +1,8 @@
 #include <stddef.h>

 int decode_frame(const unsigned char *buf, int len) {
+    // decode_frame here
     int header = buf[0];      /* deref: crashes if buf is NULL */
     if (header < 0 || len <= 0) return -1;
     return header + len;
 }
"""


def _write_case(tmp_path, name, *, ticket=None, oracle=None, fix_diff=None):
    d = tmp_path / name
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps(ticket if ticket is not None else GOOD_TICKET))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle if oracle is not None else GOOD_ORACLE))
    (d / "fix.diff").write_text(fix_diff if fix_diff is not None else GOOD_DIFF)
    return d


def test_good_case_is_valid(tmp_path, repo_root):
    good_dir = _write_case(tmp_path, "good")
    assert validate_authored_case(good_dir, repo_root) == []


def test_missing_expected_file_is_flagged(tmp_path, repo_root):
    oracle = dict(GOOD_ORACLE, expected_files=["src/missing.c"])
    bad_dir = _write_case(tmp_path, "bad-missing-file", oracle=oracle)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("src/missing.c" in p for p in problems)


def test_missing_required_api_is_flagged(tmp_path, repo_root):
    oracle = dict(GOOD_ORACLE, required_apis=["no_such_fn"])
    bad_dir = _write_case(tmp_path, "bad-missing-api", oracle=oracle)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("no_such_fn" in p for p in problems)


def test_ungrounded_log_is_flagged(tmp_path, repo_root):
    ticket = json.loads(json.dumps(GOOD_TICKET))
    ticket["logs"] = [{"path": "logs/crash.txt", "kind": "native", "content": "some unrelated text"}]
    bad_dir = _write_case(tmp_path, "bad-ungrounded-log", ticket=ticket)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("log" in p.lower() for p in problems)


def test_owning_repo_leak_is_flagged(tmp_path, repo_root):
    ticket = json.loads(json.dumps(GOOD_TICKET))
    ticket["description"] = "App crashes decoding a frame in demo-lib."
    bad_dir = _write_case(tmp_path, "bad-leak", ticket=ticket)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("leak" in p.lower() for p in problems)


def test_owning_repo_leak_via_ticket_id_is_flagged(tmp_path, repo_root):
    ticket = json.loads(json.dumps(GOOD_TICKET))
    ticket["id"] = "demo-lib-1"
    bad_dir = _write_case(tmp_path, "bad-leak-id", ticket=ticket)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("leak" in p.lower() for p in problems)


def test_fix_diff_touching_wrong_file_is_flagged(tmp_path, repo_root):
    diff = """--- a/src/other.c
+++ b/src/other.c
@@ -1,2 +1,3 @@
 int other(void) {
+    return 0;
     return 1;
"""
    bad_dir = _write_case(tmp_path, "bad-fix-wrong-file", fix_diff=diff)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("fix" in p.lower() or "diff" in p.lower() for p in problems)


def test_fix_diff_that_does_not_apply_is_flagged(tmp_path, repo_root):
    """A diff whose hunk header line counts don't match its body can't `git apply --check` clean —
    this is the hunk-offset defect class: a diff that reads plausibly but was never verified against
    the real file (e.g. authored against a stale/misremembered copy)."""
    bad_dir = _write_case(tmp_path, "bad-does-not-apply", fix_diff=BAD_APPLY_DIFF)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("apply" in p.lower() for p in problems)


def test_required_api_only_in_comment_is_flagged(tmp_path, repo_root):
    """The diff applies clean and touches the expected file, but the only added line mentioning the
    required_api is a pure comment (`// decode_frame here`) — no real code was changed."""
    bad_dir = _write_case(tmp_path, "bad-api-comment-only", fix_diff=COMMENT_ONLY_API_DIFF)
    problems = validate_authored_case(bad_dir, repo_root)
    assert problems
    assert any("comment" in p.lower() for p in problems)
