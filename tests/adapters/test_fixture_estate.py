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
