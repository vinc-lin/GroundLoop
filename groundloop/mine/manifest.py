"""Committed e2e case manifest — the version-controlled recipe + oracle for the realistic
end-to-end corpus, one entry per case (docs/environments.md: eval datasets live off-repo; this
manifest is the small, reproducible seed that regenerates them via `gh` + git at pinned SHAs).

Deliberately NOT here: diffs/patches/logs/any bulky payload. Those stay off-repo, regenerable from
this manifest's (repo, issue/pr numbers+urls, base/fix SHAs) recipe fields plus the (owning_repo,
expected_files, required_apis) oracle fields.

TOML in, TOML out: stdlib `tomllib` reads (Python 3.11+, matches `groundloop/build/corpus.py`);
`tomli_w` isn't a project dependency, so writing uses a small hand-rolled deterministic serializer
(safe here — every field is a str/int/list-of-str, no floats/datetimes/nested tables to escape).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class E2ECase:
    repo: str
    issue_number: int
    issue_url: str
    pr_number: int
    pr_url: str
    base_sha: str
    fix_sha: str
    owning_repo: str
    expected_files: tuple[str, ...]
    required_apis: tuple[str, ...]


_STR_FIELDS = ("repo", "issue_url", "pr_url", "base_sha", "fix_sha", "owning_repo")
_INT_FIELDS = ("issue_number", "pr_number")
_LIST_FIELDS = ("expected_files", "required_apis")


def _toml_str(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_str(i) for i in items) + "]"


def write_manifest(cases: list[E2ECase], path: str | Path) -> None:
    """Serialize `cases` to `path` as a TOML array-of-tables (`[[case]]`), sorted by
    `(repo, issue_number)` for a byte-identical, order-independent output (no wall-clock/random
    fields exist on `E2ECase`, so sorting is the only determinism lever needed)."""
    ordered = sorted(cases, key=lambda c: (c.repo, c.issue_number))
    lines = [
        "# Realistic end-to-end eval corpus — recipe + oracle only (bulky data off-repo).",
        "# populate: gloop mine --require-crash-log --require-merged-fix ...",
    ]
    for c in ordered:
        lines.append("")
        lines.append("[[case]]")
        for f in _STR_FIELDS:
            lines.append(f"{f} = {_toml_str(getattr(c, f))}")
        for f in _INT_FIELDS:
            lines.append(f"{f} = {getattr(c, f)}")
        for f in _LIST_FIELDS:
            lines.append(f"{f} = {_toml_list(getattr(c, f))}")
    text = "\n".join(lines) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def load_manifest(path: str | Path) -> list[E2ECase]:
    """Parse a manifest written by `write_manifest` back into `E2ECase`s (lists -> tuples so
    round-trip equality holds against the frozen dataclass)."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    field_names = {f.name for f in fields(E2ECase)}
    out: list[E2ECase] = []
    for row in data.get("case", []):
        kwargs = {k: v for k, v in row.items() if k in field_names}
        for f in _LIST_FIELDS:
            if f in kwargs:
                kwargs[f] = tuple(kwargs[f])
        out.append(E2ECase(**kwargs))
    return out
