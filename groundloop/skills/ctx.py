"""The oracle-blind context a Skill predicate evaluates against. Built ONLY from loop-visible inputs:
the arm's extracted Signals (structured) + a raw lowercased haystack over the ticket + its logs. NEVER
reads _oracle/. The raw `text` haystack matters because AndroidSignalExtractor's error pattern only
captures *Error/*Exception and misses SIGSEGV/native/.so/JNI cues — native playbooks key on `text`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from groundloop.core.types import Signals, Ticket


@dataclass(frozen=True)
class SkillCtx:
    signals: Signals           # structured, arm-extracted
    repo: Optional[str]        # the predicted owning repo (loop prediction, not the oracle)
    text: str                  # lowercased haystack: summary + description + all log content

    def tokens(self) -> tuple[str, ...]:
        return self.signals.tokens()


def build_ctx(signals: Signals, ticket: Ticket, repo: Optional[str]) -> SkillCtx:
    parts = [ticket.summary, ticket.description, *(a.content for a in ticket.logs)]
    text = "\n".join(p for p in parts if p).lower()
    return SkillCtx(signals=signals, repo=repo, text=text)
