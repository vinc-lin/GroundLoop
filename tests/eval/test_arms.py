from groundloop.eval.arms import build_arms, Arm
from groundloop.core.types import Ticket, LogAttachment


class _FakeIndex:
    def rank_repos(self, signals, catalog):
        return []


def test_build_arms_membership_text_and_logs():
    arms = build_arms(membership_index=_FakeIndex())
    names = {a.name for a in arms}
    assert names == {"membership+text", "membership+logs"}
    assert all(isinstance(a, Arm) for a in arms)


def test_text_arm_drops_logs_logs_arm_keeps():
    arms = {a.name: a for a in build_arms(membership_index=_FakeIndex())}
    log = LogAttachment(path="l", kind="logcat", content="java.lang.UnsatisfiedLinkError")
    ticket = Ticket(id="t", summary="s", description="d")
    txt = arms["membership+text"].extractor.extract((log,), ticket)
    logs = arms["membership+logs"].extractor.extract((log,), ticket)
    assert "UnsatisfiedLinkError" not in txt.tokens()
    assert "UnsatisfiedLinkError" in logs.tokens()
