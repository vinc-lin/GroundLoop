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
    from groundloop.build.wiki_stub import ensure_indexable_wiki
    for e in entries:
        if ensure_indexable_wiki(e.wiki_dir):
            print(f"index: stubbed missing wiki for {e.name} (symbol-only)")

    atlas_db = settings.atlas_db or "atlas.db"
    store = Store(atlas_db)
    embedder = GatewayEmbedder(settings.embed_base_url, settings.embed_api_key,
                               settings.embed_model, batch=settings.embed_batch,
                               max_chars=settings.embed_max_chars)
    counts = asyncio.run(_index_mod.index_all(entries, store, embedder,
                                              call_timeout=settings.cbm_index_timeout))
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

    # --concurrency wins if given; otherwise fall back to KLOOP_PRODUCE_CONCURRENCY (default 1).
    concurrency = args.concurrency
    if concurrency is None:
        concurrency = int(os.environ.get("KLOOP_PRODUCE_CONCURRENCY", "1"))

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
        "concurrency": concurrency,
    }

    generator = CLIDocumentationGenerator(
        repo_path=repo_path,
        output_dir=output_dir,
        config=config,
        verbose=False,
    )
    generator.generate()
    return 0


def _run_mine(args) -> int:
    from groundloop.mine.gh_miner import mine
    from groundloop.engines.atlas.registry import load_registry
    from groundloop.config.settings import Settings
    reg = Settings.load().registry
    fleet = [e.name for e in load_registry(reg)] if reg else [args.repo_name]
    leak_index = None
    if getattr(args, "index_db", ""):
        from groundloop.adapters.index.atlas import AtlasIndex
        leak_index = AtlasIndex(args.index_db)
    if leak_index is None:
        print("gloop mine: WARNING — no --index-db; the closed-loop leak reject is OFF "
              "(deterministic scrub only — un-enumerated owner tokens may reach the matcher).")
    report = mine([args.slug], args.out, repo_name=args.repo_name, fleet_names=fleet,
                  limit=args.limit, max_files=args.max_files, holdout_frac=args.holdout_frac,
                  coverage_cutoff=args.coverage_cutoff, leak_index=leak_index,
                  not_a_defect_limit=args.not_a_defect_limit)
    print(f"mine {args.repo_name}: " + " ".join(f"{k}={v}" for k, v in report.items()))
    return 0


def _run_eval(args) -> int:
    import json
    from pathlib import Path
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.adapters.estate import MockEstate
    from groundloop.eval.dataset import load_cases, load_eval_oracle
    from groundloop.eval.arms import build_arms
    from groundloop.eval.runner import EvalRunner
    from groundloop.eval.scorecard import grade_all, per_case_rows
    from groundloop.eval.report import render_markdown

    cases = load_cases(args.dataset)
    runner = EvalRunner(issues=MockJira(args.dataset),
                        estate=MockEstate(args.catalog, args.dataset + "/_work"),
                        tau_margin=args.tau_margin, tau_score=args.tau_score)
    semantic_index = None
    if args.semantic:
        from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
        from groundloop.engines.atlas.embed import GatewayEmbedder
        from groundloop.config.settings import Settings
        st = Settings.load()
        emb = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
        semantic_index = SemanticAtlasIndex(args.index_db, emb)
    judge_index = None
    if args.judge:
        from groundloop.adapters.index.atlas_judge import LLMJudgeIndex, GatewayJudge
        from groundloop.config.settings import Settings as _S
        s = _S.load()
        gj = GatewayJudge(s.produce_base_url, s.produce_api_key, s.produce_main_model)
        judge_index = LLMJudgeIndex(AtlasIndex(args.index_db), gj)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db),
                                           semantic_index=semantic_index, judge_index=judge_index))
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}  # OFFLINE grade — oracle read here only
    card = grade_all(records, oracle_by_case=oracle_by_case)
    Path(args.out).write_text(json.dumps(card, indent=2))
    Path(args.out).with_suffix(".md").write_text(render_markdown(card))
    rows = per_case_rows(records, oracle_by_case=oracle_by_case)   # per-(case x arm) prediction dump
    pred_path = Path(args.out).with_name(Path(args.out).stem + ".predictions.jsonl")
    pred_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"predictions: {len(rows)} rows -> {pred_path.name}")
    for arm, a in card["arms"].items():
        oof = a["selective"]["abstention_recall_oof"]["value"]
        oof_s = "n/a" if oof is None else f"{oof:.2f}"
        print(f"{arm}: recall@1={a['forced']['recall@1']['value']:.2f} "
              f"coverage={a['selective']['coverage']:.2f} phi_1={a['selective']['phi_c']['1.0']:.2f} "
              f"oof_recall={oof_s}")
    return 0


