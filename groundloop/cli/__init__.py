from __future__ import annotations
import argparse
import asyncio
from groundloop.core.workflow import run_ticket
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import MockEstate
from groundloop.adapters.index.simple import TokenIndex
from groundloop.adapters.index.atlas import AtlasIndex
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


def _run_doctor(args) -> int:
    """Check index readiness; rc 0 if atlas.db is usable."""
    import os
    from groundloop.config.settings import Settings

    settings = Settings.load()
    atlas_db = getattr(args, "atlas_db", None) or settings.atlas_db

    if not atlas_db:
        print("doctor: atlas.db not configured — pass --atlas-db or set KLOOP_ATLAS_DB")
        return 1

    # Check atlas.db exists + is readable
    if not os.path.isfile(atlas_db):
        print(f"doctor: atlas.db not found: {atlas_db}")
        return 1

    try:
        from groundloop.engines.atlas.store import Store
        store = Store(atlas_db)
        repo_states = store.list_repo_states()
        repo_count = len(repo_states)
        unit_total = sum(rs.unit_count for rs in repo_states)
        print(f"atlas.db  OK  {atlas_db}")
        print(f"  repos: {repo_count}  units: {unit_total}")
        for rs in repo_states:
            print(f"  - {rs.repo}  units={rs.unit_count}  head={rs.indexed_repo_head or 'n/a'}")
    except Exception as exc:
        print(f"doctor: atlas.db not readable: {exc}")
        return 1

    # Embed gateway check (optional — gated by configuration)
    embed_base_url = settings.embed_base_url
    if embed_base_url:
        try:
            import httpx
            resp = httpx.get(embed_base_url.rstrip("/") + "/health", timeout=3.0)
            if resp.status_code < 400:
                print(f"embed gateway  OK  {embed_base_url}")
            else:
                print(f"embed gateway  WARN  {embed_base_url} (status {resp.status_code})")
        except Exception as exc:
            print(f"embed gateway  WARN  {embed_base_url} (unreachable: {exc})")
    else:
        print("embed gateway  SKIP  (KLOOP_EMBED_BASE_URL not set)")

    # CBM check (optional — gated by configuration)
    cbm_ready = os.environ.get("KLOOP_CBM_READY", "")
    if cbm_ready:
        try:
            from groundloop.engines.lore.deploy import resolve_launch_spec
            spec = resolve_launch_spec(environ=dict(os.environ))
            print(f"CBM  OK  launch={spec}")
        except Exception as exc:
            print(f"CBM  WARN  ({exc})")
    else:
        print("CBM  SKIP  (KLOOP_CBM_READY not set)")

    print("\nreadiness: READY (atlas.db usable)")
    return 0


def _run_produce(args) -> int:
    """Invoke the migrated CodeWiki generator for --repo <path> --out <wiki_dir>."""
    import os
    from pathlib import Path
    from groundloop.engines.produce.cli.adapters.doc_generator import CLIDocumentationGenerator

    repo_path = Path(args.repo).expanduser().resolve()
    output_dir = Path(args.out).expanduser().resolve()

    # Build a minimal config from env vars (mirrors kl produce generate env-driven config)
    config = {
        # deepseek-chat is the served, live-validated produce model on the LiteLLM gateway
        # (no OpenAI access in this environment). Override via KLOOP_PRODUCE_*_MODEL.
        "main_model": os.environ.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"),
        "cluster_model": os.environ.get("KLOOP_PRODUCE_CLUSTER_MODEL", "deepseek-chat"),
        "fallback_model": os.environ.get("KLOOP_PRODUCE_FALLBACK_MODEL", "deepseek-chat"),
        "base_url": os.environ.get("KLOOP_PRODUCE_BASE_URL", ""),
        "api_key": os.environ.get("KLOOP_PRODUCE_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        "provider": os.environ.get("KLOOP_PRODUCE_PROVIDER", "openai-compatible"),
        "aws_region": os.environ.get("KLOOP_PRODUCE_AWS_REGION", "us-east-1"),
    }

    generator = CLIDocumentationGenerator(
        repo_path=repo_path,
        output_dir=output_dir,
        config=config,
        verbose=False,
    )
    generator.generate()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gloop")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    for flag in ("--case", "--dataset", "--catalog", "--work", "--changes"):
        r.add_argument(flag, required=True)
    # --index and --index-db are mutually exclusive; at least one must be provided
    idx_group = r.add_mutually_exclusive_group(required=True)
    idx_group.add_argument("--index", default=None,
                           help="path to token-index JSON (M0 stub)")
    idx_group.add_argument("--index-db", default=None,
                           help="path to atlas.db (real AtlasIndex)")

    ix = sub.add_parser("index", help="build atlas.db from a registry")
    ix.add_argument("--registry", default="", help="path to atlas.toml (overrides KLOOP_REGISTRY)")

    doc = sub.add_parser("doctor", help="check index readiness")
    doc.add_argument("--atlas-db", default="",
                     help="path to atlas.db (overrides KLOOP_ATLAS_DB)")

    prod = sub.add_parser("produce", help="generate a CodeWiki for a repo")
    prod.add_argument("--repo", required=True, help="path to the repository to document")
    prod.add_argument("--out", required=True, help="output directory for the generated wiki")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        if args.index_db:
            index = AtlasIndex(args.index_db)
        else:
            index = TokenIndex(args.index)
        issues = MockJira(args.dataset)
        rec = run_ticket(args.case, issues=issues, extractor=AndroidSignalExtractor(),
                         estate=MockEstate(args.catalog, args.work), index=index,
                         fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                         changes=MockGerrit(args.changes, issues))
        print(f"case={rec.ticket_id} matched={rec.chosen.name} change={rec.change.change_id}")
        return 0
    if args.cmd == "index":
        return _run_index(args)
    if args.cmd == "doctor":
        return _run_doctor(args)
    if args.cmd == "produce":
        return _run_produce(args)
    return 1
