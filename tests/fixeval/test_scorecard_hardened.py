from dataclasses import dataclass
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all


@dataclass
class O:  # noqa: E742 (minimal oracle stand-in — name kept for parity with the plan's literal test text)
    expected_files: list
    required_apis: list
    is_answerable: bool = True


def _rec(**kw):
    base = dict(case_id="c1", arm="a", predicted_repo="r", locations=["src/Right.java"],
                patch_diff="", patch_files=[], patch_emitted=True, patch_applies=True,
                abstained=False, abstain_reason=None, refine_iters=0, cost_usd=0.0)
    base.update(kw)
    return FixRecord(**base)


def test_strict_rejects_wrong_file_edit():
    # localize surfaced the right file, but the patch edits the WRONG file
    diff = "--- a/src/Wrong.java\n+++ b/src/Wrong.java\n@@ -1 +1,2 @@\n+    foo();\n"
    rec = _rec(patch_diff=diff, patch_files=["src/Wrong.java"])
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["foo"])}
    card = grade_fix_all([rec], oracle_by_case=oracle)["arms"]["a"]
    assert card["resolved_rate"]["value"] == 1.0          # old proxy: file_recall over locations passes
    assert card["resolved_rate_strict"]["value"] == 0.0   # hardened: patch touched the wrong file


def test_strict_rejects_comment_only_api():
    diff = "--- a/src/Right.java\n+++ b/src/Right.java\n@@ -1 +1,2 @@\n+    // foo() should be called\n+    int x=1;\n"
    rec = _rec(patch_diff=diff, patch_files=["src/Right.java"])
    oracle = {"c1": O(expected_files=["src/Right.java"], required_apis=["foo"])}
    card = grade_fix_all([rec], oracle_by_case=oracle)["arms"]["a"]
    assert card["resolved_rate_strict"]["value"] == 0.0   # api only name-dropped in a comment
