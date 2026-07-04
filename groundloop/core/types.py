from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class LogAttachment:
    path: str
    kind: str            # 'logcat'|'stacktrace'|'native'|'anr'|'other'
    content: str


@dataclass(frozen=True)
class Ticket:
    id: str
    summary: str
    description: str
    component: str = ""                       # MUST NOT be the owning repo
    comments: tuple[dict, ...] = ()
    logs: tuple[LogAttachment, ...] = ()
    status: str = "Open"


@dataclass(frozen=True)
class Signals:
    packages: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()             # native symbols
    libraries: tuple[str, ...] = ()           # .so names
    errors: tuple[str, ...] = ()

    def tokens(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for group in (self.classes, self.packages, self.methods, self.symbols, self.libraries, self.errors):
            for t in group:
                if t:
                    seen.setdefault(t, None)
        return tuple(seen)


@dataclass(frozen=True)
class RepoRef:
    name: str


@dataclass(frozen=True)
class RepoScore:
    repo: RepoRef
    score: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkTree:
    repo: RepoRef
    path: str


@dataclass(frozen=True)
class Patch:
    diff: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Change:
    change_id: str
    commit_subject: str
    ticket_id: str
    patch: Patch


@dataclass(frozen=True)
class Oracle:
    owning_repo: str
    expected_files: tuple[str, ...] = ()
    required_apis: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scores:
    repo_recall_at_1: float
    repo_rank: int
    localization_recall: float
    bound: bool
