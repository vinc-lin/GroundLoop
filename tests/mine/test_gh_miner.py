import json
from pathlib import Path  # noqa: F401 (kept for parity with the plan's literal test text)

from groundloop.mine.gh_miner import mine
from groundloop.adapters.mock.jira import MockJira


def _page(slug, number, body, path):
    return {"data": {"repository": {"issues": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [{
            "number": number, "title": "Crash", "body": body,
            "createdAt": "2026-01-01T00:00:00Z", "url": "u", "labels": {"nodes": [{"name": "bug"}]},
            "closedByPullRequestsReferences": {"nodes": [{
                "number": number + 1000, "merged": True, "mergedAt": "2026-02-01T00:00:00Z",
                "mergeCommit": {"oid": "sha1"}, "repository": {"nameWithOwner": slug},
                "files": {"totalCount": 1, "nodes": [
                    {"path": path, "changeType": "MODIFIED", "additions": 3, "deletions": 1}]},
            }]},
        }],
    }}}}


def test_mine_end_to_end_emits_admitted_scrubbed_case(tmp_path):
    # A NewPipe issue whose body leaks the owner namespace + a generic exception.
    body = ("Crashes on search.\n```\n"
            "java.lang.NullPointerException\n"
            "  at org.schabi.newpipe.SearchFragment.doSearch(SearchFragment.java:42)\n```\n")
    gh = lambda args: _page("TeamNewPipe/NewPipe", 100, body,  # noqa: E731
                            "app/src/main/java/org/schabi/newpipe/SearchFragment.java")

    report = mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand", "media3"], limit=10)

    assert report["admitted"] == 1
    # catalog written
    assert json.loads((tmp_path / "catalog.json").read_text()) == [
        {"name": "newpipe"}, {"name": "osmand"}, {"name": "media3"}]
    # the emitted ticket loads and is SCRUBBED (owner namespace gone, generic error kept)
    case_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    ticket = MockJira(str(tmp_path)).fetch(case_dir.name)
    blob = ticket.description + "\n" + "\n".join(a.content for a in ticket.logs)
    assert "org.schabi.newpipe" not in blob
    assert "NullPointerException" in blob          # generic signal kept
    # oracle is hidden + correct
    oracle = json.loads((case_dir / "_oracle" / "oracle.json").read_text())
    assert oracle["owning_repo"] == "newpipe"
    assert oracle["expected_files"] == ["app/src/main/java/org/schabi/newpipe/SearchFragment.java"]


def test_mine_rejects_when_no_production_files(tmp_path):
    body = "Docs typo.\n```\nat x.Y.z()\n```\n"
    gh = lambda args: _page("TeamNewPipe/NewPipe", 101, body, "README.md")  # noqa: E731
    report = mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe"], limit=10)
    assert report["admitted"] == 0
    assert report["dropped_filters"] >= 1
