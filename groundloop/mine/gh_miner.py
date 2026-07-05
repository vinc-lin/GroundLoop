"""Miner orchestrator: harvest -> filter -> signal split -> scrub -> admit -> emit. `gloop mine`."""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for
from groundloop.mine.harvest import Candidate, harvest_repo
from groundloop.mine.filters import is_minable, production_files
from groundloop.mine.signal import split_issue_body
from groundloop.mine.scrub import build_owner_tokens, scrub, leakage_flags, admit
from groundloop.mine.emit import MinedCase, emit_case, emit_catalog


def _opaque_id(slug: str, num: int) -> str:
    """Owner-free stable case id (spec §1.3 item-6 BLOCKER: {repo}-{n} leaks the owner in the dir name)."""
    return "gl-" + hashlib.sha1(f"{slug}#{num}".encode()).hexdigest()[:12]


def _oracle_for(cand: Candidate, repo_name: str, expected_files: list[str]) -> dict:
    row = owner_tokens_for(repo_name)
    return {
        "owning_repo": repo_name,
        "owner_namespaces": list(row["namespaces"]), "owner_slugs": list(row["slugs"]),
        "owner_sonames": list(row["sonames"]), "expected_files": expected_files,
        "fix_patch": "",  # E1-B v1 derives class/method from the issue text, not the diff body
    }


def mine(slugs: list[str], out: str, *, gh: Optional[Callable] = None, repo_name: str,
         fleet_names: list[str], limit: int = 200, max_files: int = 5) -> dict:
    """Mine one repo slug (repo_name = its short catalog name) into `out/`. Returns a report dict."""
    report = {"harvested": 0, "dropped_filters": 0, "rejected_leak": 0, "bucketed": 0, "admitted": 0}
    emit_catalog(out, fleet_names)
    kwargs = {"limit": limit} if gh is None else {"gh": gh, "limit": limit}
    for slug in slugs:
        for cand in harvest_repo(slug, **kwargs):
            report["harvested"] += 1
            prod = production_files(cand.files)
            if not is_minable({"merged": True, "changed_files": cand.files_total,
                               "title": cand.issue_title}, cand.files, max_files=max_files):
                report["dropped_filters"] += 1
                continue
            prose, logs = split_issue_body(cand.issue_body)
            oracle = _oracle_for(cand, repo_name, prod)
            tok = build_owner_tokens(oracle)
            s_desc = scrub(prose, tok)
            s_summary = scrub(cand.issue_title, tok)
            s_logs = [scrub(lg["text"], tok) for lg in logs]
            flags, sig = leakage_flags(s_desc + "\n" + s_summary, s_logs, tok, repo_name)
            verdict = admit(flags, sig)
            if verdict == "REJECT":
                report["rejected_leak"] += 1
                continue
            if verdict == "BUCKET_PROSE_ONLY":
                report["bucketed"] += 1
                s_logs = []  # nothing matchable survived; keep prose-only
            case = MinedCase(
                case_id=_opaque_id(slug, cand.issue_number), summary=s_summary, description=s_desc,
                logs=[{"kind": lg["kind"], "text": t} for lg, t in zip(logs, s_logs)],
                owning_repo=repo_name, expected_files=prod, required_apis=[],
                owning_repo_sha=cand.merge_commit_sha, is_answerable=True,
                provenance={"issue": {"number": cand.issue_number, "url": cand.issue_url, "repo": slug},
                            "pr": {"number": cand.pr_number, "merge_commit_sha": cand.merge_commit_sha},
                            "link_method": "github_linked_pr", "created_at": cand.created_at},
                leakage={"leakage_flags": {k: v for k, v in flags.items() if k != "extractor_leak"},
                         "scrubber_version": "1.0.0"},
                raw={"issue": {"number": cand.issue_number, "title": cand.issue_title,
                               "body": cand.issue_body}, "pr_files": cand.files})
            emit_case(out, case)
            report["admitted"] += 1
    return report
