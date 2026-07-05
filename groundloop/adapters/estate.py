from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from groundloop.core.types import RepoRef, WorkTree


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
            shutil.copytree(src, dst, dirs_exist_ok=True)
            for args in (["init", "-q"], ["config", "user.email", "t@t"],
                         ["config", "user.name", "fixeval"], ["add", "-A"],
                         ["commit", "-q", "-m", "base"]):
                subprocess.run(["git", "-C", str(dst), *args], check=True)
        return WorkTree(repo=repo, path=str(dst))
