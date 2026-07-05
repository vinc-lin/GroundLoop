import subprocess
from pathlib import Path

from groundloop.fixeval.patch import patch_applies


def _git_worktree(tmp_path, rel, content):
    d = tmp_path / "wt"
    (d / Path(rel).parent).mkdir(parents=True)
    (d / rel).write_text(content)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(d), *args], check=True)
    return str(d)


def test_patch_applies_true_false(tmp_path):
    wt = _git_worktree(tmp_path, "x/A.cpp", "// bug\n")
    good = "--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+// fixed\n"
    assert patch_applies(good, wt) is True
    bad = "--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-nonexistent context\n+// fixed\n"
    assert patch_applies(bad, wt) is False
    assert patch_applies("", wt) is False
