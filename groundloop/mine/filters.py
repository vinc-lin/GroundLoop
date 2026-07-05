"""Quality filters for mined issue↔PR pairs (docs/type2-evaluation.md §4.2)."""
from __future__ import annotations

import re

_PROD_ROOTS = ("src/main/", "app/src/main/", "library/src/main/")
_PROD_EXT = (".java", ".kt", ".cpp", ".cc", ".c", ".h", ".hpp", ".mm")
_EXCLUDE = ("/test/", "/androidtest/", "/src/test/", "/resources/mocks",
            "/testdata/", "/fixtures/", "/samples/")
_KEEP_STATUS = {"added", "modified", "renamed"}
_MERGE_RE = re.compile(r"^\s*(?:merge\b|revert\b|revert \")", re.I)


def production_files(files: list[dict]) -> list[str]:
    """Repo-relative production source paths from a PR /files payload (drops test/doc/build)."""
    out: list[str] = []
    for f in files:
        name = f.get("filename", "")
        low = name.lower()
        if f.get("status") not in _KEEP_STATUS:
            continue
        if not low.endswith(_PROD_EXT):
            continue
        if any(x in low for x in _EXCLUDE):
            continue
        if not (any(r in low for r in _PROD_ROOTS) or low.startswith("src/") or "/src/" in low):
            continue
        out.append(name)
    return out


def is_minable(pr: dict, files: list[dict], *, max_files: int = 5) -> bool:
    """Admit only a merged, single-concern PR that touches >=1 production file and <= max_files."""
    if not pr.get("merged"):
        return False
    if _MERGE_RE.match(pr.get("title", "")):
        return False
    if pr.get("changed_files", len(files)) > max_files:
        return False
    return len(production_files(files)) >= 1
