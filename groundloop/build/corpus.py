"""Load the shared corpus.toml (repo url + pinned sha) for the clone step."""
from __future__ import annotations

import tomllib


def load_corpus(path: str) -> dict[str, tuple[str, str]]:
    """Return {name: (url, sha)} for each [[repo]] in corpus.toml that has a url.

    A missing or placeholder sha ("" / "PIN_AT_CLONE") normalizes to "" — clone
    HEAD now, pin the resolved SHA afterward.
    """
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    out: dict[str, tuple[str, str]] = {}
    for r in data.get("repo", []):
        name = r.get("name")
        url = r.get("url", "")
        if not name or not url:
            continue
        sha = r.get("sha", "") or ""
        if sha == "PIN_AT_CLONE":
            sha = ""
        out[name] = (url, sha)
    return out
