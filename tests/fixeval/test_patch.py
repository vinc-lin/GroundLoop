from groundloop.fixeval.patch import (
    extract_unified_diff, touched_files, added_lines, references_api, norm_path)

_FENCED = "blah\n```diff\n--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+int nativeCreateHandler(){return 1;}\n```\ntrailer"
_BARE = "--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+int fixed;\n"


def test_extract_unified_diff_fenced_and_bare():
    assert "+++ b/x/A.cpp" in extract_unified_diff(_FENCED)
    assert extract_unified_diff(_FENCED).strip().endswith("nativeCreateHandler(){return 1;}")
    assert "+++ b/x/A.cpp" in extract_unified_diff(_BARE)
    assert extract_unified_diff("no diff here at all") == ""


def test_touched_files_strips_b_prefix():
    assert touched_files(_BARE) == ["x/A.cpp"]
    assert touched_files("--- a/dev/null\n+++ b/dev/null\n") == ["dev/null"]


def test_added_lines_excludes_header():
    al = added_lines(_FENCED)
    assert any("nativeCreateHandler" in a for a in al)
    assert not any(a.startswith("+++") for a in al)


def test_references_api_whole_word_over_added_only():
    assert references_api(_FENCED, "nativeCreateHandler") is True
    assert references_api(_FENCED, "nativeCreateHandlerX") is False
    assert references_api("--- a/A\n+++ b/A\n@@\n-nativeCreateHandler\n", "nativeCreateHandler") is False


def test_norm_path():
    assert norm_path("b/x/A.cpp") == "x/A.cpp" and norm_path("a/x/A.cpp") == "x/A.cpp"
    assert norm_path("./x//A.cpp") == "x/A.cpp" and norm_path("x/A.cpp") == "x/A.cpp"
