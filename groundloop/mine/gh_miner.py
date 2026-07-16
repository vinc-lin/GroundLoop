"""Miner orchestrator: harvest -> filter -> signal split -> scrub -> admit -> emit. `gloop mine`."""
from __future__ import annotations

import hashlib
import re
from typing import Callable, Optional

from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for
from groundloop.fix.patch import code_added_lines
from groundloop.mine.harvest import Candidate, fetch_commit_diff, harvest_repo
from groundloop.mine.filters import is_minable, production_files
from groundloop.mine.signal import split_issue_body
from groundloop.mine.scrub import build_owner_tokens, scrub, leakage_flags, admit
from groundloop.mine.emit import MinedCase, emit_case, emit_catalog

# Identifier immediately followed by '(' == a call/decl/constructor-type (mirrors scrub._DECL).
_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
# Language keywords / primitive-type names that trail a '(' but are NOT an API a fix "uses".
_API_STOPWORDS = {
    "if", "for", "while", "switch", "catch", "return", "new", "sizeof", "synchronized",
    "do", "else", "when", "try", "throw", "throws", "super", "this", "assert", "case", "yield",
    "public", "private", "protected", "static", "final", "abstract", "class", "interface", "enum",
    "void", "fun", "val", "var", "def", "lambda", "print", "println", "await", "async",
    "int", "long", "float", "double", "char", "bool", "boolean", "byte", "short",
    "str", "string", "list", "map", "set", "dict", "object", "array",
}
_API_MIN_LEN = 3
_API_CAP = 5


def required_apis_from_diff(diff: str, *, cap: int = _API_CAP) -> list[str]:
    """Derive a small, high-signal set of API references a correct fix must use, from the gold
    diff's ADDED CODE lines (comments/blanks excluded via `code_added_lines`).

    Heuristic — take 'call-like' identifiers: a name immediately followed by '(' (method/function
    calls, `obj.method(` targets, and the TYPE in a `new Type(...)` constructor); this mirrors the
    scrubber's decl regex. Then drop language keywords / primitive-type names (case-insensitive) and
    trivially short tokens (< 3 chars), dedup preserving first-seen order, and cap at `cap` (5).
    Conservative by design: the aim is a meaningful resolved_rate GATE, not every token. By
    construction each returned api is a whole-word on an added code line, so
    `references_api_code(diff, api)` is True for the gold diff (a candidate fix is then scored on
    whether IT references them)."""
    out: list[str] = []
    for ln in code_added_lines(diff):
        for m in _CALL.finditer(ln):
            tok = m.group(1)
            if len(tok) < _API_MIN_LEN or tok.lower() in _API_STOPWORDS or tok in out:
                continue
            out.append(tok)
            if len(out) >= cap:
                return out
    return out


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


def _oracle_for(cand: Candidate, repo_name: str, expected_files: list[str],
                *, fix_patch: str = "") -> dict:
    row = owner_tokens_for(repo_name)
    return {
        "owning_repo": repo_name,
        "owner_namespaces": list(row["namespaces"]), "owner_slugs": list(row["slugs"]),
        "owner_sonames": list(row["sonames"]), "expected_files": expected_files,
        "owner_github_slug": cand.owning_slug,
        "fix_patch": fix_patch,  # the fetched gold merge-commit diff ("" when unavailable);
                                 # feeds the scrubber's owner-tell tokens + required_apis derivation
    }


def mine(slugs: list[str], out: str, *, gh: Optional[Callable] = None, repo_name: str,
         fleet_names: list[str], limit: int = 200, max_files: int = 5, holdout_frac: float = 0.0,
         coverage_cutoff: str = "", leak_index=None, not_a_defect_limit: int = 0,
         diff_fetcher: Optional[Callable[[str, str], str]] = None) -> dict:
    """Mine one repo slug (repo_name = its short catalog name) into `out/`. Returns a report dict.

    `diff_fetcher(slug, sha) -> unified diff` supplies each positive's gold merge-commit diff (sets
    `fix_patch` + `required_apis` so the fix `resolved_rate` becomes gradeable). Default resolution:
    production (real gh, `gh is None`) fetches via the REST commits endpoint; an injected fake gh
    (tests) defaults to a no-op "" so the hermetic suite never touches the network — inject an
    explicit `diff_fetcher` to exercise the wiring. A failed/empty fetch is fail-safe: fix_patch=""
    + required_apis=[] leave the case ungradeable rather than crashing."""
    from groundloop.domains.android_ivi.owner_tokens import missing_owner_rows
    missing = missing_owner_rows([repo_name])
    if missing:
        raise ValueError(f"no FLEET_OWNER_TOKENS row for {missing}; cannot scrub its owner tells")
    if diff_fetcher is None:
        diff_fetcher = ((lambda slug, sha: fetch_commit_diff(slug, sha)) if gh is None
                        else (lambda slug, sha: ""))
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
            try:
                gold_diff = diff_fetcher(slug, cand.merge_commit_sha) if cand.merge_commit_sha else ""
            except Exception:
                gold_diff = ""     # fail-safe: a failed fetch leaves the case ungradeable, never crashes
            fix_apis = required_apis_from_diff(gold_diff)
            oracle = _oracle_for(cand, repo_name, prod, fix_patch=gold_diff)
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
                owning_repo=owning, expected_files=prod, required_apis=fix_apis, fix_patch=gold_diff,
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

        if not_a_defect_limit > 0:
            from groundloop.mine.harvest import harvest_nondefects
            nd_kwargs = {"limit": not_a_defect_limit} if gh is None else {"gh": gh, "limit": not_a_defect_limit}
            for cand in harvest_nondefects(slug, **nd_kwargs):
                report["harvested"] += 1
                prose, logs = split_issue_body(cand.issue_body)
                tok = build_owner_tokens(_oracle_for(cand, repo_name, []))
                s_desc, s_summary = scrub(prose, tok), scrub(cand.issue_title, tok)
                s_logs = [scrub(lg["text"], tok) for lg in logs]
                emit_case(out, MinedCase(
                    case_id=_opaque_id(slug, cand.issue_number), summary=s_summary, description=s_desc,
                    logs=[{"kind": lg["kind"], "text": t} for lg, t in zip(logs, s_logs)],
                    owning_repo="__NOT_A_DEFECT__", expected_files=[], required_apis=[],
                    is_answerable=False, negative_class="not_a_defect",
                    provenance={"source_method": "label_harvest", "labels": list(cand.labels)}))
                report["not_a_defect"] += 1
    return report
