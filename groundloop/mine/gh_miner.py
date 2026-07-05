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


def _should_hold_out(seq: int, frac: float) -> bool:
    """Deterministic hold-out sampler: every `stride`-th admitted-positive becomes an out_of_fleet
    negative (stride = round(1/frac)), so held-out cases are evenly spread across the run."""
    if frac <= 0:
        return False
    if frac >= 1:
        return True
    stride = max(2, round(1 / frac))
    return seq % stride == 0


def _owner_still_wins(leak_index, sanitized_desc, sanitized_logs, owning_repo, fleet_names) -> bool:
    """Closed-loop leak gate: run the real matcher over the SANITIZED text; if the true owner still
    ranks top-1, the scrub failed to hide the answer (grounding-over-narrative: trust the real index,
    not the scrub rules, to decide whether the owner is still identifiable).
    """
    from groundloop.core.types import LogAttachment, Ticket, RepoRef
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
    tk = Ticket(id="x", summary="", description=sanitized_desc)
    atts = tuple(LogAttachment(path=f"logs/{i}.txt", kind="other", content=b)
                 for i, b in enumerate(sanitized_logs))
    sig = AndroidSignalExtractor().extract(atts, tk)
    ranked = leak_index.rank_repos(sig, [RepoRef(n) for n in fleet_names])
    return bool(ranked) and ranked[0].repo.name == owning_repo and ranked[0].score > 0


def _oracle_for(cand: Candidate, repo_name: str, expected_files: list[str]) -> dict:
    row = owner_tokens_for(repo_name)
    return {
        "owning_repo": repo_name,
        "owner_namespaces": list(row["namespaces"]), "owner_slugs": list(row["slugs"]),
        "owner_sonames": list(row["sonames"]), "expected_files": expected_files,
        "owner_github_slug": cand.owning_slug,
        "fix_patch": "",  # E1-B v1 derives class/method from the issue text, not the diff body
    }


def mine(slugs: list[str], out: str, *, gh: Optional[Callable] = None, repo_name: str,
         fleet_names: list[str], limit: int = 200, max_files: int = 5, holdout_frac: float = 0.0,
         coverage_cutoff: str = "", leak_index=None) -> dict:
    """Mine one repo slug (repo_name = its short catalog name) into `out/`. Returns a report dict."""
    from groundloop.domains.android_ivi.owner_tokens import missing_owner_rows
    missing = missing_owner_rows([repo_name])
    if missing:
        raise ValueError(f"no FLEET_OWNER_TOKENS row for {missing}; cannot scrub its owner tells")
    report = {"harvested": 0, "dropped_filters": 0, "rejected_leak": 0, "bucketed": 0, "admitted": 0,
              "insufficient_signal": 0, "oof": 0, "coverage_gap": 0, "not_a_defect": 0}
    emit_catalog(out, fleet_names)
    kwargs = {"limit": limit} if gh is None else {"gh": gh, "limit": limit}
    answerable_seq = 0
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
            neg_class = None
            source_method = "github_linked_pr"
            owning = repo_name
            answerable = True
            held_out = None
            case_catalog_names = None

            verdict = admit(flags, sig)
            if verdict == "REJECT":
                report["rejected_leak"] += 1
                continue
            if verdict == "BUCKET_PROSE_ONLY":
                s_logs = []

            if leak_index is not None and _owner_still_wins(leak_index, s_desc, s_logs, repo_name, fleet_names):
                report["rejected_leak"] += 1     # grounding-over-narrative: the matcher can still ID the owner
                continue

            # classify the SURVIVING case (counters reflect emitted cases only)
            if verdict == "BUCKET_PROSE_ONLY":
                report["bucketed"] += 1
                report["insufficient_signal"] += 1
                neg_class = "insufficient_signal"
                source_method = "prose_only"
            else:
                answerable_seq += 1
                if coverage_cutoff and cand.merged_at and cand.merged_at > coverage_cutoff:
                    neg_class = "coverage_gap"
                    answerable = False
                    source_method = "temporal_gap"
                    report["coverage_gap"] += 1        # owning stays repo_name; NO per-case catalog
                elif _should_hold_out(answerable_seq, holdout_frac):
                    neg_class = "out_of_fleet"
                    answerable = False
                    held_out = repo_name
                    case_catalog_names = [n for n in fleet_names if n != repo_name]
                    source_method = "hold_out"
                    report["oof"] += 1
                else:
                    report["admitted"] += 1

            case = MinedCase(
                case_id=_opaque_id(slug, cand.issue_number), summary=s_summary, description=s_desc,
                logs=[{"kind": lg["kind"], "text": t} for lg, t in zip(logs, s_logs)],
                owning_repo=owning, expected_files=prod, required_apis=[],
                owning_repo_sha=cand.merge_commit_sha, is_answerable=answerable, negative_class=neg_class,
                held_out_repo=held_out, case_catalog=case_catalog_names,
                provenance={"issue": {"number": cand.issue_number, "url": cand.issue_url, "repo": slug},
                            "pr": {"number": cand.pr_number, "merge_commit_sha": cand.merge_commit_sha},
                            "link_method": "github_linked_pr", "created_at": cand.created_at,
                            "source_method": source_method},
                leakage={"leakage_flags": {k: v for k, v in flags.items() if k != "extractor_leak"},
                         "scrubber_version": "1.0.0"},
                raw={"issue": {"number": cand.issue_number, "title": cand.issue_title,
                               "body": cand.issue_body}, "pr_files": cand.files})
            emit_case(out, case)
    return report