def _run_fixeval(args) -> int:
    import json
    import os
    from pathlib import Path
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.adapters.estate import GitFixtureEstate
    from groundloop.adapters.fix.model_patch import ModelPatchEngine
    from groundloop.adapters.mock.model import CannedModel
    from groundloop.core.types import RepoRef
    from groundloop.eval.arms import build_arms
    from groundloop.eval.dataset import load_cases, load_eval_oracle
    from groundloop.fixeval.runner import FixEvalRunner
    from groundloop.fixeval.scorecard import grade_fix_all
    from groundloop.fixeval.report import render_fix_markdown

    catalog = [RepoRef(r["name"]) for r in json.loads(Path(args.catalog).read_text())]
    if os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
        from groundloop.adapters.model.gateway import GatewayModel
        from groundloop.config.settings import Settings
        s = Settings.load()
        model = GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
    else:
        print("gloop fixeval: no KLOOP_PRODUCE_API_KEY — hermetic canned model (all cases abstain at fix).")
        model = CannedModel({"default": ""})
    cases = load_cases(args.dataset)
    skills = None
    if args.skills == "mock":
        from groundloop.adapters.skills.mock import MockSkillRegistry
        embedder = None
        if os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
            from groundloop.engines.atlas.embed import GatewayEmbedder
            from groundloop.config.settings import Settings
            st = Settings.load()
            embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
        skills = MockSkillRegistry.load(embedder=embedder)
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)),
                         fixer=ModelPatchEngine(model))
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — oracle read here only
    card = grade_fix_all(records, oracle_by_case=oracle_by_case)
    Path(args.out).write_text(json.dumps(card, indent=2))
    Path(args.out).with_suffix(".md").write_text(render_fix_markdown(card))
    for arm, a in card["arms"].items():
        fr = a["file_recall@1"]["value"]
        fab = a["fabrication_rate"]["value"]
        print(f"{arm}: file_recall@1={'n/a' if fr is None else f'{fr:.2f}'} "
              f"apply_rate={a['patch_apply_rate']:.2f} "
              f"fabrication={'n/a' if fab is None else f'{fab:.2f}'} gradeable_n={a['n_gradeable']}")
    return 0


def _run_compare(args) -> int:
    import json
    from pathlib import Path
    from groundloop.fixeval.compare import compare, compare_metrics, accept

    def _arms(path):
        return json.loads(Path(path).read_text()).get("arms", {})

    base_arms, head_arms = _arms(args.base), _arms(args.head)
    arm = args.arm if args.arm else (next(iter(base_arms)) if base_arms else None)
    base_arm, head_arm = base_arms.get(arm, {}), head_arms.get(arm, {})
    resolved = compare(base_arm.get("resolved_by_case", {}), head_arm.get("resolved_by_case", {}))
    metrics = compare_metrics(base_arm, head_arm)
    verdict = accept(metrics, resolved, cost_budget=args.cost_budget)
    result = {"arm": arm, "resolved": resolved, "metrics": metrics, "verdict": verdict}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"compare[{arm}]: Δfile_recall@1={metrics['file_recall@1']['delta']} "
          f"Δfabrication={metrics['fabrication_rate']['delta']} "
          f"newly_solved={verdict['newly_solved']} newly_broken={verdict['newly_broken']} "
          f"-> {'ACCEPT' if verdict['accepted'] else 'REJECT'} {verdict['reasons']}")
    return 0


