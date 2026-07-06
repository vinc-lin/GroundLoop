"""Synth failure-log generation — the signal it produces must be real (extractable + owner-matching),
and the crash-class registry must be able to fire EACH of the 12 dev-experience KB skills."""
import pytest

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.skills.mock import MockSkillRegistry
from groundloop.core.types import LogAttachment, RepoRef, Ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.engines.atlas.store import Store
from groundloop.kb.validate import SEED_PATH as KB_SEED_PATH
from groundloop.skills.ctx import build_ctx
from groundloop.synth import logs as S
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _java_frame():
    return [S.Frame(package="com.aaos.player", cls="PlaybackController", method="onEvent",
                    filename="PlaybackController.java", line=142)]


def _native_frame():
    return [S.Frame(package="", cls="AudioEngineImpl", method="render",
                    filename="AudioEngineImpl.cpp", line=88)]


# --------------------------------------------------------------------------- parsing / base builders

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


def test_java_logcat_message_and_extra_lines_are_deterministic():
    fr = _java_frame()
    text = S.build_java_logcat(fr, "java.lang.IllegalStateException", S._rng("d"),
                               message="ZZUNIQUEZZ", extra_lines=["!!! EXTRA MARKER !!!"])
    assert "java.lang.IllegalStateException: ZZUNIQUEZZ" in text
    assert "!!! EXTRA MARKER !!!" in text
    assert "PlaybackController" in text


def test_native_backtrace_has_so_and_symbol():
    rng = S._rng("c2")
    fr = [S.Frame(package="", cls="AudioStreamAAudio", method="open", filename="AudioStreamAAudio.cpp", line=88)]
    text = S.build_native_backtrace("liboboe.so", fr, rng)
    assert "backtrace:" in text and "liboboe.so" in text and "AudioStreamAAudio::open" in text


# --------------------------------------------------------------------------- new builder shape tests

def test_native_abort_shape():
    text = S.build_native_abort("libowner.so", _native_frame(), S._rng("a"))
    assert "signal 6 (SIGABRT)" in text
    assert "free(): double free detected" in text
    assert "libowner.so" in text and "AudioEngineImpl::render" in text


def test_audio_underrun_shape():
    text = S.build_audio_underrun("liboboe.so", _native_frame(), S._rng("b"))
    assert "underrun" in text.lower()
    assert "onAudioReady" in text and "libaaudio.so" in text
    assert "liboboe.so" in text and "AudioEngineImpl::render" in text


def test_anr_shape():
    text = S.build_anr(_java_frame(), S._rng("c"))
    assert "ANR in" in text
    assert "Input dispatching timed out" in text
    assert "PlaybackController" in text


@pytest.mark.parametrize("builder,signature", [
    (S.build_fgs_crash, "did not then call service.startforeground()"),
    (S.build_ise_saved_crash, "can not perform this action after onsaveinstancestate"),
    (S.build_binder_too_large_crash, "failed binder transaction"),
    (S.build_media_illegal_state_crash, "called in state 3"),
    (S.build_camera_gl_crash, "surface has already been released"),
    (S.build_cme_crash, "concurrentmodificationexception"),
    (S.build_native_lib_load_crash, "no implementation found"),
    (S.build_fragment_npe_crash, "on a null object reference"),
])
def test_java_wrapper_shape(builder, signature):
    text = builder(_java_frame(), S._rng("w")).lower()
    assert signature in text
    assert "playbackcontroller" in text                 # owner symbol still present (grounding)


# --------------------------------------------------------------------------- 12-skill firing

def test_all_twelve_kb_skills_fire():
    """Each KB skill must have a crash class whose synthesized log makes that skill's predicate fire."""
    reg = MockSkillRegistry.load(KB_SEED_PATH)
    kb_ids = [s.id for s in reg.skills]
    assert len(kb_ids) == 12
    covered = {cc.skill_id for cc in S.CRASH_CLASSES}
    assert covered == set(kb_ids), f"registry != KB skills: {covered ^ set(kb_ids)}"

    jf = [S.Frame(package="com.aaos.player.ui", cls="PlayerView", method="onEvent",
                  filename="PlayerView.java", line=42)]
    nf = [S.Frame(package="", cls="NativeEngine", method="process",
                  filename="NativeEngine.cpp", line=88)]
    for cc in S.CRASH_CLASSES:
        rng = S._rng(cc.skill_id)
        log = cc.builder("libowner.so", nf, rng) if cc.surface == "native" else cc.builder(jf, rng)
        la = LogAttachment(path="logs/crash.txt", kind="logcat", content=log)
        tk = Ticket(id="t", summary="app failure", description="", logs=(la,))
        sig = AndroidSignalExtractor().extract((la,), tk)
        ctx = build_ctx(sig, tk, None)
        fired = {s.id for s in reg.select(ctx)}
        assert cc.skill_id in fired, f"{cc.skill_id} did not fire; fired={sorted(fired)}"


# --------------------------------------------------------------------------- selection determinism

def test_select_crash_class_deterministic_and_affinity(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    nf = S.crash_frames(store, "android-gpuimage-plus",
                        ["library/src/main/jni/cge/CGEImageHandler.cpp"], S._rng("g"))
    assert nf
    cc1 = S.select_crash_class("android-gpuimage-plus", nf, "case-1")
    cc2 = S.select_crash_class("android-gpuimage-plus", nf, "case-1")
    assert cc1 == cc2 and cc1.surface == "native"       # deterministic
    # an oboe-affinity class is never selected for a non-oboe native owner (affinity excludes it)
    for i in range(40):
        cc = S.select_crash_class("android-gpuimage-plus", nf, f"c{i}")
        assert cc.skill_id != "realtime-audio-callback-underrun"


# --------------------------------------------------------------------------- grounding regressions

def test_synth_log_extracts_owner_signal_and_matches(tmp_path):
    """End-to-end (native surface): a synth log for gpuimage must (a) yield real signal via the
    extractor and (b) rank gpuimage top-1 over the fixture atlas — i.e. it exercises the matcher."""
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    text, kind = S.synth_log_for_case(
        store, "android-gpuimage-plus",
        ["library/src/main/jni/cge/CGEImageHandler.cpp"], "gpuimage-1")
    assert kind == "native" and "libCGE.so" in text and "CGEImageHandler" in text

    la = LogAttachment(path="logs/crash.txt", kind=kind, content=text)
    sig = AndroidSignalExtractor().extract((la,), Ticket(id="t", summary="", description=""))
    assert sig.tokens()                                   # non-empty: real signal
    ranked = AtlasIndex(db).rank_repos(sig, [RepoRef("android-gpuimage-plus"),
                                             RepoRef("organicmaps"), RepoRef("cameraview")])
    assert ranked[0].repo.name == "android-gpuimage-plus"


def test_java_crash_class_grounds_to_owner(tmp_path):
    """A java crash-class log built from the owner's real frames must still rank the owner top-1."""
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    rng = S._rng("cam-1")
    frames = S.crash_frames(
        store, "cameraview",
        ["cameraview/src/main/java/com/otaliastudios/cameraview/CameraView.java"], rng)
    assert frames
    text = S.build_ise_saved_crash(frames, rng)
    la = LogAttachment(path="logs/crash.txt", kind="logcat", content=text)
    sig = AndroidSignalExtractor().extract((la,), Ticket(id="t", summary="", description=""))
    ranked = AtlasIndex(db).rank_repos(
        sig, [RepoRef("cameraview"), RepoRef("androidx-media"), RepoRef("android-gpuimage-plus")])
    assert ranked[0].repo.name == "cameraview"
