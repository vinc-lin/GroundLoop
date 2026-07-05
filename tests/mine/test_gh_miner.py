import json
from pathlib import Path  # noqa: F401 (kept for parity with the plan's literal test text)

from groundloop.mine.gh_miner import mine
from groundloop.adapters.mock.jira import MockJira
from groundloop.core.types import RepoRef, RepoScore
from tests.mine.conftest import _node, _fake, _PRODFILE


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


class _OwnerWinsIndex:
    """A leak_index that always ranks `owner` top-1 (score>0) — simulates 'the owner is still identifiable'."""
    def __init__(self, owner):
        self.owner = owner

    def rank_repos(self, signals, catalog):
        return ([RepoScore(RepoRef(self.owner), 9.0)]
                + [RepoScore(r, 0.0) for r in catalog if r.name != self.owner])


def _leak_gh():
    return _fake([_node(100, body="java.lang.IllegalStateException at app.A.f(A.java:5)",
                        closer={"slug": "TeamNewPipe/NewPipe", "files": [_PRODFILE]})])


def test_closed_loop_reject_drops_when_owner_still_wins(tmp_path):
    fleet = ["newpipe", "osmand", "media3"]
    # (a) no leak_index -> admitted as before (back-compat)
    r1 = mine(["TeamNewPipe/NewPipe"], str(tmp_path / "a"), gh=_leak_gh(), repo_name="newpipe",
              fleet_names=fleet, limit=5)
    assert r1["admitted"] == 1
    # (b) leak_index says the owner still wins on the sanitized text -> rejected, nothing emitted
    r2 = mine(["TeamNewPipe/NewPipe"], str(tmp_path / "b"), gh=_leak_gh(), repo_name="newpipe",
              fleet_names=fleet, limit=5, leak_index=_OwnerWinsIndex("newpipe"))
    assert r2["rejected_leak"] >= 1 and r2["admitted"] == 0
    assert not any(p.is_dir() for p in Path(str(tmp_path / "b")).iterdir())


def test_prose_only_tagged_insufficient_signal(tmp_path):
    from tests.mine.conftest import _node, _fake, _PRODFILE
    # PR touches a real prod .java (is_minable OK) but the issue body is pure prose (no stack/log)
    gh = _fake([_node(300, title="empty list", body="The list is occasionally empty after refresh.",
                      closer={"slug": "TeamNewPipe/NewPipe", "files": [_PRODFILE]})])
    out = str(tmp_path / "ds")
    report = mine(["TeamNewPipe/NewPipe"], out, gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand"], limit=5)
    import json
    from pathlib import Path
    d = next(p for p in Path(out).iterdir() if p.is_dir())
    o = json.loads((d / "_oracle" / "oracle.json").read_text())
    assert o["is_answerable"] is True and o["negative_class"] == "insufficient_signal"
    assert json.loads((d / "_oracle" / "provenance.json").read_text())["source_method"] == "prose_only"
    assert report["insufficient_signal"] == 1
