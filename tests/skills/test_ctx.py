from groundloop.core.types import Signals, Ticket, LogAttachment
from groundloop.skills.ctx import build_ctx


def test_build_ctx_lowercases_and_concatenates_ticket_and_logs():
    sig = Signals(libraries=("libffmpeg.so",), errors=("UnsatisfiedLinkError",))
    tk = Ticket(id="GP-352", summary="App CRASHES on GL thread", description="Attaching the logcat.",
                logs=(LogAttachment(path="l", kind="logcat",
                                    content="No implementation found for nativeCreateHandler()"),))
    ctx = build_ctx(sig, tk, "android-gpuimage-plus")
    assert ctx.repo == "android-gpuimage-plus"
    assert ctx.signals is sig
    # text is one lowercased haystack over summary + description + every log's content
    assert "app crashes on gl thread" in ctx.text
    assert "attaching the logcat." in ctx.text
    assert "nativecreatehandler" in ctx.text


def test_build_ctx_is_oracle_blind_by_construction():
    # build_ctx takes only loop-visible values; it must not accept or read an oracle
    tk = Ticket(id="t", summary="s", description="d")
    ctx = build_ctx(Signals(), tk, None)
    assert ctx.repo is None and ctx.text == "s\nd"
