from __future__ import annotations
from typing import Sequence
from groundloop.core.ports import Model
from groundloop.core.types import WorkTree, Ticket, Patch


class CannedFixEngine:
    """Minimal FixEngine: emits a deterministic unified-diff stub over the given locations.
    The real agentic engine (wrapping fixrunner) replaces this in a later milestone."""

    def __init__(self, model: Model):
        self.model = model

    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch:
        self.model.complete(f"Fix {ticket.id} in {list(locations)}")   # exercise the Model port
        target = locations[0] if locations else "UNKNOWN"
        diff = f"--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-// bug\n+// fixed for {ticket.id}\n"
        return Patch(diff=diff, files=tuple(locations) or (target,))
