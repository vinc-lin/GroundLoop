from __future__ import annotations
from typing import Protocol, Sequence, runtime_checkable
from groundloop.core.types import (
    Ticket, LogAttachment, Signals, RepoRef, RepoScore, WorkTree, Patch, Change,
)


@runtime_checkable
class IssueSource(Protocol):
    def fetch(self, ticket_id: str) -> Ticket: ...
    def post_comment(self, ticket_id: str, body: str) -> None: ...
    def transition(self, ticket_id: str, status: str) -> None: ...


@runtime_checkable
class SignalExtractor(Protocol):
    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals: ...


@runtime_checkable
class RepoEstate(Protocol):
    def catalog(self) -> list[RepoRef]: ...
    def materialize(self, repo: RepoRef) -> WorkTree: ...


@runtime_checkable
class CodeIndex(Protocol):
    def rank_repos(self, signals: Signals, catalog: Sequence[RepoRef]) -> list[RepoScore]: ...
    def retrieve(self, repo: RepoRef, query: str) -> list[str]: ...


@runtime_checkable
class FixEngine(Protocol):
    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch: ...


@runtime_checkable
class ChangeSink(Protocol):
    def submit(self, repo: RepoRef, patch: Patch, ticket: Ticket) -> Change: ...
    def bind(self, change: Change, ticket: Ticket) -> None: ...


@runtime_checkable
class Model(Protocol):
    def complete(self, prompt: str) -> str: ...
