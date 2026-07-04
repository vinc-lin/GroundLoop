from groundloop.core.types import LogAttachment, Ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor

LOG = (
    "E/AndroidRuntime: FATAL EXCEPTION: GLThread 549\n"
    "java.lang.UnsatisfiedLinkError: No implementation found for "
    "long org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler()\n"
    '  at org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler(Native Method)\n'
    'E/libCGE_java: Load library for \'cge\' failed!: couldn\'t find "libffmpeg.so"\n'
)


def test_extracts_android_signals():
    s = AndroidSignalExtractor().extract((LogAttachment("logs/crash.txt", "logcat", LOG),),
                                         Ticket("GP-352", "crash", ""))
    assert "org.wysaid.nativePort.CGEImageHandler" in s.classes
    assert "org.wysaid.nativePort" in s.packages
    assert "nativeCreateHandler" in s.methods
    assert "libffmpeg.so" in s.libraries
    assert "UnsatisfiedLinkError" in s.errors
    assert "org.wysaid.nativePort.CGEImageHandler" in s.tokens()
