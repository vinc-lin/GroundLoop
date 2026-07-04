from __future__ import annotations
import json
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
