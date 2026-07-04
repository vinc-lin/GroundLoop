from __future__ import annotations
import argparse
import asyncio
from groundloop.core.workflow import run_ticket
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import MockEstate
from groundloop.adapters.index.simple import TokenIndex
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor


def _run_index(args) -> int:
    from groundloop.config.settings import Settings
    from groundloop.engines.atlas.store import Store
    from groundloop.engines.atlas.embed import GatewayEmbedder
    from groundloop.engines.atlas.registry import load_registry
    import groundloop.engines.atlas.index as _index_mod

    settings = Settings.load()
    registry_path = args.registry or settings.registry
    if not registry_path:
        print("gloop index: --registry is required (or set KLOOP_REGISTRY)")
        return 2

    entries = load_registry(registry_path)
    atlas_db = settings.atlas_db or "atlas.db"
    store = Store(atlas_db)
    embedder = GatewayEmbedder(settings.embed_base_url, settings.embed_api_key,
                               settings.embed_model)
    counts = asyncio.run(_index_mod.index_all(entries, store, embedder))
    for name, n in counts.items():
        print(f"indexed {name}: {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gloop")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    for flag in ("--case", "--dataset", "--catalog", "--index", "--work", "--changes"):
        r.add_argument(flag, required=True)

    ix = sub.add_parser("index", help="build atlas.db from a registry")
    ix.add_argument("--registry", default="", help="path to atlas.toml (overrides KLOOP_REGISTRY)")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        issues = MockJira(args.dataset)
        rec = run_ticket(args.case, issues=issues, extractor=AndroidSignalExtractor(),
                         estate=MockEstate(args.catalog, args.work), index=TokenIndex(args.index),
                         fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                         changes=MockGerrit(args.changes, issues))
        print(f"case={rec.ticket_id} matched={rec.chosen.name} change={rec.change.change_id}")
        return 0
    if args.cmd == "index":
        return _run_index(args)
    return 1
