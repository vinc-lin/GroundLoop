"""FixEvalRunner opt-in @base=fix^ checkout (hermetic, NO network). With base_checkout enabled the
case's fix stage runs against the real BASE (fix^) source and becomes gradeable (present + applying
patch); disabled, behavior is unchanged (empty worktree -> abstain)."""
import json
import subprocess
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import Patch, RepoRef, RepoScore, Signals, Ticket
from groundloop.eval.arms import Arm
from groundloop.eval.dataset import CaseRef
from groundloop.fixeval.runner import FixEvalRunner


def _git(args, cwd):
    cp = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    return cp


def _init_2commit_repo(root: Path) -> str:
    root.mkdir(parents=True)
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "fixeval-test"], root)
    (root / "foo.txt").write_text("BUG\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "base"], root)
    (root / "foo.txt").write_text("FIX\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "fix"], root)
    return _git(["rev-parse", "HEAD"], root).stdout.strip()


class _Idx:
    """Ranks repoA top-1 with a clear margin; localize retrieves foo.txt."""
    def rank_repos(self, signals, catalog):
        return [RepoScore(RepoRef("repoA"), 2.0), RepoScore(RepoRef("repoB"), 0.0)]

    def retrieve(self, repo, query):
        return ["foo.txt"]


class _Ext:
    def extract(self, logs, ticket):
        return Signals(classes=("Foo",))


class _Issues:
    def fetch(self, cid):
        return Ticket(id=cid, summary="s", description="d")


class _StubFixer:
    """Records the worktree it proposes against, and emits a clean-applying diff generated FROM that
    worktree's current (base) content. Empty patch when the target file is absent (empty worktree)."""
    def __init__(self, target="foo.txt"):
        self.target = target
        self.seen = []
        self.model = None

    def propose(self, worktree, ticket, locations):
        self.seen.append(worktree.path)
        p = Path(worktree.path) / self.target
        if not p.is_file():
            return Patch(diff="", files=())
        old = p.read_text()
        p.write_text(old.replace("BUG", "FIXED"))
        diff = subprocess.run(["git", "-C", worktree.path, "diff"],
                              capture_output=True, text=True).stdout
        p.write_text(old)                     # restore so apply-check runs against base
        return Patch(diff=diff, files=(self.target,))


def _case(tmp_path, fix_sha) -> CaseRef:
    cdir = tmp_path / "ds" / "C-1"
    (cdir / "_oracle").mkdir(parents=True)
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "repoA", "owning_repo_sha": fix_sha,
         "expected_files": ["foo.txt"], "is_answerable": True}))
    return CaseRef(case_id="C-1", case_dir=str(cdir))


def _runner(tmp_path, repos_root, *, base_checkout):
    return FixEvalRunner(
        issues=_Issues(),
        estate=GitFixtureEstate(str(tmp_path / "empty_fixtures"), str(tmp_path / "work")),
        catalog=[RepoRef("repoA"), RepoRef("repoB")], tau_margin=0.0, tau_score=0.0,
        base_checkout=base_checkout, repos_root=str(repos_root),
        base_work_root=str(tmp_path / "_base"))


def test_base_checkout_enabled_makes_case_gradeable(tmp_path):
    repos_root = tmp_path / "repos"
    fix_sha = _init_2commit_repo(repos_root / "repoA")
    case = _case(tmp_path, fix_sha)
    fixer = _StubFixer()
    recs = _runner(tmp_path, repos_root, base_checkout=True).run(
        [case], [Arm("test", _Idx(), _Ext(), 0.0, 0.0)], fixer=fixer)
    r = recs[0]
    assert r.predicted_repo == "repoA"
    assert r.patch_emitted and r.patch_applies and not r.abstained
    # propose ran against the BASE (fix^) worktree: present + buggy content
    used = Path(fixer.seen[-1])
    assert "_base" in used.parts and "C-1" in used.parts
    assert (used / "foo.txt").read_text() == "BUG\n"


def test_base_checkout_disabled_is_unchanged(tmp_path):
    repos_root = tmp_path / "repos"
    fix_sha = _init_2commit_repo(repos_root / "repoA")
    case = _case(tmp_path, fix_sha)
    fixer = _StubFixer()
    recs = _runner(tmp_path, repos_root, base_checkout=False).run(
        [case], [Arm("test", _Idx(), _Ext(), 0.0, 0.0)], fixer=fixer)
    r = recs[0]
    # empty estate worktree -> no real source -> abstain (today's behavior), NOT the base checkout
    assert r.predicted_repo == "repoA" and not r.patch_emitted and r.abstained
    used = Path(fixer.seen[-1])
    assert "_base" not in used.parts
    assert not (used / "foo.txt").is_file()


def test_base_checkout_failsafe_bad_sha_falls_back(tmp_path):
    # a bogus owning_repo_sha -> checkout_base returns None -> exactly the disabled behavior
    repos_root = tmp_path / "repos"
    _init_2commit_repo(repos_root / "repoA")
    case = _case(tmp_path, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    fixer = _StubFixer()
    recs = _runner(tmp_path, repos_root, base_checkout=True).run(
        [case], [Arm("test", _Idx(), _Ext(), 0.0, 0.0)], fixer=fixer)
    assert recs[0].abstained and not recs[0].patch_emitted
    assert "_base" not in Path(fixer.seen[-1]).parts
