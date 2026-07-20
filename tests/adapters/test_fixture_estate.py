import subprocess
from pathlib import Path

from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import RepoRef

FIX = Path(__file__).parent.parent / "fixtures" / "repos"
REL = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


def test_materialize_synthesizes_single_commit_repo(tmp_path):
    est = GitFixtureEstate(str(FIX), str(tmp_path / "work"))
    wt = est.materialize(RepoRef("android-gpuimage-plus"))
    assert (Path(wt.path) / REL).is_file()
    log = subprocess.run(["git", "-C", wt.path, "log", "--oneline"], capture_output=True, text=True)
    assert len(log.stdout.strip().splitlines()) == 1
    tags = subprocess.run(["git", "-C", wt.path, "tag"], capture_output=True, text=True)
    assert tags.stdout.strip() == ""


def test_missing_repo_yields_empty_dir(tmp_path):
    est = GitFixtureEstate(str(FIX), str(tmp_path / "work"))
    wt = est.materialize(RepoRef("no-such-repo"))
    assert Path(wt.path).is_dir() and not any(Path(wt.path).iterdir())


def test_materialize_ignores_source_git_and_makes_clean_base(tmp_path):
    """A src that is a REAL clone (carries .git with committed history) must still yield a clean single
    `base` commit — the source .git is excluded, so `git init`+`add -A`+`commit -m base` does not fail
    'nothing to commit' (check=True). Without the ignore, materialize would raise CalledProcessError."""
    fixtures = tmp_path / "fixtures"
    src = fixtures / "cloned-repo"
    src.mkdir(parents=True)
    (src / "file.txt").write_text("hello")
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-q", "-m", "orig"]):
        subprocess.run(["git", "-C", str(src), *a], check=True)
    assert (src / ".git").is_dir()                                    # src is a real clone
    est = GitFixtureEstate(str(fixtures), str(tmp_path / "work"))
    wt = est.materialize(RepoRef("cloned-repo"))                       # must NOT raise
    assert (Path(wt.path) / "file.txt").is_file()
    log = subprocess.run(["git", "-C", wt.path, "log", "--oneline"], capture_output=True, text=True)
    lines = log.stdout.strip().splitlines()
    assert len(lines) == 1 and lines[0].endswith("base")              # a fresh single base, not the copied "orig"
