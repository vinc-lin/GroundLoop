"""clone_fleet fetches each repo at its pinned SHA (or reports one already present)."""
from __future__ import annotations

from groundloop.build.clone_fleet import clone_fleet, FleetRepo, CloneResult


def _repo(tmp_path, name, sha="cafe1234"):
    return FleetRepo(name=name, url=f"https://example.test/{name}.git",
                     sha=sha, dest=str(tmp_path / name))


def test_clones_missing_repo_and_reports_sha(tmp_path):
    r = _repo(tmp_path, "a", sha="deadbeef")
    calls = []

    def fake_git(repo):
        calls.append(repo.name)
        return CloneResult(repo.name, "cloned", repo.sha)

    results = clone_fleet([r], jobs=1, runner=fake_git)

    assert calls == ["a"]
    assert results["a"].status == "cloned"
    assert results["a"].sha == "deadbeef"


def test_present_repo_is_not_recloned(tmp_path):
    r = _repo(tmp_path, "a")

    def fake_git(repo):
        # runner decides present vs cloned; here simulate "already present"
        return CloneResult(repo.name, "present", "existingsha")

    results = clone_fleet([r], jobs=1, runner=fake_git)
    assert results["a"].status == "present"
    assert results["a"].sha == "existingsha"


def test_clone_failure_is_isolated(tmp_path):
    good, bad = _repo(tmp_path, "good"), _repo(tmp_path, "bad")

    def fake_git(repo):
        if repo.name == "bad":
            return CloneResult(repo.name, "failed", "", "network down")
        return CloneResult(repo.name, "cloned", repo.sha)

    results = clone_fleet([good, bad], jobs=2, runner=fake_git)
    assert results["good"].status == "cloned"
    assert results["bad"].status == "failed"
    assert "network down" in results["bad"].detail


def test_default_runner_reports_present_for_existing_checkout(tmp_path):
    # A dir with a .git subdir is treated as already present (no network).
    dest = tmp_path / "a"
    (dest / ".git").mkdir(parents=True)
    from groundloop.build.clone_fleet import _default_git_runner
    r = FleetRepo(name="a", url="https://example.test/a.git", sha="", dest=str(dest))
    # Should not raise and should classify as present (rev-parse may fail on a bare
    # .git skeleton, but status must be 'present', never 'cloned').
    res = _default_git_runner(r)
    assert res.status == "present"
