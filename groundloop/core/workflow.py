from __future__ import annotations
from dataclasses import dataclass, field
from groundloop.core.ports import IssueSource, SignalExtractor, RepoEstate, CodeIndex, FixEngine, ChangeSink
from groundloop.core.types import RepoScore, RepoRef, Patch, Change


@dataclass
class RunRecord:
    ticket_id: str
    ranked: list[RepoScore]
    chosen: RepoRef
    locations: list[str]
    patch: Patch
    change: Change
    bound: bool
    events: list[str] = field(default_factory=list)


def run_ticket(ticket_id: str, *, issues: IssueSource, extractor: SignalExtractor, estate: RepoEstate,
               index: CodeIndex, fixer: FixEngine, changes: ChangeSink) -> RunRecord:
    """Deterministic control plane: ticket → signals → MATCH → materialize → localize → fix → bind.
    Grading is a separate offline pass and is never called here (the loop never sees the oracle)."""
    ev: list[str] = []
    ticket = issues.fetch(ticket_id)
    ev.append("intake")
    signals = extractor.extract(ticket.logs, ticket)
    ev.append("extract")
    ranked = index.rank_repos(signals, estate.catalog())
    ev.append("match")
    chosen = ranked[0].repo
    wt = estate.materialize(chosen)
    ev.append("materialize")
    locations = index.retrieve(chosen, ticket.summary)
    ev.append("localize")
    patch = fixer.propose(wt, ticket, locations)
    ev.append("fix")
    change = changes.submit(chosen, patch, ticket)
    ev.append("submit")
    changes.bind(change, ticket)
    ev.append("bind")
    return RunRecord(ticket_id=ticket_id, ranked=ranked, chosen=chosen, locations=list(locations),
                     patch=patch, change=change, bound=True, events=ev)
