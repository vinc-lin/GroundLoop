from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from groundloop.core.types import RepoRef, WorkTree

if TYPE_CHECKING:  # avoid a runtime package import cycle; the real import is lazy in materialize()
    from groundloop.run.record import MaterializeOutcome


class MockEstate:
    """Fleet catalog + a materialize() that provisions a throwaway work-tree dir (real corpus later)."""

    def __init__(self, catalog_path: str, work_root: str):
        self.catalog_path = Path(catalog_path)
        self.work_root = Path(work_root)

    def catalog(self) -> list[RepoRef]:
        return [RepoRef(r["name"]) for r in json.loads(self.catalog_path.read_text())]

    def materialize(self, repo: RepoRef) -> WorkTree:
        p = self.work_root / repo.name
        p.mkdir(parents=True, exist_ok=True)
        return WorkTree(repo=repo, path=str(p))


class GitFixtureEstate:
    """Hermetic @base materializer: copy a checked-in plain-file repo snapshot into a fresh tmp
    work-tree and synthesize a SINGLE-COMMIT git repo (the docs §3 anti-leak recipe in miniature —
    no upstream history/tags to mine). Makes `git apply --check` meaningful. A repo with no snapshot
    → an empty dir (which drives the honest localize/apply abstain)."""

    def __init__(self, fixtures_root: str, work_root: str):
        self.fixtures_root = Path(fixtures_root)
        self.work_root = Path(work_root)

    def catalog(self):
        return []

    def materialize(self, repo: RepoRef) -> WorkTree:
        dst = self.work_root / repo.name
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        src = self.fixtures_root / repo.name
        if src.is_dir():
            # Exclude the source .git: a real clone (not a plain-file snapshot) carries committed history
            # that the fresh `git init` below would sit on top of, so `git add -A`/`commit -m base` then
            # fails "nothing to commit" (check=True). Ignoring .git guarantees a clean single base commit;
            # a no-op for plain-file fixtures (no .git present).
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            for args in (["init", "-q"], ["config", "user.email", "t@t"],
                         ["config", "user.name", "fixeval"], ["add", "-A"],
                         ["commit", "-q", "-m", "base"]):
                subprocess.run(["git", "-C", str(dst), *args], check=True)
        return WorkTree(repo=repo, path=str(dst))


class RecordingEstate:
    """A RepoEstate decorator: delegates catalog()/materialize() to an inner estate and records a
    MaterializeOutcome (present, n_files) per materialize so the offline grader can judge fix
    gradeability without re-reading disk. Pure adapter — no core edit."""

    def __init__(self, inner):
        self.inner = inner
        self._outcomes: dict[str, "MaterializeOutcome"] = {}

    def catalog(self):
        return self.inner.catalog()

    def materialize(self, repo: RepoRef) -> WorkTree:
        from groundloop.run.record import MaterializeOutcome
        wt = self.inner.materialize(repo)
        d = Path(wt.path)
        n = 0
        if d.is_dir():
            for _ in d.rglob("*"):                 # capped: we only need present vs empty + a small count
                n += 1
                if n >= 2:                          # >=1 real entry beyond an empty dir is enough signal
                    break
        self._outcomes[repo.name] = MaterializeOutcome(repo=repo.name, path=str(d),
                                                       present=n > 0, n_files=n)
        return wt

    def outcome_for(self, name: str):
        return self._outcomes.get(name)


class CheckoutEstate(MockEstate):
    """Catalog from catalog.json (MockEstate) + a materialize() that checks out a plain-file repo
    snapshot from <fixtures_root>/<repo> into a fresh work-tree and git-inits it (the GitFixtureEstate
    recipe). No snapshot -> empty dir (honest localize/apply abstain). For `gloop run --repos`."""

    def __init__(self, catalog_path: str, fixtures_root: str, work_root: str):
        super().__init__(catalog_path, work_root)
        self.fixtures_root = Path(fixtures_root)

    def materialize(self, repo: RepoRef) -> WorkTree:
        dst = self.work_root / repo.name
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True)
        src = self.fixtures_root / repo.name
        if src.is_dir():
            # Exclude the source .git: a real clone (not a plain-file snapshot) carries committed history
            # that the fresh `git init` below would sit on top of, so `git add -A`/`commit -m base` then
            # fails "nothing to commit" (check=True). Ignoring .git guarantees a clean single base commit;
            # a no-op for plain-file fixtures (no .git present).
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "run"],
                      ["add", "-A"], ["commit", "-q", "-m", "base"]):
                subprocess.run(["git", "-C", str(dst), *a], check=True)
        return WorkTree(repo=repo, path=str(dst))
