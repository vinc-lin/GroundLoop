from groundloop.mine.harvest import harvest_repo, Candidate

# Minimal shape of the GraphQL page the harvester consumes.
_PAGE = {
    "data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [
            {   # good: same-repo merged closer, 1 production file
                "number": 100, "title": "Crash on filter", "body": "boom\n```\nat x.Y.z()\n```",
                "createdAt": "2026-01-01T00:00:00Z", "url": "u",
                "labels": {"nodes": [{"name": "bug"}]},
                "closedByPullRequestsReferences": {"nodes": [{
                    "number": 200, "merged": True, "mergedAt": "2026-02-01T00:00:00Z",
                    "mergeCommit": {"oid": "deadbeef"},
                    "repository": {"nameWithOwner": "acme/widget"},
                    "files": {"totalCount": 1, "nodes": [
                        {"path": "src/main/java/A.java", "changeType": "MODIFIED", "additions": 3, "deletions": 1}]},
                }]},
            },
            {   # cross-repo closer -> MUST be dropped
                "number": 101, "title": "Extractor bug", "body": "x",
                "createdAt": "2026-01-02T00:00:00Z", "url": "u2", "labels": {"nodes": []},
                "closedByPullRequestsReferences": {"nodes": [{
                    "number": 300, "merged": True, "mergedAt": "2026-02-02T00:00:00Z",
                    "mergeCommit": {"oid": "cafe"},
                    "repository": {"nameWithOwner": "acme/widget-extractor"},  # DIFFERENT repo
                    "files": {"totalCount": 1, "nodes": [
                        {"path": "src/main/java/B.java", "changeType": "MODIFIED", "additions": 1, "deletions": 0}]},
                }]},
            },
            {   # no merged closer -> dropped
                "number": 102, "title": "Question", "body": "how?", "createdAt": "2026-01-03T00:00:00Z",
                "url": "u3", "labels": {"nodes": []}, "closedByPullRequestsReferences": {"nodes": []},
            },
        ],
    }}}
}


def test_harvest_keeps_same_repo_merged_and_drops_cross_repo_and_unlinked():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return _PAGE

    cands = harvest_repo("acme/widget", gh=fake_gh, limit=50)

    assert [c.issue_number for c in cands] == [100]
    c = cands[0]
    assert isinstance(c, Candidate)
    assert c.owning_slug == "acme/widget"
    assert c.pr_number == 200
    assert c.merge_commit_sha == "deadbeef"
    assert c.files[0]["filename"] == "src/main/java/A.java"
    assert c.files[0]["status"] == "modified"        # normalized from GraphQL UPPERCASE
    assert c.issue_title == "Crash on filter"


def test_dedup_same_issue_across_pages():
    node = _PAGE["data"]["repository"]["issues"]["nodes"][0]
    page = {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node, node]}}}}
    cands = harvest_repo("acme/widget", gh=lambda a: page, limit=50)
    assert len(cands) == 1
