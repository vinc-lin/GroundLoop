"""Harvest closed issues with a same-repo merged closing PR via the GitHub GraphQL API.

`gh` is injected as a callable: gh(args:list[str]) -> parsed JSON. The default shells out to
`gh api graphql`. GraphQL is used (not `gh search`) because closedByPullRequestsReferences gives
the issue->merged-PR binding directly in one paginated call (search does not expose it).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable

_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    issues(states:CLOSED, first:25, after:$cursor,
           orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body createdAt url
        labels(first:20) { nodes { name } }
        closedByPullRequestsReferences(first:5, includeClosedPrs:true) {
          nodes {
            number merged mergedAt mergeCommit { oid }
            repository { nameWithOwner }
            files(first:100) { totalCount nodes { path changeType additions deletions } }
          }
        }
      }
    }
  }
}
"""

_STATUS = {"ADDED": "added", "MODIFIED": "modified", "REMOVED": "removed",
           "DELETED": "removed",  # GitHub GraphQL PatchStatus uses DELETED (not REMOVED)
           "RENAMED": "renamed", "COPIED": "copied", "CHANGED": "changed"}


@dataclass(frozen=True)
class Candidate:
    owning_slug: str          # "owner/name"
    issue_number: int
    issue_title: str
    issue_body: str
    issue_url: str
    labels: tuple[str, ...]
    created_at: str
    pr_number: int
    merge_commit_sha: str
    merged_at: str
    files_total: int
    files: list[dict] = field(default_factory=list)  # [{filename,status,additions,deletions}]


def _default_gh(args: list[str]) -> dict:
    cp = subprocess.run(["gh", *args], capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"gh {args[:2]} failed: {(cp.stderr or '')[-300:]}")
    return json.loads(cp.stdout or "{}")


def _gql_args(owner: str, name: str, cursor: str | None) -> list[str]:
    args = ["api", "graphql", "-f", f"query={_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}"]
    if cursor:
        args += ["-F", f"cursor={cursor}"]
    return args


def _assemble_unified_diff(files: list[dict]) -> str:
    """Reassemble a unified diff from GitHub commit `files[]` entries (filename/status/patch/
    previous_filename). The REST commits API's per-file `patch` is the hunk body only (starts at
    `@@`), WITHOUT the `diff --git`/`---`/`+++` headers — we synthesize them so
    groundloop.fix.patch's parsers (touched_files/added_lines/git apply) accept the result.
    Files with no textual `patch` (binary) are skipped."""
    out: list[str] = []
    for f in files:
        patch = f.get("patch")
        if not patch:
            continue
        path = f.get("filename", "")
        old = f.get("previous_filename", path)
        status = f.get("status", "modified")
        out.append(f"diff --git a/{old} b/{path}")
        out.append("--- /dev/null" if status == "added" else f"--- a/{old}")
        out.append("+++ /dev/null" if status == "removed" else f"+++ b/{path}")
        out.append(patch.rstrip("\n"))
    return "\n".join(out) + ("\n" if out else "")


def fetch_commit_diff(slug: str, sha: str, *, gh: Callable[[list[str]], dict] = _default_gh) -> str:
    """Return the merge commit's unified diff (the fix gold diff) for `sha` in `slug`, or "".

    Uses the gh REST commits endpoint (`gh api repos/{slug}/commits/{sha}`); its JSON payload
    carries per-file `patch` hunks that we reassemble into a header-complete unified diff
    (`_assemble_unified_diff`). The raw-diff `Accept: application/vnd.github.diff` header is NOT used
    because the JSON-decoding gh helper cannot return raw text. `gh` is injectable so tests pass a
    fake — no network. Fail-safe: a missing slug/sha returns "" WITHOUT calling gh (the caller then
    leaves fix_patch/required_apis empty → the case is ungradeable, never a crash)."""
    if not slug or not sha:
        return ""
    payload = gh(["api", f"repos/{slug}/commits/{sha}"])
    files = payload.get("files", []) if isinstance(payload, dict) else []
    return _assemble_unified_diff(files)


def harvest_repo(slug: str, *, gh: Callable[[list[str]], dict] = _default_gh,
                 limit: int = 200) -> list[Candidate]:
    """Return same-repo merged-closer candidates for a repo, deduped per issue."""
    owner, name = slug.split("/", 1)
    seen: set[int] = set()
    out: list[Candidate] = []
    cursor: str | None = None
    while len(out) < limit:
        page = gh(_gql_args(owner, name, cursor))
        conn = page["data"]["repository"]["issues"]
        for node in conn["nodes"]:
            if node["number"] in seen:
                continue
            closer = _pick_closer(node, slug)
            if closer is None:
                continue
            seen.add(node["number"])
            out.append(_to_candidate(slug, node, closer))
            if len(out) >= limit:
                break
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return out


def _pick_closer(node: dict, slug: str) -> dict | None:
    for pr in node.get("closedByPullRequestsReferences", {}).get("nodes", []):
        if pr.get("merged") and pr.get("repository", {}).get("nameWithOwner") == slug:
            return pr        # same-repo merged closer (the non-negotiable filter)
    return None


def _to_candidate(slug: str, node: dict, pr: dict) -> Candidate:
    files = [{"filename": f["path"], "status": _STATUS.get(f["changeType"], f["changeType"].lower()),
              "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)}
             for f in pr.get("files", {}).get("nodes", [])]
    return Candidate(
        owning_slug=slug, issue_number=node["number"], issue_title=node.get("title", ""),
        issue_body=node.get("body") or "", issue_url=node.get("url", ""),
        labels=tuple(x["name"] for x in node.get("labels", {}).get("nodes", [])),
        created_at=node.get("createdAt", ""), pr_number=pr["number"],
        merge_commit_sha=(pr.get("mergeCommit") or {}).get("oid", ""),
        merged_at=pr.get("mergedAt", ""), files_total=pr.get("files", {}).get("totalCount", len(files)),
        files=files)


NOT_A_DEFECT_LABELS = {"enhancement", "question", "duplicate", "wontfix", "invalid",
                       "feature", "feature request", "documentation"}


def harvest_nondefects(slug: str, *, gh: Callable[[list[str]], dict] = _default_gh,
                       limit: int = 50) -> list[Candidate]:
    """Issues with NO same-repo merged closer AND a not-a-defect label (reuses _QUERY unchanged)."""
    owner, name = slug.split("/", 1)
    out: list[Candidate] = []
    seen: set[int] = set()
    cursor: str | None = None
    while len(out) < limit:
        page = gh(_gql_args(owner, name, cursor))
        conn = page["data"]["repository"]["issues"]
        for node in conn["nodes"]:
            if node["number"] in seen:
                continue
            labels = {x["name"].lower() for x in node.get("labels", {}).get("nodes", [])}
            if _pick_closer(node, slug) is None and (labels & NOT_A_DEFECT_LABELS):
                seen.add(node["number"])
                out.append(_to_nondefect_candidate(slug, node))
                if len(out) >= limit:
                    break
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return out


def _to_nondefect_candidate(slug: str, node: dict) -> Candidate:
    return Candidate(owning_slug=slug, issue_number=node["number"], issue_title=node.get("title", ""),
                     issue_body=node.get("body") or "", issue_url=node.get("url", ""),
                     labels=tuple(x["name"] for x in node.get("labels", {}).get("nodes", [])),
                     created_at=node.get("createdAt", ""), pr_number=0, merge_commit_sha="",
                     merged_at="", files_total=0, files=[])
