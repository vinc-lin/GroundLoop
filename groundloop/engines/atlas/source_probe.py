"""Source-grep symbol existence — the authoritative fallback for symbols the atlas index may
under-index. Product-level and shared: the eval oracle and the feedback verifier both use it
(no eval coupling). `repo_tokens` builds the identifier set once (efficient for many lookups);
`symbol_in_source` is the per-symbol convenience wrapper."""
from __future__ import annotations

import os
import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SRC_EXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".java", ".kt",
            ".js", ".ts", ".jsx", ".tsx", ".py", ".go", ".rs", ".m", ".mm")
_SKIP_DIRS = {".git", "node_modules", "build", ".venv", "__pycache__", "dist"}


def repo_tokens(repo_path: str) -> set:
    """Every identifier token in the repo's source files (one walk). Unreadable files are skipped;
    `.git`/build/vendor dirs are pruned."""
    toks: set = set()
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(_SRC_EXT):
                try:
                    with open(os.path.join(root, fn), errors="ignore") as fh:
                        toks.update(_IDENT.findall(fh.read()))
                except OSError:
                    pass
    return toks


def symbol_in_source(repo_path: str, name: str) -> bool:
    """True iff the (unqualified) `name` appears as an identifier anywhere under `repo_path`.
    A qualified `A::b` is checked by its last segment. Empty name -> False. Rebuilds the token set
    per call — use `repo_tokens` directly when checking many symbols."""
    if not name:
        return False
    return name.split("::")[-1] in repo_tokens(repo_path)
