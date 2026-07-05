"""Unified-diff parsing + apply-check for the fix-loop eval. Pure/oracle-free; ported from the
knowledgeLoop eval extract.py (docs/downstream-fix-loop.md §1)."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

_FENCE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)\n```", re.S)
_DIFF_START = re.compile(r"(?m)^(diff --git |--- )")


def extract_unified_diff(text: str) -> str:
    """Pull a unified diff from model output: the FIRST fenced block whose body is diff-shaped
    (an LLM may show 'before' code in an earlier fence, then the real fix in a later ```diff);
    else, if no fence is diff-shaped, from the first bare `diff --git`/`--- ` header to end.
    Returns "" when no diff is found."""
    if not text:
        return ""
    for m in _FENCE.finditer(text):                     # first diff-shaped fence (not just the first fence)
        if _DIFF_START.search(m.group(1)):
            return m.group(1).strip("\n")
    m2 = _DIFF_START.search(text)                        # unfenced diff → to end of text
    return text[m2.start():].strip("\n") if m2 else ""


def touched_files(diff: str) -> list[str]:
    """Repo-relative paths from `+++ b/<path>` headers (b/ stripped), in order, deduped."""
    out: list[str] = []
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            p = norm_path(ln[4:].split("\t", 1)[0].strip())
            if p and p not in out:
                out.append(p)
    return out


def added_lines(diff: str) -> list[str]:
    """Content of `+` lines, excluding the `+++` file header."""
    return [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


def references_api(diff: str, api: str) -> bool:
    """Whole-word `\\bapi\\b` over ADDED lines only."""
    pat = re.compile(rf"\b{re.escape(api)}\b")
    return any(pat.search(ln) for ln in added_lines(diff))


def norm_path(p: str) -> str:
    """Normalize a diff/oracle path to a bare repo-relative form: strip ONE leading a/ or b/,
    then a leading ./, and collapse //. (Single-strip so a real path like 'a/b/foo' keeps 'b/foo'.)"""
    p = p.strip()
    if p.startswith(("a/", "b/")):
        p = p[2:]
    if p.startswith("./"):
        p = p[2:]
    return re.sub(r"/+", "/", p)


def patch_applies(diff: str, worktree_path: str) -> bool:
    """True iff `diff` applies cleanly against the tree at worktree_path (git apply --check).
    Empty diff => False. LF + --whitespace=nowarn (WSL-safe). git-only, oracle-free."""
    if not diff.strip():
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False, newline="\n") as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
        patch_file = fh.name
    try:
        cp = subprocess.run(["git", "-C", worktree_path, "apply", "--check",
                             "--whitespace=nowarn", patch_file],
                            capture_output=True, text=True)
        return cp.returncode == 0
    finally:
        Path(patch_file).unlink(missing_ok=True)
