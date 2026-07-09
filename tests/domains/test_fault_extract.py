import random

from groundloop.domains.android_ivi.fault_extract import extract_fault_record
from groundloop.domains.android_ivi.logcat_parse import parse_logcat
from groundloop.synth.logs import Frame, build_java_logcat, build_native_backtrace, build_anr

RNG = lambda: random.Random(5)  # noqa: E731 (kept for parity with the plan's literal test text)
JF = Frame(package="org.schabi.newpipe.streams", cls="SrtWriter", method="write",
           filename="SrtWriter.java", line=42)
NF = Frame(package="", cls="AudioStreamAAudio", method="requestStart", filename="AAudioStream.cpp", line=9)


def test_java_fatal_exception():
    text = build_java_logcat([JF], "java.lang.NullPointerException", RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.family == "java"
    assert fr.top_frame.key() == "org.schabi.newpipe.streams.SrtWriter.write"
    assert fr.fault_file_hint == "SrtWriter.java" and fr.confidence == "HIGH"
    assert fr.exception.endswith("NullPointerException")


def test_native_signal():
    text = build_native_backtrace("liboboe.so", [NF], RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.family == "native"
    assert fr.top_frame.key() == "AudioStreamAAudio::requestStart"
    assert fr.top_frame.soname == "liboboe.so" and fr.confidence == "HIGH"


def test_anr():
    text = build_anr([JF], RNG(), proc="net.osmand")
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.family == "anr"
    assert fr.top_frame.key() == "org.schabi.newpipe.streams.SrtWriter.write"


def test_skips_framework_frames_for_top():
    fw = Frame(package="android.os", cls="Handler", method="dispatchMessage", filename="Handler.java", line=1)
    text = build_java_logcat([fw, JF], "java.lang.IllegalStateException", RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr.top_frame.package == "org.schabi.newpipe.streams"   # first non-framework frame


def test_all_framework_is_low_confidence():
    fw = Frame(package="android.os", cls="Handler", method="dispatchMessage", filename="Handler.java", line=1)
    text = build_java_logcat([fw], "java.lang.NullPointerException", RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.confidence == "LOW"


def test_lowercase_owner_soname_not_framework():
    # libcge.so is a real owner soname (android-gpuimage-plus); must NOT be skipped as framework
    text = build_native_backtrace("libcge.so", [NF], RNG())
    fr = extract_fault_record(parse_logcat(text))
    assert fr is not None and fr.top_frame.soname == "libcge.so"
    assert fr.top_frame.key() == "AudioStreamAAudio::requestStart" and fr.confidence == "HIGH"


def test_no_anchor_returns_none():
    assert extract_fault_record(parse_logcat("07-05 10:34:07.221 1 1 I Foo: nothing crashed here")) is None
