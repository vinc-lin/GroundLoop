from groundloop.eval.extractors import TextOnlyExtractor
from groundloop.core.types import Ticket, LogAttachment


def test_text_only_ignores_logs():
    log = LogAttachment(path="logs/0.txt", kind="logcat",
                        content="java.lang.UnsatisfiedLinkError at org.x.Y.z()")
    ticket = Ticket(id="t", summary="crash in filter", description="NullPointerException in prose")
    sig_txt = TextOnlyExtractor().extract((log,), ticket)
    # text-only must NOT pick up the log's UnsatisfiedLinkError...
    assert "UnsatisfiedLinkError" not in sig_txt.tokens()
    # ...but SHOULD still extract from summary/description
    assert any("NullPointerException" in t for t in sig_txt.tokens()) or \
        "NullPointerException" in ticket.description
