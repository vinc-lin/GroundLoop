"""Gold-diff fetch + required_apis derivation (the fix `resolved_rate` producers).

Hermetic: the `gh` REST call is injected as a fake — no network. Covers
harvest.fetch_commit_diff (assemble a unified diff from the commits API `files[].patch`),
gh_miner.required_apis_from_diff (call-like API extraction over added CODE lines), and the
miner wiring (a mined positive gets a non-empty fix_patch + required_apis; a failed/empty
fetch stays fail-safe at ""/[]).
"""
import json
from pathlib import Path

from groundloop.fix.patch import added_lines, references_api_code, touched_files
from groundloop.mine.harvest import fetch_commit_diff
from groundloop.mine.gh_miner import mine, required_apis_from_diff
from tests.mine.conftest import _node, _fake, _PRODFILE


# --------------------------------------------------------------------------- fetch_commit_diff

def _commits_payload(files):
    return {"sha": "sha1", "files": files}


def test_fetch_commit_diff_assembles_unified_diff_from_files_patch():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return _commits_payload([
            {"filename": "src/main/java/app/A.java", "status": "modified",
             "patch": "@@ -1,3 +1,4 @@\n ctx\n-int old = 0;\n+long v = helper.doThing();"},
        ])

    diff = fetch_commit_diff("acme/widget", "sha1", gh=fake_gh)
    # the fetch hits the REST commits endpoint for THIS slug/sha (not graphql)
    assert calls == [["api", "repos/acme/widget/commits/sha1"]]
    # a well-formed unified diff the fix/patch parsers accept
    assert "diff --git a/src/main/java/app/A.java b/src/main/java/app/A.java" in diff
    assert "--- a/src/main/java/app/A.java" in diff
    assert "+++ b/src/main/java/app/A.java" in diff
    assert touched_files(diff) == ["src/main/java/app/A.java"]
    assert "long v = helper.doThing();" in added_lines(diff)


def test_fetch_commit_diff_added_and_removed_use_devnull():
    def fake_gh(_args):
        return _commits_payload([
            {"filename": "src/New.java", "status": "added", "patch": "@@ -0,0 +1,1 @@\n+new Thing();"},
            {"filename": "src/Old.java", "status": "removed", "patch": "@@ -1,1 +0,0 @@\n-gone();"},
        ])

    diff = fetch_commit_diff("acme/widget", "sha1", gh=fake_gh)
    assert "--- /dev/null" in diff          # added file: no old side
    assert "+++ b/src/New.java" in diff
    assert "+++ /dev/null" in diff          # removed file: no new side
    assert "--- a/src/Old.java" in diff


def test_fetch_commit_diff_skips_binary_and_is_failsafe_on_missing_sha():
    def fake_gh(_args):
        return _commits_payload([{"filename": "img.png", "status": "added"}])  # no `patch` (binary)

    assert fetch_commit_diff("acme/widget", "sha1", gh=fake_gh) == ""   # binary skipped -> empty
    # missing slug/sha never calls gh (fail-safe, no crash)
    boom = lambda _a: (_ for _ in ()).throw(AssertionError("gh must not be called"))  # noqa: E731
    assert fetch_commit_diff("", "sha1", gh=boom) == ""
    assert fetch_commit_diff("acme/widget", "", gh=boom) == ""


# --------------------------------------------------------------------------- required_apis_from_diff

_FIXTURE_DIFF = (
    "diff --git a/A.java b/A.java\n--- a/A.java\n+++ b/A.java\n"
    "@@ -1,2 +1,6 @@\n"
    " unchanged;\n"
    "+        Result r = foo.bar(x);\n"
    "+        Baz b = new Baz(config);\n"
    "+        if (r != null) { return; }\n"
    "+        // helper.doThing() is intentional here\n"   # comment: excluded by code_added_lines
)


def test_required_apis_extracts_call_like_apis_drops_keywords_and_comments():
    apis = required_apis_from_diff(_FIXTURE_DIFF)
    # `bar` (obj.method target) + `Baz` (constructor type via `new Baz(`), first-seen order.
    # `if` (keyword) dropped; `doThing` lives only on a comment line -> not extracted.
    assert apis == ["bar", "Baz"]
    # sanity: the gold diff references every derived api on an added CODE line (by construction)
    for a in apis:
        assert references_api_code(_FIXTURE_DIFF, a)
    assert not references_api_code(_FIXTURE_DIFF, "doThing")   # comment-only, correctly excluded


def test_required_apis_dedups_and_caps():
    lines = "".join(f"+        callFn{i}();\n" for i in range(8))
    lines += "+        callFn0();\n"    # a repeat -> must dedup
    diff = "diff --git a/B.java b/B.java\n--- a/B.java\n+++ b/B.java\n@@ -1,1 +1,10 @@\n ctx\n" + lines
    apis = required_apis_from_diff(diff)
    assert apis == ["callFn0", "callFn1", "callFn2", "callFn3", "callFn4"]   # capped at 5, first-seen


def test_required_apis_empty_on_empty_diff():
    assert required_apis_from_diff("") == []


# --------------------------------------------------------------------------- miner wiring

def _positive_gh():
    return _fake([_node(500, body="java.lang.IllegalStateException at app.A.f(A.java:5)",
                        closer={"slug": "TeamNewPipe/NewPipe", "files": [_PRODFILE], "oid": "sha1"})])


def _oracle_of(out):
    d = next(p for p in Path(out).iterdir() if p.is_dir())
    return json.loads((d / "_oracle" / "oracle.json").read_text())


def test_mine_sets_fix_patch_and_required_apis_from_injected_diff(tmp_path):
    out = str(tmp_path / "ds")
    gold = ("diff --git a/src/main/java/app/A.java b/src/main/java/app/A.java\n"
            "--- a/src/main/java/app/A.java\n+++ b/src/main/java/app/A.java\n"
            "@@ -1,1 +1,2 @@\n ctx\n+        Baz b = new Baz(config);\n")
    seen = []

    def diff_fetcher(slug, sha):
        seen.append((slug, sha))
        return gold

    report = mine(["TeamNewPipe/NewPipe"], out, gh=_positive_gh(), repo_name="newpipe",
                  fleet_names=["newpipe", "osmand"], limit=5, diff_fetcher=diff_fetcher)
    assert report["admitted"] == 1
    assert seen == [("TeamNewPipe/NewPipe", "sha1")]      # fetched for the merge commit sha
    o = _oracle_of(out)
    assert o["fix_patch"] == gold
    assert o["required_apis"] == ["Baz"]


def test_mine_failed_diff_fetch_is_failsafe(tmp_path):
    out = str(tmp_path / "ds")

    def boom(_slug, _sha):
        raise RuntimeError("gh commits fetch failed")

    report = mine(["TeamNewPipe/NewPipe"], out, gh=_positive_gh(), repo_name="newpipe",
                  fleet_names=["newpipe", "osmand"], limit=5, diff_fetcher=boom)
    assert report["admitted"] == 1                       # still emitted (fail-safe, no crash)
    o = _oracle_of(out)
    assert o["fix_patch"] == "" and o["required_apis"] == []


def test_mine_without_diff_fetcher_stays_empty_hermetic(tmp_path):
    # No diff_fetcher + an injected (fake) gh -> the diff fetch is OFF (no network); ungradeable but safe.
    out = str(tmp_path / "ds")
    mine(["TeamNewPipe/NewPipe"], out, gh=_positive_gh(), repo_name="newpipe",
         fleet_names=["newpipe", "osmand"], limit=5)
    o = _oracle_of(out)
    assert o["fix_patch"] == "" and o["required_apis"] == []
