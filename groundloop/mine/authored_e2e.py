"""[authored] INTEGRATED, oracle-blind end-to-end over the authored crash corpus.

Treats match -> localize -> fix as ONE compounding process: real match -> real localize (crash-token query)
-> real plan fix, each stage feeding the next. Nothing in the loop sees the oracle; grading reads it offline.
This is a MECHANICS read (arm-selection / mechanism-debugging), NOT effectiveness; never `[production]`.

Usage: .venv/bin/python -m groundloop.mine.authored_e2e [flood|routing] [summary|tokens]
       default: routing tokens  (the optimized config). needs an atlas + the gateway (KLOOP_PRODUCE_*),
       and the fleet checkouts at /mnt/x/code/corpora/<repo> (worktree = the real checkout, read-only).
"""
from __future__ import annotations

import glob
import json
import os
import sys

from groundloop.adapters.fix.planning import PlanningFixEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.labs.fault_routing import FaultRoutingIndex
from groundloop.adapters.model.gateway import GatewayModel
from groundloop.core.types import LogAttachment, RepoRef, Ticket, WorkTree
from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.fix.patch import norm_path, references_api_code

ATLAS = os.environ.get("KLOOP_ATLAS_DB", "/dev/shm/atlas-fleet.db")
CORPORA = os.environ.get("KLOOP_CORPORA_ROOT", "/mnt/x/code/corpora")
DATASET = "groundloop/mine/data/authored"


def _hit1(locs: list[str], exp: list[str]) -> bool:
    return bool(locs) and any(locs[0].split("/")[-1] == e.split("/")[-1] or locs[0].endswith(e) or e.endswith(locs[0])
                              for e in exp)


def main(argv: list[str]) -> int:
    match_arm = argv[1] if len(argv) > 1 else "routing"
    loc_query = argv[2] if len(argv) > 2 else "tokens"
    if match_arm == "routing":
        idx, ext = FaultRoutingIndex(ATLAS), FaultSignalExtractor()
    else:
        idx, ext = AtlasIndex(ATLAS), AndroidSignalExtractor()
    model = GatewayModel(os.environ["KLOOP_PRODUCE_BASE_URL"], os.environ["KLOOP_PRODUCE_API_KEY"],
                         os.environ.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"))
    fx = PlanningFixEngine(model)
    catalog = [RepoRef(c["name"]) for c in json.load(open(os.path.join(DATASET, "catalog.json")))]

    n = m = loc = res = 0
    for tp in sorted(glob.glob(os.path.join(DATASET, "crash-*", "ticket.json"))):
        d = os.path.dirname(tp)
        t = json.load(open(tp))
        o = json.load(open(os.path.join(d, "_oracle", "oracle.json")))
        lg = tuple(LogAttachment(path=x.get("path", ""), kind=x.get("kind", "other"), content=x.get("content", ""))
                   for x in t["logs"])
        tk = Ticket(id=t["id"], summary=t["summary"], description=t["description"], component="", logs=lg,
                    status="Open")
        sig = ext.extract(tk.logs, tk)
        n += 1
        ranked = idx.rank_repos(sig, catalog)
        chosen = ranked[0].repo.name if ranked else None
        m += chosen == o["owning_repo"]
        query = " ".join(sig.tokens()) if loc_query == "tokens" else tk.summary
        locs = idx.retrieve(RepoRef(chosen), query) if chosen else []
        loc += _hit1(locs, o["expected_files"])
        patch = fx.propose(WorkTree(RepoRef(chosen), f"{CORPORA}/{chosen}"), tk, locs) if chosen else None
        resolved = False
        if patch and patch.diff.strip():
            resolved = bool({norm_path(f) for f in patch.files} & {norm_path(e) for e in o["expected_files"]}) \
                and any(references_api_code(patch.diff, a) for a in o["required_apis"])
        res += resolved

    print(f"[authored] integrated e2e (match={match_arm} localize={loc_query} fix=plan+retry) n={n}")
    print(f"  match recall@1  : {m}/{n} ({m / n:.2f})")
    print(f"  localize file@1 : {loc}/{n} ({loc / n:.2f})")
    print(f"  fix resolved    : {res}/{n} ({res / n:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
