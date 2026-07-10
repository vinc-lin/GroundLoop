"""Lightweight per-repo TEXT profile store: embed cheap, always-available repo text (README,
manifest namespace/applicationId, module & package identifiers) with bge-m3 into a SMALL atlas.db
(kind='profile' units). This is NOT the 12 GB code atlas — the identical builder runs in production.
Anti-leak: reads only public repo text, never a case oracle (see the red-test)."""
from __future__ import annotations

import os
import re

from groundloop.engines.atlas.store import Store, Unit

_NS = re.compile(r'(?:namespace|applicationId)\s*[=(]?\s*["\']([\w.]+)["\']')
_SKIP_DIRS = {".git", "build", "node_modules"}


def gather_repo_texts(repo_root: str, *, max_chunks: int = 120) -> list[str]:
    """Assemble bounded profile chunks: READMEs + manifest namespace/applicationId (primary) +
    shallowest module/package path identifiers (secondary), capped at max_chunks. Skips vendor dirs."""
    readmes: list[str] = []
    manifests: list[str] = []
    segs: list[str] = []
    for base, _dirs, files in os.walk(repo_root):
        _dirs[:] = [d for d in _dirs if d not in _SKIP_DIRS]      # prune the walk (don't descend)
        rel = os.path.relpath(base, repo_root)
        seg = rel.replace(os.sep, " ").replace("-", " ").replace("_", " ").strip()
        if seg and seg != ".":
            segs.append(seg)                                     # module/package path identifiers
        for fn in files:
            low = fn.lower()
            if low.startswith("readme"):
                try:
                    readmes.append(open(os.path.join(base, fn), encoding="utf-8",
                                        errors="ignore").read()[:4000])
                except OSError:
                    pass
            elif low.startswith("build.gradle") or low == "androidmanifest.xml":
                try:
                    txt = open(os.path.join(base, fn), encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                manifests += _NS.findall(txt)

    def _dedup(xs: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for x in xs:
            x = x.strip()
            if x:
                seen.setdefault(x, None)
        return list(seen)

    readmes, manifests, segs = _dedup(readmes), _dedup(manifests), _dedup(segs)
    segs.sort(key=lambda s: len(s.split()))                       # shallowest paths first
    out = readmes + manifests + segs
    return out[:max_chunks] or [os.path.basename(repo_root.rstrip("/")) or repo_root]


def build_text_profiles(profiles: dict[str, list[str]], dest_db: str, embedder) -> str:
    """Embed each repo's text chunks and write a small profile atlas.db keyed by repo."""
    store = Store(dest_db)
    for repo, chunks in profiles.items():
        chunks = [c for c in chunks if c and c.strip()] or [repo]     # never leave a repo empty
        vecs = embedder.embed(chunks)
        units = [Unit(repo=repo, kind="profile", name=f"{repo}#{i}", qualified_name=None,
                      file=None, repo_head="profile", text=chunk, meta={})
                 for i, chunk in enumerate(chunks)]
        store.reindex_repo(repo, list(zip(units, vecs)), repo_head="profile")
    return dest_db
