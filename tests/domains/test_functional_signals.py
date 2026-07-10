from groundloop.core.types import LogAttachment, Ticket
from groundloop.domains.android_ivi.functional_signals import (
    PROSE_MARK, FunctionalTextExtractor, prose_query)


def test_extractor_packs_summary_and_description_into_symbols():
    t = Ticket(id="t", summary="No sound on Bluetooth", description="Audio stutters in podcasts")
    sig = FunctionalTextExtractor().extract((), t)
    assert len(sig.symbols) == 1 and sig.symbols[0].startswith(PROSE_MARK)
    q = prose_query(sig)
    assert "bluetooth" in q and "podcasts" in q          # summary AND description, lowercased
    assert not sig.packages and not sig.classes           # no crash tokens for a prose-only ticket


def test_extractor_keeps_optional_log_tokens_out_of_symbols():
    t = Ticket(id="t", summary="audio underrun", description="stutter")
    log = LogAttachment(path="l", kind="logcat", content="W AAudio: liboboe.so onAudioReady underrun")
    sig = FunctionalTextExtractor().extract((log,), t)
    assert "liboboe.so" in sig.libraries                  # log .so is captured as optional evidence
    assert len(sig.symbols) == 1 and sig.symbols[0].startswith(PROSE_MARK)   # symbols stays prose-only
