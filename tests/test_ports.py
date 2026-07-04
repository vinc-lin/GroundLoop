from groundloop.core import ports
from groundloop.core.types import Ticket


def test_ports_are_runtime_checkable_protocols():
    class FakeIssues:
        def fetch(self, ticket_id): return Ticket(ticket_id, "", "")
        def post_comment(self, ticket_id, body): pass
        def transition(self, ticket_id, status): pass
    assert isinstance(FakeIssues(), ports.IssueSource)

    class NotAnIndex:
        pass
    assert not isinstance(NotAnIndex(), ports.CodeIndex)
