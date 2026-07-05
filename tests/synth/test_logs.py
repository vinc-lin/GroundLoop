"""Synth failure-log generation — the signal it produces must be real (extractable + owner-matching)."""
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import RepoRef
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.engines.atlas.store import Store
from groundloop.synth import logs as S
from tests.fixtures.atlas_fixture import build_atlas_fixture


def test_parse_source_file_java_native_and_test_exclusion():
    assert S.parse_source_file("app/src/main/java/org/schabi/newpipe/streams/W.java") == (
        "java", "org.schabi.newpipe.streams", "W")
    assert S.parse_source_file("src/aaudio/AudioStreamAAudio.cpp") == ("native", "", "AudioStreamAAudio")
    # a fix's test file is not the crash site -> excluded
    assert S.parse_source_file("app/src/test/java/org/x/WTest.java") == (None, None, None)


def test_java_logcat_is_frame_shaped():
    rng = S._rng("c1")
    fr = [S.Frame(package="org.schabi.newpipe.streams", cls="SrtFromTtmlWriter",
                  method="write", filename="SrtFromTtmlWriter.java", line=123)]
    text = S.build_java_logcat(fr, "java.lang.NullPointerException", rng)
    assert "FATAL EXCEPTION" in text
    assert "at org.schabi.newpipe.streams.SrtFromTtmlWriter.write(SrtFromTtmlWriter.java:123)" in text


def test_native_backtrace_has_so_and_symbol():
    rng = S._rng("c2")
    fr = [S.Frame(package="", cls="AudioStreamAAudio", method="open", filename="AudioStreamAAudio.cpp", line=88)]
    text = S.build_native_backtrace("liboboe.so", fr, rng)
    assert "backtrace:" in text and "liboboe.so" in text and "AudioStreamAAudio::open" in text


def test_synth_log_extracts_owner_signal_and_matches(tmp_path):
    """End-to-end: a synth log for gpuimage must (a) yield real signal via the extractor and
    (b) rank gpuimage top-1 over the fixture atlas — i.e. it exercises the matcher for real."""
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    text, kind = S.synth_log_for_case(
        store, "android-gpuimage-plus",
        ["library/src/main/jni/cge/CGEImageHandler.cpp"], "gpuimage-1")
    assert kind == "native_backtrace" and "libCGE.so" in text and "CGEImageHandler" in text

    # the extractor must find signal in the synth log (this is the whole point)
    class T:  # minimal ticket: no prose, all signal from the log
        description = ""
    from groundloop.engines.atlas.store import Unit  # noqa: F401  (kept: fixture uses Units)
    from groundloop.core.types import Signals  # noqa: F401
    la = type("LA", (), {"content": text, "kind": kind, "path": "logs/crash.txt"})()
    sig = AndroidSignalExtractor().extract((la,), T())
    assert sig.tokens()                                   # non-empty: real signal
    ranked = AtlasIndex(db).rank_repos(sig, [RepoRef("android-gpuimage-plus"),
                                             RepoRef("organicmaps"), RepoRef("cameraview")])
    assert ranked[0].repo.name == "android-gpuimage-plus"
