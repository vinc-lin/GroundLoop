"""[authored] arm-comparison probe — isolated, deterministic (FTS5, no LLM, no gateway).

For each authored case, measures on the ORACLE repo:
  - flood MATCH recall@1 (AtlasIndex.rank_repos over the extracted signals), and
  - localize file@1 with the ticket SUMMARY query vs the extracted CRASH-TOKEN query.

This is the `[authored]` mechanics check that validated `--localize tokens` (crash-token query) over the
summary-based default on realistic crash cases. NOT an effectiveness measurement; never `[production]`; never
folded into the mined `[proxy]` aggregate (see groundloop/mine/data/authored/README.md).

Usage:  .venv/bin/python -m groundloop.mine.authored_probe <atlas.db> <dataset_dir>
        (dataset_dir default: groundloop/mine/data/authored ; atlas default: /dev/shm/atlas-fleet.db)
"""
from __future__ import annotations

import glob
import json
import os
import sys

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import LogAttachment, RepoRef, Ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor


def _ticket(t: dict) -> Ticket:
    logs = tuple(LogAttachment(path=lg.get("path", ""), kind=lg.get("kind", "other"),
                               content=lg.get("content", "")) for lg in t.get("logs", []))
    return Ticket(id=t["id"], summary=t.get("summary", ""), description=t.get("description", ""),
                  component=t.get("component", ""), logs=logs, status=t.get("status", "Open"))


def _hit1(locs: list[str], expected: list[str]) -> bool:
    if not locs:
        return False
    top = locs[0]
    return any(top.split("/")[-1] == e.split("/")[-1] or top.endswith(e) or e.endswith(top)
               for e in expected)


def main(argv: list[str]) -> int:
    atlas = argv[1] if len(argv) > 1 else "/dev/shm/atlas-fleet.db"
    dataset = argv[2] if len(argv) > 2 else "groundloop/mine/data/authored"
    idx = AtlasIndex(atlas)
    ext = AndroidSignalExtractor()
    catalog = [RepoRef(c["name"]) for c in json.load(open(os.path.join(dataset, "catalog.json")))]

    n = m_hit = loc_summary = loc_tokens = 0
    for tp in sorted(glob.glob(os.path.join(dataset, "crash-*", "ticket.json"))):
        cid = os.path.basename(os.path.dirname(tp))
        t = json.load(open(tp))
        orc = json.load(open(os.path.join(os.path.dirname(tp), "_oracle", "oracle.json")))
        tk = _ticket(t)
        sig = ext.extract(tk.logs, tk)
        oracle, expected = orc["owning_repo"], orc["expected_files"]
        n += 1
        ranked = idx.rank_repos(sig, catalog)
        m = bool(ranked) and ranked[0].repo.name == oracle
        m_hit += m
        hs = _hit1(idx.retrieve(RepoRef(oracle), tk.summary), expected)
        ht = _hit1(idx.retrieve(RepoRef(oracle), " ".join(sig.tokens())), expected)
        loc_summary += hs
        loc_tokens += ht
        print(f"{cid:<32} match={'HIT' if m else 'miss':<4} "
              f"loc@1 summary={'HIT' if hs else '.'} tokens={'HIT' if ht else '.'}")

    print(f"\n[authored] n={n} · isolated localize on the oracle repo · FTS5, no judge")
    print(f"  MATCH flood recall@1    : {m_hit}/{n} ({m_hit / n:.2f})")
    print(f"  LOCALIZE file@1 summary : {loc_summary}/{n} ({loc_summary / n:.2f})  (current default query)")
    print(f"  LOCALIZE file@1 tokens  : {loc_tokens}/{n} ({loc_tokens / n:.2f})  (--localize tokens / crash-token query)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
