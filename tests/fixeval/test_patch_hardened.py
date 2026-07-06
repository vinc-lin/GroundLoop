from groundloop.fixeval.patch import references_api, references_api_code


def test_code_api_excludes_comment_namedrop():
    diff = "--- a/f.java\n+++ b/f.java\n@@ -1 +1,2 @@\n+    // remember to call startForeground()\n+    int x = 1;\n"
    assert references_api(diff, "startForeground") is True        # old proxy: comment name-drop counts
    assert references_api_code(diff, "startForeground") is False  # hardened: comments excluded


def test_code_api_matches_real_call():
    diff = "--- a/f.java\n+++ b/f.java\n@@ -1 +1,2 @@\n+    startForeground(1, note);\n"
    assert references_api_code(diff, "startForeground") is True


def test_code_api_ignores_blank_and_star_continuation():
    diff = "--- a/f.java\n+++ b/f.java\n@@ -1 +1,3 @@\n+\n+     * javadoc mentions foo\n+    int y = 0;\n"
    assert references_api_code(diff, "foo") is False
