from groundloop.core.types import (
    LogAttachment,
    Signals,
    Ticket,
)


def test_package_imports():
    import groundloop
    assert groundloop is not None


def test_signals_tokens_are_deduped_distinctive():
    s = Signals(packages=("org.wysaid.nativePort",), classes=("org.wysaid.nativePort.CGEImageHandler",),
                methods=("nativeCreateHandler",), libraries=("libffmpeg.so",), errors=("UnsatisfiedLinkError",))
    toks = s.tokens()
    assert "org.wysaid.nativePort.CGEImageHandler" in toks and "libffmpeg.so" in toks
    assert len(toks) == len(set(toks))


def test_ticket_carries_logs_not_owning_repo():
    t = Ticket(id="GP-352", summary="crash", description="...", logs=(LogAttachment("logs/c.txt", "native", "x"),))
    assert t.status == "Open" and t.component == "" and t.logs[0].kind == "native"
