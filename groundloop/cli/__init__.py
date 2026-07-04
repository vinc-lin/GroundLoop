from __future__ import annotations
import argparse
from groundloop.core.workflow import run_ticket
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import MockEstate
from groundloop.adapters.index.simple import TokenIndex
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gloop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    for flag in ("--case", "--dataset", "--catalog", "--index", "--work", "--changes"):
        r.add_argument(flag, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        issues = MockJira(args.dataset)
        rec = run_ticket(args.case, issues=issues, extractor=AndroidSignalExtractor(),
                         estate=MockEstate(args.catalog, args.work), index=TokenIndex(args.index),
                         fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                         changes=MockGerrit(args.changes, issues))
        print(f"case={rec.ticket_id} matched={rec.chosen.name} change={rec.change.change_id}")
        return 0
    return 1