def _run_build_atlas(args) -> int:
    import os
    import tomllib
    from pathlib import Path
    from groundloop.config.settings import Settings
    from groundloop.build.atlas_build import build_atlas
    from groundloop.build.corpus import load_corpus

    settings = Settings.load()
    registry = args.registry or settings.registry
    if not registry:
        print("gloop build-atlas: --registry is required (or set KLOOP_REGISTRY)")
        return 2
    corpus_path = args.corpus or str(Path(registry).with_name("corpus.toml"))
    corpus = None
    if os.path.isfile(corpus_path):
        try:
            corpus = load_corpus(corpus_path)
        except tomllib.TOMLDecodeError as exc:
            print(f"gloop build-atlas: corpus.toml is malformed ({corpus_path}): {exc}")
            return 2
    report = build_atlas(registry, jobs=args.jobs, concurrency=args.concurrency,
                         force=args.force, corpus=corpus)
    for name, r in report.clone.items():
        print(f"clone {name}: {getattr(r, 'status', '?')}"
              + (f" ({getattr(r, 'detail', '')})" if getattr(r, "status", "") == "failed" else ""))
    for name, r in report.produce.items():
        print(f"produce {name}: {getattr(r, 'status', '?')}")
    print(f"index rc={report.index_rc}  doctor rc={report.doctor_rc}")
    if not report.ok:
        print(f"build-atlas FAILED at stage: {report.failed_stage}")
        return 1
    print("build-atlas OK")
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
    prod.add_argument("--concurrency", type=int, default=None,
                      help="modules generated in parallel within this repo "
                           "(default 1, or KLOOP_PRODUCE_CONCURRENCY)")

    ba = sub.add_parser("build-atlas", help="clone fleet + produce (parallel) + index + doctor")
    ba.add_argument("--registry", default="", help="path to atlas.toml (overrides KLOOP_REGISTRY)")
    ba.add_argument("--jobs", type=int, default=3, help="repos produced in parallel (default 3)")
    ba.add_argument("--concurrency", type=int, default=4,
                    help="modules per repo in parallel (default 4); total in-flight ~= jobs*concurrency")
    ba.add_argument("--force", action="store_true", help="re-produce even if a wiki exists")
    ba.add_argument("--corpus", default="",
                    help="path to corpus.toml (repo url+sha for cloning); "
                         "defaults to a corpus.toml sibling of the registry")

    mn = sub.add_parser("mine", help="harvest issue->fix cases for a fleet repo (online, gh)")
    mn.add_argument("--slug", required=True, help="owner/name GitHub slug, e.g. TeamNewPipe/NewPipe")
    mn.add_argument("--repo-name", required=True, help="short fleet/catalog name, e.g. newpipe")
    mn.add_argument("--out", required=True, help="dataset output dir")
    mn.add_argument("--limit", type=int, default=200)
    mn.add_argument("--max-files", type=int, default=5)
    mn.add_argument("--index-db", default="",
                    help="atlas.db for the closed-loop leak reject (recommended for real mining)")
    mn.add_argument("--holdout-frac", type=float, default=0.0,
                    help="fraction of admitted positives to convert to out_of_fleet hold-out negatives")
    mn.add_argument("--coverage-cutoff", default="",
                    help="ISO date; admitted cases merged AFTER this become coverage_gap negatives "
                         "(temporal proxy for un-indexed fix)")
    mn.add_argument("--not-a-defect-limit", type=int, default=0,
                    help="cap on label-harvested not_a_defect negatives per repo (0=off)")

    ev = sub.add_parser("eval", help="run the Type-2 eval over a mined dataset -> scorecard")
    ev.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    ev.add_argument("--catalog", required=True, help="path to catalog.json")
    ev.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    ev.add_argument("--out", required=True, help="scorecard.json output path (a .md twin is written too)")
    ev.add_argument("--tau-margin", type=float, default=1.0)
    ev.add_argument("--tau-score", type=float, default=1.0)
    ev.add_argument("--semantic", action="store_true",
                    help="add the bge-m3 semantic arms (needs KLOOP_EMBED_* live gateway)")
    ev.add_argument("--judge", action="store_true",
                    help="add the LLM-judge arms (reranks membership top-k via KLOOP_PRODUCE_* model)")

    fx = sub.add_parser("fixeval", help="run the downstream fix/RCA loop over a dataset -> fix-scorecard")
    fx.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    fx.add_argument("--catalog", required=True, help="path to catalog.json")
    fx.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    fx.add_argument("--repos", required=True, help="fixtures/repos root for @base materialization")
    fx.add_argument("--out", required=True, help="fix-scorecard.json output path (a .md twin is written too)")
    fx.add_argument("--tau-margin", type=float, default=1.0)
    fx.add_argument("--tau-score", type=float, default=1.0)
    fx.add_argument("--skills", choices=["none", "mock"], default="none",
                    help="dev-experience KB arm: none (baseline) | mock (real-data seed)")

    cmp = sub.add_parser("compare", help="diff two fix-scorecards -> newly_solved/newly_broken")
    cmp.add_argument("--base", required=True, help="base fix-scorecard.json")
    cmp.add_argument("--head", required=True, help="head fix-scorecard.json")
    cmp.add_argument("--arm", default="", help="arm to compare (default: the first arm)")
    cmp.add_argument("--out", default="", help="write the full compare (metrics+verdict) JSON here")
    cmp.add_argument("--cost-budget", dest="cost_budget", type=float, default=None,
                     help="reject if Δcost_per_solved exceeds this (default: advisory only)")

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
    if args.cmd == "build-atlas":
        return _run_build_atlas(args)
    if args.cmd == "mine":
        return _run_mine(args)
    if args.cmd == "eval":
        return _run_eval(args)
    if args.cmd == "fixeval":
        return _run_fixeval(args)
    if args.cmd == "compare":
        return _run_compare(args)
    return 1
