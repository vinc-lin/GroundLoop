"""Lightweight source-scan symbol indexer — build a matchable atlas WITHOUT CBM or produce.

Scans each repo's source for the tokens the Stage-1 matcher keys on (package/class/interface names,
`.so` library names), makes symbol `Unit`s, embeds their text via the (working) bge-m3 gateway, and
stores them with `Store.reindex_repo`. A reliable TEST substrate when CBM is slow/flaky and produce is
too slow (docs/type2-atlas-build-findings.md Finding 3, mitigation 3). The eval does not care how units
were produced — only that they exist and match ticket signals.
"""
from __future__ import annotations

import glob
import os
import re
from typing import Sequence

from groundloop.engines.atlas.registry import RepoEntry
from groundloop.engines.atlas.store import Store, Unit

_SRC_EXT = (".java", ".kt", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".mm")
_RE_PKG = re.compile(r"^\s*package\s+([\w.]+)", re.M)                 # Java/Kotlin package decl
_RE_TYPE = re.compile(r"\b(?:class|interface|object|enum|struct)\s+([A-Z][A-Za-z0-9_]+)")
_RE_SO = re.compile(r"\b(lib[A-Za-z0-9_]+\.so)\b")


def scan_repo(repo_path: str, repo_name: str, *, max_files: int = 6000) -> list[Unit]:
    """Distinct package/class/.so tokens across a repo's source, as symbol Units (text == token)."""
    seen: dict[str, tuple[str, str]] = {}      # qualified_name -> (kind, file)
    files: list[str] = []
    for ext in _SRC_EXT:
        files += glob.glob(os.path.join(repo_path, "**", f"*{ext}"), recursive=True)
    for fp in sorted(files)[:max_files]:
        try:
            src = open(fp, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        rel = os.path.relpath(fp, repo_path)
        mpkg = _RE_PKG.search(src)
        pkg = mpkg.group(1) if mpkg else None
        if pkg:
            seen.setdefault(pkg, ("package", rel))
        for m in _RE_TYPE.finditer(src):
            cls = m.group(1)
            qn = f"{pkg}.{cls}" if pkg else cls
            seen.setdefault(qn, ("class", rel))
            seen.setdefault(cls, ("class", rel))          # bare class name too (matches class signals)
        for m in _RE_SO.finditer(src):
            seen.setdefault(m.group(1), ("library", rel))
    return [Unit(repo=repo_name, kind=kind, name=qn.split(".")[-1], qualified_name=qn,
                 file=file, repo_head="lite", text=qn, meta={})
            for qn, (kind, file) in seen.items()]


def lite_index(entries: Sequence[RepoEntry], store: Store, embedder, *,
               batch: int = 256, on_repo=None) -> dict[str, int]:
    """Scan + embed + store each entry; returns {repo: unit_count}. `on_repo(name, n)` for progress."""
    counts: dict[str, int] = {}
    for e in entries:
        units = scan_repo(e.repo_path, e.name)
        vecs: list = []
        for i in range(0, len(units), batch):
            vecs += embedder.embed([u.text for u in units[i:i + batch]])
        store.reindex_repo(e.name, list(zip(units, vecs)), repo_head="lite")
        counts[e.name] = len(units)
        if on_repo:
            on_repo(e.name, len(units))
    return counts
