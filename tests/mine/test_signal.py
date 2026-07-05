from groundloop.mine.signal import split_issue_body, classify


def test_classify_kinds():
    assert classify("  at org.x.Foo.bar(Foo.java:1)") == "stacktrace"
    assert classify("E/AndroidRuntime: FATAL EXCEPTION: main") == "logcat"
    assert classify("  #00 pc 0000abcd  liba.so") == "native"
    assert classify("ANR in com.x (com.x/.Main)") == "anr"
    assert classify("just prose about a crash") == "other"


def test_fenced_log_block_extracted_and_cut_from_prose():
    md = (
        "The app crashes when I tap filter.\n\n"
        "```\n"
        "E/AndroidRuntime: FATAL EXCEPTION: GLThread\n"
        "java.lang.UnsatisfiedLinkError: No implementation found\n"
        "  at org.wysaid.CGEImageHandler.nativeCreateHandler(Native Method)\n"
        "```\n\n"
        "Device: Pixel 5.\n"
    )
    prose, logs = split_issue_body(md)
    assert len(logs) == 1
    assert logs[0]["kind"] == "logcat"
    assert "UnsatisfiedLinkError" in logs[0]["text"]
    # the fenced block is removed from prose; surrounding prose is kept
    assert "crashes when I tap filter" in prose
    assert "Device: Pixel 5" in prose
    assert "UnsatisfiedLinkError" not in prose


def test_issue_template_scaffolding_stripped():
    md = "### Steps to reproduce\n- [ ] checkbox\n<!-- comment -->\nreal prose here\n"
    prose, logs = split_issue_body(md)
    assert "checkbox" not in prose
    assert "real prose here" in prose


def test_body_with_no_logs_yields_empty_logs():
    prose, logs = split_issue_body("Feature request: please add dark mode.")
    assert logs == []
    assert "dark mode" in prose
