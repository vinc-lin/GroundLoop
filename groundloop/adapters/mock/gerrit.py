from __future__ import annotations
import hashlib
import json
from pathlib import Path
from groundloop.core.ports import IssueSource
from groundloop.core.types import RepoRef, Patch, Ticket, Change


class MockGerrit:
    """Synthesize a Gerrit Change (deterministic Change-Id + JIRA key in the subject) and bind it back
    to the ticket: append to a changes ledger AND transition the ticket via the IssueSource write-back."""

    def __init__(self, changes_path: str, issues: IssueSource):
        self.changes_path = Path(changes_path)
        self.issues = issues

    def submit(self, repo: RepoRef, patch: Patch, ticket: Ticket) -> Change:
        h = hashlib.sha1(f"{repo.name}\0{ticket.id}\0{patch.diff}".encode()).hexdigest()
        return Change(change_id="I" + h, commit_subject=f"[{ticket.id}] fix in {repo.name}",
                      ticket_id=ticket.id, patch=patch)

    def bind(self, change: Change, ticket: Ticket) -> None:
        with self.changes_path.open("a") as fh:
            fh.write(json.dumps({"change_id": change.change_id, "ticket": ticket.id,
                                 "subject": change.commit_subject, "files": list(change.patch.files)}) + "\n")
        self.issues.post_comment(ticket.id, f"Fix submitted as {change.change_id}")
        self.issues.transition(ticket.id, "Resolved")
