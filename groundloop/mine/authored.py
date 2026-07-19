"""Anti-fabrication validator for hand-authored Tier-B cases (labs — never imported by product runtime).

Hand-authored cases (crash log -> owning repo -> files -> fix, typed by a human against real fleet
source) carry a risk mined cases don't: a fabricated oracle field — a file/symbol/diff hunk that
sounds plausible but doesn't actually exist in the repo. `validate_authored_case` checks every oracle
field against the REAL source tree on disk and returns a list of problem strings (empty = valid).
Stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _slug_variants(owning_repo: str) -> set[str]:
    return {owning_repo, owning_repo.lower(), owning_repo.replace("-", ""), owning_repo.replace("-", "_")}


def validate_authored_case(case_dir: Path, repo_root: Path) -> list[str]:
    """Ground every oracle field of an authored case against real source under repo_root.

    case_dir layout: ticket.json, _oracle/oracle.json, fix.diff (path given by oracle["fix_patch"]).
    repo_root: the directory CONTAINING the owning repo (i.e. repo_root/owning_repo/... is the tree).
    Returns a list of problem strings; empty list = the case is grounded.
    """
    case_dir = Path(case_dir)
    repo_root = Path(repo_root)
    problems: list[str] = []

    ticket = json.loads((case_dir / "ticket.json").read_text())
    oracle = json.loads((case_dir / "_oracle" / "oracle.json").read_text())

    owning_repo = oracle.get("owning_repo", "")
    expected_files = list(oracle.get("expected_files", []))
    required_apis = list(oracle.get("required_apis", []))

    # 1. exists: each expected_file must be a real file in the real repo tree.
    existing_file_texts: list[str] = []
    for rel in expected_files:
        f = repo_root / owning_repo / rel
        if not f.is_file():
            problems.append(f"expected_file not found in real source: {owning_repo}/{rel}")
        else:
            existing_file_texts.append(f.read_text())

    # 2. api present: each required_api must appear in the text of SOME existing expected file.
    for api in required_apis:
        if not any(api in text for text in existing_file_texts):
            problems.append(f"required_api not found in real source: {api}")

    # 3. log grounds: the crash log must name at least one oracle symbol (an API or an expected-file
    # basename) — otherwise the log is disconnected from the rest of the oracle (ungrounded).
    log_text = "\n".join(lg.get("content", "") for lg in ticket.get("logs", []))
    basenames = [Path(rel).name for rel in expected_files]
    if not any(sym in log_text for sym in required_apis + basenames):
        problems.append("crash log names no oracle symbol (ungrounded)")

    # 4. leak-safe: the owning_repo name must never leak into the ticket text (summary/description/logs).
    text_blob = "\n".join([ticket.get("summary", ""), ticket.get("description", ""), log_text])
    if owning_repo:
        variants = _slug_variants(owning_repo)
        if any(v and v.lower() in text_blob.lower() for v in variants):
            problems.append(f"owning_repo name leaks into the ticket: {owning_repo}")

    # 5. fix targets: fix.diff must touch an expected_file and reference a required_api on an added line.
    fix_path = case_dir / oracle.get("fix_patch", "fix.diff")
    if fix_path.is_file():
        diff_text = fix_path.read_text()
        diff_paths = set()
        for m in re.finditer(r"(?m)^(?:\+\+\+|---) (.+)$", diff_text):
            p = m.group(1).strip()
            if p.startswith("a/") or p.startswith("b/"):
                p = p[2:]
            diff_paths.add(p)

        def _touches_expected(p: str) -> bool:
            pname = Path(p).name
            for rel in expected_files:
                if pname == Path(rel).name or p.endswith(rel) or rel.endswith(p):
                    return True
            return False

        if not any(_touches_expected(p) for p in diff_paths):
            problems.append("fix.diff does not touch any expected_file")

        added_lines = [ln for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        added_text = "\n".join(added_lines)
        if required_apis and not any(api in added_text for api in required_apis):
            problems.append("fix.diff does not reference any required_api on an added line")

    return problems
