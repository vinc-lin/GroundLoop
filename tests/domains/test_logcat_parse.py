from groundloop.domains.android_ivi.logcat_parse import parse_logcat, LogLine  # noqa: F401


def test_threadtime_format():
    lines = parse_logcat("07-05 10:34:07.221  4821  4913 E AndroidRuntime: FATAL EXCEPTION: main")
    assert len(lines) == 1
    ln = lines[0]
    assert ln.pid == "4821" and ln.tid == "4913" and ln.level == "E"
    assert ln.tag == "AndroidRuntime" and ln.msg == "FATAL EXCEPTION: main"


def test_year_format():
    ln = parse_logcat("2026-07-05 10:34:07.221 4821 4913 F libc: Fatal signal 11 (SIGSEGV)")[0]
    assert ln.level == "F" and ln.tag == "libc" and ln.msg.startswith("Fatal signal 11")


def test_continuation_attaches_to_prev_pid():
    text = ("07-05 10:34:07.221  4821  4821 E AndroidRuntime: java.lang.NullPointerException: x\n"
            "07-05 10:34:07.221  4821  4821 E AndroidRuntime: \tat com.x.Foo.bar(Foo.java:10)")
    lines = parse_logcat(text)
    assert lines[1].pid == "4821" and "at com.x.Foo.bar" in lines[1].msg


def test_malformed_line_preserved_raw():
    lines = parse_logcat("not a logcat line\n07-05 10:34:07.221 1 1 I T: ok")
    assert lines[0].raw == "not a logcat line" and lines[0].pid is None
    assert lines[1].tag == "T"
