def test_recording_extractor_captures_last_signals():
    from groundloop.adapters.extractor_recording import RecordingExtractor
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
    from groundloop.core.types import Ticket
    rex = RecordingExtractor(AndroidSignalExtractor())
    t = Ticket(id="T-1", summary="NullPointerException in FooActivity", description="", logs=())
    sig = rex.extract(t.logs, t)
    assert rex.last_signals is sig                       # the exact object the loop saw
    assert sig is not None                               # delegated to the real extractor
