import random
from groundloop.core.types import LogAttachment, Ticket
from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor, fault_record_for_logs
from groundloop.synth.logs import Frame, build_java_logcat

JF = Frame(package="org.schabi.newpipe.streams", cls="SrtWriter", method="write",
           filename="SrtWriter.java", line=42)


def _logs():
    text = build_java_logcat([JF], "java.lang.NullPointerException", random.Random(1))
    noise = "\n".join(f"07-05 10:34:07.2{i:02d}  10  10 I ActivityManager: Start proc com.android.x{i}"
                      for i in range(50))
    return (LogAttachment(path="l", kind="logcat", content=noise + "\n" + text),)


def test_extract_yields_only_fault_tokens():
    sig = FaultSignalExtractor().extract(_logs(), Ticket(id="T", summary="s", description="d"))
    assert "org.schabi.newpipe.streams" in sig.packages
    assert "SrtWriter" in sig.classes and "write" in sig.methods
    assert not any(p.startswith("com.android") for p in sig.packages)


def test_no_fault_yields_empty_signals():
    sig = FaultSignalExtractor().extract(
        (LogAttachment(path="l", kind="logcat", content="07-05 10:34:07.221 1 1 I Foo: fine"),),
        Ticket(id="T", summary="s", description="d"))
    assert sig.tokens() == ()


def test_fault_record_for_logs_roundtrip():
    fr = fault_record_for_logs(_logs())
    assert fr is not None and fr.top_frame.key() == "org.schabi.newpipe.streams.SrtWriter.write"
