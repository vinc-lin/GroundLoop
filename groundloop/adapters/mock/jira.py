from __future__ import annotations
import json
from pathlib import Path
from groundloop.core.types import Ticket, LogAttachment


class MockJira:
    """Filesystem-backed mock JIRA: fetch from dataset/<id>/, write-back to a per-case ledger."""

    def __init__(self, root: str):
        self.root = Path(root)

    def fetch(self, ticket_id: str) -> Ticket:
        d = self.root / ticket_id
        raw = json.loads((d / "ticket.json").read_text())
        logs = tuple(
            LogAttachment(path=a["path"], kind=a.get("kind", "other"),
                          # errors="replace": a real logcat can carry non-UTF-8 bytes; a strict decode would
                          # raise UnicodeDecodeError and abort intake for the whole case. Byte-identical for
                          # well-formed UTF-8 (only invalid bytes become U+FFFD).
                          content=(d / a["path"]).read_text(errors="replace"))
            for a in raw.get("logs", [])
        )
        return Ticket(id=raw["id"], summary=raw.get("summary", ""), description=raw.get("description", ""),
                      component=raw.get("component", ""), comments=tuple(raw.get("comments", [])),
                      logs=logs, status=raw.get("status", "Open"))

    def _append(self, ticket_id: str, rec: dict) -> None:
        with (self.root / ticket_id / "ledger.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def post_comment(self, ticket_id: str, body: str) -> None:
        self._append(ticket_id, {"comment": body})

    def transition(self, ticket_id: str, status: str) -> None:
        self._append(ticket_id, {"transition": status})
