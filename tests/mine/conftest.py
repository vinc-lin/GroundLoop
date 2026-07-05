"""Shared fake-`gh` GraphQL fixture helpers for tests/mine/* (reproduces the page shape
`groundloop/mine/harvest.py` consumes, so tests never touch the network).
"""
from __future__ import annotations

_PRODFILE = {"path": "src/main/java/app/A.java", "changeType": "MODIFIED", "additions": 3, "deletions": 1}


def _node(number, *, title="t", body="", labels=(), closer=None, merged_at="2026-01-01T00:00:00Z"):
    """One issue node. closer=None → no linked PR; else dict {slug, files, merged=True, oid, mergedAt}."""
    closers = []
    if closer is not None:
        closers = [{"number": 1, "merged": closer.get("merged", True),
                    "mergedAt": closer.get("mergedAt", merged_at),
                    "mergeCommit": {"oid": closer.get("oid", "abc123")},
                    "repository": {"nameWithOwner": closer["slug"]},
                    "files": {"totalCount": len(closer.get("files", [])), "nodes": closer.get("files", [])}}]
    return {"number": number, "title": title, "body": body, "createdAt": "2026-01-01T00:00:00Z",
            "url": f"https://github.com/x/y/issues/{number}",
            "labels": {"nodes": [{"name": n} for n in labels]},
            "closedByPullRequestsReferences": {"nodes": closers}}


def _gql_page(nodes):
    return {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}


def _fake(nodes):
    """A fake gh callable returning one page for any graphql args (matches harvest.py's gh(args) API)."""
    return lambda _args: _gql_page(nodes)
