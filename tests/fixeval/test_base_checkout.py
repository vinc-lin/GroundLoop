"""Hermetic tests for the Dev-Labs @base=fix^ materializer (groundloop/fixeval/base_checkout).
Full-history path only — NO network. The shallow-clone `git fetch` path is gated/live."""
import subprocess
from pathlib import Path

from groundloop.fixeval.base_checkout import checkout_base


def _git(args, cwd):
    cp = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    return cp


def _init_2commit_repo(root: Path) -> str:
    """Build a 2-commit history: commit1 'base' (foo.txt=BUG), commit2 'fix' (foo.txt=FIX).
    Returns the FIX commit sha. Full history (no shallow boundary)."""
    root.mkdir(parents=True)
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "fixeval-test"], root)
    src = root / "src"
    src.mkdir()
    (src / "foo.txt").write_text("BUG\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "base"], root)
    (src / "foo.txt").write_text("FIX\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "fix"], root)
    return _git(["rev-parse", "HEAD"], root).stdout.strip()


def test_full_history_checks_out_base_content(tmp_path):
    repo = tmp_path / "clone"
    fix_sha = _init_2commit_repo(repo)
    dest = tmp_path / "base"
    out = checkout_base(str(repo), fix_sha, str(dest))
    assert out == str(dest)
    # @base = fix^ = commit1 -> the BUGGY content, NOT the fix
    assert (dest / "src" / "foo.txt").read_text() == "BUG\n"


def test_dest_is_a_git_repo_so_git_apply_check_works(tmp_path):
    # patch_applies() shells `git -C <dest> apply --check`, which needs a real work-tree.
    repo = tmp_path / "clone"
    fix_sha = _init_2commit_repo(repo)
    dest = tmp_path / "base"
    checkout_base(str(repo), fix_sha, str(dest))
    assert (dest / ".git").exists()
    cp = subprocess.run(["git", "-C", str(dest), "rev-parse", "--is-inside-work-tree"],
                        capture_output=True, text=True)
    assert cp.returncode == 0 and cp.stdout.strip() == "true"


def test_bogus_sha_returns_none_no_raise_no_network(tmp_path):
    repo = tmp_path / "clone"
    _init_2commit_repo(repo)          # no `origin` remote -> fetch fails locally, never hits network
    dest = tmp_path / "base"
    out = checkout_base(str(repo), "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", str(dest))
    assert out is None
    assert not dest.exists()          # cleaned up on failure


def test_missing_source_returns_none(tmp_path):
    assert checkout_base(str(tmp_path / "nope"), "abcabcabc", str(tmp_path / "d")) is None


def test_empty_sha_returns_none(tmp_path):
    repo = tmp_path / "clone"
    _init_2commit_repo(repo)
    assert checkout_base(str(repo), "", str(tmp_path / "d")) is None


def test_dest_preexisting_is_replaced(tmp_path):
    repo = tmp_path / "clone"
    fix_sha = _init_2commit_repo(repo)
    dest = tmp_path / "base"
    dest.mkdir()
    (dest / "stale.txt").write_text("stale\n")
    checkout_base(str(repo), fix_sha, str(dest))
    assert not (dest / "stale.txt").exists()
    assert (dest / "src" / "foo.txt").read_text() == "BUG\n"
