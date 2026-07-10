"""Offline: assemble a combined crash∪functional oracle dataset from multiple sources so one eval run
can report the two classes separately (via the scorecard's bug_kind split). COPIES case dirs (self-
contained; never mutates the sources), unions their catalogs, and stamps bug_kind. Offline-only."""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from groundloop.eval.label_bug_kind import stamp_bug_kind


def combine_oracles(sources: list[str], out: str, *, label: bool = True) -> dict:
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    existing = [d.name for d in outp.iterdir() if d.is_dir() and (d / "ticket.json").is_file()]
    if existing:
        raise ValueError(f"--out already has {len(existing)} case dir(s); use a fresh directory")
    repos: dict[str, dict] = {}                 # union catalog, deduped by name (insertion order)
    per_source: dict[str, int] = defaultdict(int)
    seen: dict[str, str] = {}                    # case_id -> source (collision guard)
    for src in sources:
        srcp = Path(src)
        cat = srcp / "catalog.json"
        if cat.is_file():
            for r in json.loads(cat.read_text()):
                repos.setdefault(r["name"], r)
        for d in sorted(srcp.iterdir()):
            if not (d.is_dir() and (d / "ticket.json").is_file()):
                continue
            cid = d.name
            if cid in seen:
                raise ValueError(f"case id collision: '{cid}' in both {seen[cid]} and {src}")
            seen[cid] = src
            shutil.copytree(d, outp / cid)
            per_source[src] += 1
    (outp / "catalog.json").write_text(json.dumps(list(repos.values()), indent=2, ensure_ascii=False))
    (outp / "dataset_meta.json").write_text(json.dumps(
        {"dataset_kind": "combined_oracle", "sources": list(sources)}, indent=2, ensure_ascii=False))
    labeled = stamp_bug_kind(str(outp)) if label else 0
    return {"cases": sum(per_source.values()), "per_source": dict(per_source),
            "repos": len(repos), "labeled": labeled}
