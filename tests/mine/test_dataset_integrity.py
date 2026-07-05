"""Every mined case must round-trip through MockJira/Oracle AND leak no owner-unique token."""
from pathlib import Path

from groundloop.mine.gh_miner import mine
from groundloop.mine.scrub import build_owner_tokens, leakage_flags
from groundloop.mine.emit import MinedCase, emit_case  # noqa: F401 (schema reference)
from groundloop.adapters.mock.jira import MockJira
from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for


def _oracle(repo, files):
    row = owner_tokens_for(repo)
    return {"owning_repo": repo, "owner_namespaces": list(row["namespaces"]),
            "owner_slugs": list(row["slugs"]), "owner_sonames": list(row["sonames"]),
            "expected_files": files, "fix_patch": ""}


def test_mined_case_never_leaks_owner_token(tmp_path):
    body = ("Crash.\n```\njava.lang.NullPointerException\n"
            "  at org.schabi.newpipe.player.Player.load(Player.java:9)\n```\n")
    gh = lambda a: {"data": {"repository": {"issues": {  # noqa: E731
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{
            "number": 7, "title": "Player NPE", "body": body, "createdAt": "t", "url": "u",
            "labels": {"nodes": []}, "closedByPullRequestsReferences": {"nodes": [{
                "number": 8, "merged": True, "mergedAt": "t", "mergeCommit": {"oid": "s"},
                "repository": {"nameWithOwner": "TeamNewPipe/NewPipe"},
                "files": {"totalCount": 1, "nodes": [{
                    "path": "app/src/main/java/org/schabi/newpipe/player/Player.java",
                    "changeType": "MODIFIED", "additions": 2, "deletions": 1}]}}]}}]}}}}
    report = mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
                  fleet_names=["newpipe", "osmand", "media3"], limit=5)
    # Guard against vacuity: a scrubber/gate regression that rejects everything must fail loudly,
    # not pass silently on an empty dataset. This NewPipe case is clean and MUST be admitted.
    assert report["admitted"] >= 1, f"no case admitted — pipeline rejected everything: {report}"

    for case_dir in [p for p in Path(tmp_path).iterdir() if p.is_dir()]:
        ticket = MockJira(str(tmp_path)).fetch(case_dir.name)
        assert ticket.component == ""
        tok = build_owner_tokens(_oracle("newpipe",
              ["app/src/main/java/org/schabi/newpipe/player/Player.java"]))
        flags, sig = leakage_flags(ticket.description,
                                   [a.content for a in ticket.logs], tok, "newpipe")
        assert not any(flags.values()), f"leak in {case_dir.name}: {flags}"
