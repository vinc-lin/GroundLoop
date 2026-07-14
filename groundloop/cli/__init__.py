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


def _run_mine_affinity(args) -> int:
    from groundloop.domains.android_ivi.mine_component_affinity import write_affinity
    n = write_affinity(args.dataset, args.out)
    print(f"mine-affinity: {n} (component,owner) pairs -> {args.out}")
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


def _load_skills(kind: str, seed: str | None, embedder):
    """Compose the fixeval KB arm. kind: none|mock|kb|placebo.
    none -> None (baseline, no KB injected). mock -> the SP3 4-playbook seed.
    kb -> OUR 12-skill corpus (groundloop/kb/data/aaos_kb_seed.toml) or the --skills-seed override.
    placebo -> the length-matched irrelevant control (groundloop/kb/data/placebo.toml) or the override.
    All three real arms share the MockSkillRegistry wiring (predicate select + gated bge-m3 rerank)."""
    if kind == "none":
        return None
    from pathlib import Path

    from groundloop.adapters.skills.mock import SEED_PATH, MockSkillRegistry
    from groundloop.kb.validate import SEED_PATH as KB_SEED

    if kind == "mock":
        path = seed or SEED_PATH
    elif kind == "kb":
        path = seed or KB_SEED
    elif kind == "placebo":
        path = seed or str(Path(KB_SEED).parent / "placebo.toml")
    elif kind == "distilled":
        path = seed or str(Path(KB_SEED).parent / "distilled.toml")   # produced by `gloop kb-distill`
    else:
        raise ValueError(f"unknown --skills kind: {kind!r}")
    return MockSkillRegistry.load(path, embedder=embedder)


def _load_claims(kind: str, embedder, store_path: str | None = None):
    """Compose the fixeval claim arm. kind: none|candidate|validated.
    none -> (None, "validated"); candidate -> (registry, "candidate") [EVAL floor];
    validated -> (registry, "validated") [PRODUCTION floor]. The registry loads the claim store at
    `store_path` (an external/working claims.json, e.g. the Phase D ext4 store); `store_path=None`
    resolves to the packaged CLAIMS_PATH -> byte-identical to today. The tier floor gates candidates out
    of prod."""
    if kind == "none":
        return None, "validated"
    from groundloop.kb.claim import CLAIMS_PATH
    from groundloop.kb.registry import ClaimRegistry
    return ClaimRegistry.load(path=store_path or CLAIMS_PATH, embedder=embedder), kind


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
    embedder = None
    want_embed = args.skills != "none" or args.claims != "none"
    if want_embed and os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
    skills = _load_skills(args.skills, args.skills_seed, embedder)
    claims, claims_tier_floor = _load_claims(args.claims, embedder, store_path=args.claims_store)
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills, claims=claims, claims_tier_floor=claims_tier_floor,
                           skill_inject=args.skills_inject)
    if getattr(args, "fixer", "direct") == "plan":
        from groundloop.adapters.fix.planning import PlanningFixEngine
        fixer = PlanningFixEngine(model, max_replan=args.max_replan)
    else:
        fixer = ModelPatchEngine(model)
    records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)), fixer=fixer)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — oracle read here only
    card = grade_fix_all(records, oracle_by_case=oracle_by_case)
    Path(args.out).write_text(json.dumps(card, indent=2))
    Path(args.out).with_suffix(".md").write_text(render_fix_markdown(card))
    from groundloop.fixeval.archive import archive_plans
    n_plans = archive_plans(records, str(Path(args.out).parent))
    if n_plans:
        print(f"archived {n_plans} plan(s) -> {Path(args.out).parent}/plans/")
    for arm, a in card["arms"].items():
        fr = a["file_recall@1"]["value"]
        fab = a["fabrication_rate"]["value"]
        pg = a.get("plan_groundedness", {}).get("value")
        rs = a.get("resolved_rate_strict", {}).get("value")
        extra = ""
        if pg is not None:
            ptr = a.get("plan_target_recall@1", {}).get("value")
            extra = (f" plan_grounded={pg:.2f} plan_recall@1={'n/a' if ptr is None else f'{ptr:.2f}'}"
                     f" resolved_strict={'n/a' if rs is None else f'{rs:.2f}'}")
        print(f"{arm}: file_recall@1={'n/a' if fr is None else f'{fr:.2f}'} "
              f"apply_rate={a['patch_apply_rate']:.2f} "
              f"fabrication={'n/a' if fab is None else f'{fab:.2f}'} gradeable_n={a['n_gradeable']}{extra}")
    return 0


def _run_synth(args) -> int:
    """Synthesize failure-log tickets from a mined dataset. --mode failurelog (default, the SP2 short synth)
    or faultlog (v2 long unscrubbed logcat + fault-locus oracle)."""
    import json
    import os
    from pathlib import Path
    from groundloop.config.settings import Settings

    atlas_db = args.atlas_db or Settings.load().atlas_db
    if not atlas_db:
        print("gloop synth: --atlas-db is required (or set KLOOP_ATLAS_DB)")
        return 2
    catalog_path = args.catalog or os.path.join(args.src, "catalog.json")
    catalog_names = [c["name"] for c in json.loads(Path(catalog_path).read_text())]

    if getattr(args, "mode", "failurelog") == "faultlog":
        from groundloop.synth.faultlog import build_faultlog_dataset
        made = build_faultlog_dataset(args.src, atlas_db, args.out, catalog_names,
                                      difficulty=args.difficulty, noise_lines=args.noise_lines)
        fams: dict[str, int] = {}
        for cid in made:
            o = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
            fams[o.get("fault_family", "?")] = fams.get(o.get("fault_family", "?"), 0) + 1
        print(f"faultlog synth ({args.difficulty}): {len(made)} cases -> {args.out}")
        for k in sorted(fams):
            print(f"  {k}: {fams[k]}")
        return 0

    if getattr(args, "mode", "failurelog") == "functional":
        from groundloop.synth.functional import build_functional_dataset
        made = build_functional_dataset(args.src, atlas_db, args.out, catalog_names)
        kinds: dict[str, int] = {}
        for cid in made:
            o = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
            k = o.get("functional_class", "?")
            kinds[k] = kinds.get(k, 0) + 1
        print(f"functional synth: {len(made)} cases -> {args.out}")
        for k in sorted(kinds):
            print(f"  {k}: {kinds[k]}")
        return 0

    from groundloop.synth.dataset import build_synth_dataset
    made = build_synth_dataset(args.src, atlas_db, args.out, catalog_names)
    kinds: dict[str, int] = {}
    for cid in made:
        oracle = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
        k = oracle.get("synth_log", "?")
        kinds[k] = kinds.get(k, 0) + 1
    print(f"synth: {len(made)} cases -> {args.out}")
    for k in sorted(kinds):
        print(f"  {k}: {kinds[k]}")
    return 0


def _run_label_bugkind(args) -> int:
    from groundloop.eval.label_bug_kind import stamp_bug_kind
    n = stamp_bug_kind(args.dataset)
    print(f"label-bugkind: stamped {n} cases -> {args.dataset}")
    return 0


def _run_combine_oracle(args) -> int:
    from groundloop.eval.combine_oracle import combine_oracles
    r = combine_oracles(args.sources, args.out, label=not args.no_label)
    print(f"combine-oracle: {r['cases']} cases from {len(r['per_source'])} sources -> {args.out} "
          f"({r['repos']} repos, {r['labeled']} bug_kind-labeled)")
    for src, n in r["per_source"].items():
        print(f"  {n:5} <- {src}")
    return 0


def _run_faulteval(args) -> int:
    import json
    from pathlib import Path
    from groundloop.faulteval.runner import run_faulteval
    card = run_faulteval(args.dataset, args.index_db, arms=tuple(args.arms.split(",")))
    Path(args.out).write_text(json.dumps(card, indent=2))
    loc = card["localization"]
    print(f"localization: frame@1={loc['frame@1']['value']:.2f} "
          f"frame@5={loc['frame@5']['value']:.2f} file@1={loc['file@1']['value']:.2f} "
          f"no_fault={loc['no_fault_found']}/{loc['n']}")
    for arm, a in card["attribution"]["arms"].items():
        print(f"  {arm}: attribution_recall@1={a['forced']['recall@1']['value']:.2f} "
              f"recall@3={a['forced']['recall@3']['value']:.2f} coverage={a['selective']['coverage']:.2f}")
    return 0


def _run_funceval(args) -> int:
    import json
    import os
    from pathlib import Path
    from groundloop.funceval.runner import run_funceval
    if os.environ.get("KLOOP_TEXTPROFILE_STUB") == "1":
        from groundloop.engines.atlas.embed import StubEmbedder
        emb = StubEmbedder()
    else:
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        emb = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
    arms = tuple(args.arms.split(","))
    if "component" in arms and not args.affinity:
        print("gloop funceval: the 'component' arm requires --affinity")
        return 2
    card = run_funceval(args.dataset, args.profile_db, args.index_db, embedder=emb,
                        arms=arms, affinity_path=(args.affinity or None), loo=args.loo)
    Path(args.out).write_text(json.dumps(card, indent=2))
    for arm, a in card["attribution"]["arms"].items():
        line = (f"{arm}: recall@1={a['forced']['recall@1']['value']:.2f} "
                f"coverage={a['selective']['coverage']:.2f}")
        for bk, sub in a.get("by_bug_kind", {}).items():
            line += f" | {bk} recall@1={sub['forced']['recall@1']['value']:.2f}"
        print(line)
    return 0


def _run_kb_ab(args) -> int:
    """A/B the dev-experience KB {none, kb, placebo} then a strengthened two-sided accept verdict.

    Builds an env-driven embedder EXACTLY like _run_fixeval (GatewayEmbedder when KLOOP_EMBED_BASE_URL is
    set, else None) — this closes the run_ab(embedder=None) gap so bge-m3 rerank engages live. run_ab writes
    scorecard-{none,kb,placebo}.json; we then read the chosen eval arm off each card and emit two verdicts:
    kb_vs_placebo (primary — isolates guidance content) and kb_vs_none. Oracle-blind loop; grade is offline."""
    import json
    import os
    from pathlib import Path
    from groundloop.kb.ab import run_ab
    from groundloop.kb.accept import strengthened_accept

    embedder = None
    if os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)

    cards = run_ab(dataset=args.dataset, repos=args.repos, index_db=args.index_db,
                   catalog_path=args.catalog, out_dir=args.out,
                   arms=("none", "kb", "placebo"), embedder=embedder)

    eval_arm = args.eval_arm
    base = cards["none"]["arms"][eval_arm]
    head = cards["kb"]["arms"][eval_arm]
    placebo = cards["placebo"]["arms"][eval_arm]
    kb_vs_placebo = strengthened_accept(placebo, head, cost_budget=args.cost_budget)
    kb_vs_none = strengthened_accept(base, head, cost_budget=args.cost_budget)

    verdict = {"eval_arm": eval_arm, "kb_vs_placebo": kb_vs_placebo, "kb_vs_none": kb_vs_none}
    (Path(args.out) / "verdict.json").write_text(json.dumps(verdict, indent=2))

    decision = "ACCEPT" if kb_vs_placebo["accepted"] else "REJECT"
    print(f"kb-ab[{eval_arm}]: kb_vs_placebo -> {decision} {kb_vs_placebo['reasons']}")
    return 0


def _run_kb_promote(args) -> int:
    """Fold a kb-ab verdict into the KB provenance sidecar: walk each skill's trust-tier ladder.

    Seeds any of the 12 corpus skills (validate.load_corpus(KB_SEED)) absent from the sidecar as fresh
    `candidate`s, reads passed = verdict["kb_vs_placebo"]["accepted"] (the primary two-sided verdict),
    then applies it to every KB skill via lifecycle.apply_verdict (hysteresis=2, so a lone failing A/B
    cannot demote a playbook). Idempotent: re-running with the same verdict just re-walks the ladder.
    Prints one tier transition per skill."""
    import json
    from pathlib import Path
    from groundloop.kb.lifecycle import apply_verdict
    from groundloop.kb.provenance import (
        SIDECAR_PATH,
        ProvenanceRecord,
        load_sidecar,
        save_sidecar,
    )
    from groundloop.kb.validate import SEED_PATH as KB_SEED
    from groundloop.kb.validate import load_corpus

    verdict = json.loads(Path(args.verdict).read_text())
    passed = bool(verdict["kb_vs_placebo"]["accepted"])

    prov_path = args.provenance or SIDECAR_PATH
    records = load_sidecar(prov_path)
    skill_ids = [s["id"] for s in load_corpus(KB_SEED)]
    for sid in skill_ids:
        records.setdefault(sid, ProvenanceRecord(
            id=sid, tier="candidate", lineage="authored cold-start",
            validating_case_ids=(), measured_lift={}, evidence_context={}))

    transitions = []
    for sid in skill_ids:
        before = records[sid].tier
        records[sid] = apply_verdict(records[sid], passed, hysteresis=2)
        transitions.append((sid, before, records[sid].tier))
    save_sidecar(prov_path, records)

    verb = "PASS" if passed else "FAIL"
    print(f"kb-promote[{verb}]: {len(skill_ids)} skills -> {prov_path}")
    for sid, before, after in transitions:
        note = f"{before}->{after}" if before != after else f"{after} (hold)"
        print(f"  {sid}: {note}")
    return 0


# Split firewall (mirrors groundloop.kb.harvest.cluster._MINING_SPLITS): only calib/train cases may
# author a distilled playbook that is later scored — eval/holdout cases must never launder into the KB.
_ALL_SPLITS = ("calib", "train", "eval", "holdout")
_MINING_SPLITS = frozenset({"calib", "train"})


def _case_split(case_id: str) -> str:
    """Deterministic per-case split from the opaque loop-visible case id (oracle-blind). ~1/2 mining."""
    import hashlib
    h = int(hashlib.sha1(case_id.encode("utf-8")).hexdigest(), 16)
    return _ALL_SPLITS[h % len(_ALL_SPLITS)]


def _signals_dict(signals) -> dict:
    """Frozen Signals -> the {family: [tokens]} dict cluster_by_signature keys on."""
    return {"errors": list(signals.errors), "libraries": list(signals.libraries),
            "symbols": list(signals.symbols), "classes": list(signals.classes),
            "methods": list(signals.methods), "packages": list(signals.packages)}


def _dump_corpus(skills: list[dict]) -> str:
    """Serialize skill dicts to a `[[skill]]` corpus TOML (round-trips through kb.validate.load_corpus;
    no tomli_w in the venv). Guidance rides a multiline literal ('''...''') so it needs no escaping."""
    def b(v: object) -> str:                     # TOML basic string
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def arr(xs) -> str:
        return "[" + ", ".join(b(x) for x in xs) + "]"

    chunks: list[str] = []
    for sk in skills:
        lines = [
            "[[skill]]",
            f"id = {b(sk['id'])}",
            f"provenance = {b(sk['provenance'])}",
            f"signals = {arr(sk.get('signals', []))}",
            f"hint_apis = {arr(sk.get('hint_apis', []))}",
            "guidance = '''\n" + sk["guidance"] + "\n'''",
            "",
            "[skill.match]",
        ]
        for key, val in (sk.get("match") or {}).items():
            lines.append(f"{key} = {arr(val)}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n"


def _build_distill_run_fn(args, candidate: dict):
    """Return the C2/C3 lift probe `run_fn(guidance) -> float` for ONE candidate: a run_ab-style A/B that
    re-runs the whole fix-loop with THIS candidate's match + the passed guidance injected as the sole KB
    skill, and reports the eval-arm resolved_rate lift over the skills=none baseline. Built per candidate
    so the closure carries the candidate's predicate (lofo/revalidate only ever hand it a guidance str).
    Hermetic tests monkeypatch this symbol to a scripted stub (no atlas / no model)."""
    import json
    import os
    import tempfile
    from pathlib import Path

    from groundloop.adapters.estate import GitFixtureEstate
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.adapters.skills.mock import MockSkillRegistry
    from groundloop.core.types import RepoRef
    from groundloop.eval.arms import build_arms
    from groundloop.eval.dataset import load_cases, load_eval_oracle
    from groundloop.fixeval.runner import FixEvalRunner
    from groundloop.fixeval.scorecard import grade_fix_all
    from groundloop.kb.ab import _make_fixer

    catalog_path = os.path.join(args.dataset, "catalog.json")
    catalog = [RepoRef(r["name"]) for r in json.loads(Path(catalog_path).read_text())]
    cases = load_cases(args.dataset)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — sole oracle read
    eval_arm = getattr(args, "eval_arm", None) or "membership+logs"

    embedder = None
    if os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)

    def _resolved_rate(skills, work_suffix: str) -> float:
        estate = GitFixtureEstate(args.repos, args.dataset + f"/_work-distill-{work_suffix}")
        runner = FixEvalRunner(issues=MockJira(args.dataset), estate=estate, catalog=catalog,
                               tau_margin=0.0, tau_score=0.0, skills=skills)
        records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)),
                             fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        return (card["arms"][eval_arm]["resolved_rate"]["value"] or 0.0)

    baseline_rate = _resolved_rate(None, "none")

    def run_fn(guidance: str) -> float:
        probe = dict(candidate)
        probe["guidance"] = guidance
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(_dump_corpus([probe]))
            probe_path = fh.name
        try:
            skills = MockSkillRegistry.load(probe_path, embedder=embedder)
            return _resolved_rate(skills, "kb") - baseline_rate
        finally:
            os.unlink(probe_path)

    return run_fn


def _run_kb_distill(args) -> int:
    """GATED Phase B/C driver: harvest -> distill -> lofo -> revalidate, then promote. Dormant unless the
    kb-ab Phase-A verdict ACCEPTED the KB over placebo. Split-firewalled to calib/train ONLY; oracle-blind
    (distill_guidance refuses any trace carrying owning_repo/expected_files). Only a re-validated distilled
    form re-enters the corpus (distilled.toml beside the sidecar) + earns an apply_verdict tier bump."""
    import json
    from pathlib import Path

    from groundloop.adapters.mock.jira import MockJira
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
    from groundloop.eval.dataset import load_cases
    from groundloop.kb.distill.extract import distill_guidance
    from groundloop.kb.distill.lofo import lofo_fragments
    from groundloop.kb.distill.revalidate import revalidate
    from groundloop.kb.harvest.cluster import candidate_from_cluster, cluster_by_signature
    from groundloop.kb.lifecycle import apply_verdict
    from groundloop.kb.provenance import (
        SIDECAR_PATH,
        ProvenanceRecord,
        load_sidecar,
        save_sidecar,
    )

    verdict = json.loads(Path(args.verdict).read_text())
    if not verdict.get("kb_vs_placebo", {}).get("accepted"):
        print("kb-distill: Phase-A not passed — skip (kb_vs_placebo not accepted)")
        return 0

    prov_path = args.provenance or SIDECAR_PATH
    distilled_path = Path(prov_path).with_name("distilled.toml")

    # Build split-firewalled, loop-visible per-case signals (calib/train ONLY — the mining feedstock).
    issues = MockJira(args.dataset)
    extractor = AndroidSignalExtractor()
    signals_by_case: dict[str, dict] = {}
    summary_by_case: dict[str, str] = {}
    mining_cases: list[dict] = []
    for case in load_cases(args.dataset):
        if _case_split(case.case_id) not in _MINING_SPLITS:
            continue
        ticket = issues.fetch(case.case_id)                     # loop-visible only
        sig = _signals_dict(extractor.extract(ticket.logs, ticket))
        signals_by_case[case.case_id] = sig
        summary_by_case[case.case_id] = ticket.summary
        mining_cases.append({"case_id": case.case_id, "signals": sig})

    clusters = cluster_by_signature(mining_cases)

    records = load_sidecar(prov_path)
    promoted: list[dict] = []
    for signature, case_ids in clusters.items():
        candidate = candidate_from_cluster(signature, case_ids, split_tag="train")
        if candidate is None:                                   # firewall / empty / leaky signature
            continue
        run_fn = _build_distill_run_fn(args, candidate)
        baseline_lift = run_fn(candidate["guidance"])           # form-A lift
        if baseline_lift <= 0:                                  # the candidate guidance did not help
            continue
        # loop-visible traces for the cluster (NO oracle keys -> distill_guidance stays oracle-blind)
        traces = [{"ticket_summary": summary_by_case[cid], "signals": signals_by_case[cid],
                   "injected_guidance": candidate["guidance"], "patch_diff": "", "helped": True}
                  for cid in case_ids]
        distilled = distill_guidance(traces)                    # C1: verbatim extract + leak-scrub
        if not distilled.strip():
            continue
        load_bearing = lofo_fragments(distilled, run_fn)        # C2: prune inert fragments
        distilled_final = "\n".join(load_bearing)
        if not distilled_final.strip():
            continue
        if not revalidate(distilled_final, baseline_lift, run_fn, margin=args.margin):   # C3 gate
            continue
        skill = dict(candidate)
        skill["guidance"] = distilled_final
        skill["provenance"] = (f"distilled+revalidated (harvest->distill->lofo->revalidate) from "
                               f"{candidate['provenance']}")
        promoted.append(skill)
        records.setdefault(skill["id"], ProvenanceRecord(
            id=skill["id"], tier="candidate",
            lineage="distilled (harvest->distill->revalidate)",
            validating_case_ids=tuple(sorted(case_ids)),
            measured_lift={"baseline_lift": baseline_lift}, evidence_context={}))
        records[skill["id"]] = apply_verdict(records[skill["id"]], True, hysteresis=2)

    if not promoted:
        print("kb-distill: 0 distilled skills promoted (none cleared lofo + re-validation)")
        return 0

    distilled_path.write_text(_dump_corpus(promoted))
    save_sidecar(prov_path, records)
    print(f"kb-distill: promoted {len(promoted)} distilled skill(s) -> {distilled_path}")
    for sk in promoted:
        print(f"  {sk['id']}: {records[sk['id']].tier}")
    return 0


def _extract_model():
    """The LLM proposer for kb-extract: live GatewayModel when KLOOP_PRODUCE_API_KEY is set, else a no-op
    CannedModel (hermetic tests monkeypatch this seam to a scripted CannedModel). Mirrors _run_fixeval's
    model gate. Implementer-verify (confirmed in _run_fixeval): GatewayModel(base_url, api_key, model)."""
    import os
    if os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
        from groundloop.adapters.model.gateway import GatewayModel
        from groundloop.config.settings import Settings
        s = Settings.load()
        return GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
    print("gloop kb-extract: no KLOOP_PRODUCE_API_KEY — hermetic canned model (proposes 0 claims).")
    return CannedModel({"default": ""})


def _extract_resolver(index_db: str):
    """The fleet-wide atlas existence probe for the ground-check (hermetic tests monkeypatch this seam).
    Fails fast on an empty atlas: a wrong/typo'd --index-db makes Store() create an EMPTY schema, which
    would silently reject every ref ('N rejected', exit 0) — misleading. Detect 0 indexed units and error."""
    from groundloop.engines.atlas.store import Store
    from groundloop.kb.claim_ground import atlas_resolver
    store = Store(index_db)
    if sum(st.unit_count for st in store.list_repo_states()) == 0:
        raise SystemExit(f"gloop kb-extract: atlas {index_db!r} has 0 indexed units — wrong --index-db?")
    return atlas_resolver(store)


def _run_kb_extract(args) -> int:
    """Decompose each feedstock Skill's prose into candidate Claims (LLM PROPOSES), ground-check every
    candidate against the atlas (existence) + the leak red-test (oracle-blind), and MERGE survivors into the
    claim store at tier=candidate. The LLM is a proposer only; grounding admits."""
    from groundloop.kb.claim import CLAIMS_PATH, load_claims, save_claims
    from groundloop.kb.extract import extract_to_store
    from groundloop.kb.validate import SEED_PATH as KB_SEED
    from groundloop.kb.validate import load_corpus

    seed = args.skills_seed or KB_SEED
    out = args.out or CLAIMS_PATH
    skills = load_corpus(seed)
    existing = load_claims(out)
    store, rejected = extract_to_store(skills, _extract_model(), _extract_resolver(args.index_db),
                                       existing=existing)
    save_claims(out, store)
    admitted = len(store) - len(existing)
    print(f"kb-extract: {len(skills)} skill(s) -> {admitted} new candidate claim(s), "
          f"{len(rejected)} rejected -> {out}")
    for claim, chk in rejected:
        print(f"  drop {claim.id}: {', '.join(chk.reasons)}")
    return 0


def _build_attribute_run_card_fn(args, claims):
    """Return `run_card_fn(claim_id_set) -> eval-arm scorecard dict`: re-runs the plan-format fix eval with
    EXACTLY the passed claim ids (candidates AND their per-claim placebos) injected via a ClaimRegistry at
    the candidate (EVAL) floor, and returns the eval arm of grade_fix_all (the offline grade = sole oracle
    read). Mirrors _build_distill_run_fn. Hermetic tests monkeypatch THIS symbol to a scripted stub."""
    import itertools
    import json
    import os
    from pathlib import Path

    from groundloop.adapters.estate import GitFixtureEstate
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.core.types import RepoRef
    from groundloop.eval.arms import build_arms
    from groundloop.eval.dataset import load_cases, load_eval_oracle
    from groundloop.fixeval.runner import FixEvalRunner
    from groundloop.fixeval.scorecard import grade_fix_all
    from groundloop.kb.ab import _make_fixer
    from groundloop.kb.claim_placebo import build_claim_placebo
    from groundloop.kb.registry import ClaimRegistry

    catalog_path = args.catalog or os.path.join(args.dataset, "catalog.json")
    catalog = [RepoRef(r["name"]) for r in json.loads(Path(catalog_path).read_text())]
    cases = load_cases(args.dataset)
    oracle_by_case = {c.case_id: load_eval_oracle(c) for c in cases}   # OFFLINE grade — sole oracle read
    eval_arm = getattr(args, "eval_arm", None) or "membership+logs"

    embedder = None
    if os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)

    pool = dict(claims)
    pool.update(build_claim_placebo(claims))         # candidates + one placebo each, keyed by id
    _work_seq = itertools.count()                    # unique work-dir per call (mirrors _build_distill_run_fn)

    def run_card_fn(claim_ids):
        selected = [pool[i] for i in claim_ids if i in pool]
        registry = ClaimRegistry(selected, embedder=embedder)
        estate = GitFixtureEstate(args.repos, args.dataset + f"/_work-attr-{next(_work_seq)}")
        runner = FixEvalRunner(issues=MockJira(args.dataset), estate=estate, catalog=catalog,
                               tau_margin=0.0, tau_score=0.0,
                               claims=registry, claims_tier_floor="candidate")
        records = runner.run(cases, build_arms(membership_index=AtlasIndex(args.index_db)),
                             fixer=_make_fixer())
        card = grade_fix_all(records, oracle_by_case=oracle_by_case)
        arms = card.get("arms", {})
        if eval_arm not in arms:
            raise KeyError(f"kb-attribute: eval arm {eval_arm!r} not in scorecard arms {sorted(arms)}")
        return arms[eval_arm]

    return run_card_fn


def _run_kb_attribute(args) -> int:
    """Staged per-claim attribution + governance (spec §5.4/§5.5). GATED on a plan archive: no plans/ ->
    exit 0 (nothing to attribute). screen (archive, oracle-blind) -> shortlist (capped by --max-lofo) ->
    LOFO-confirm vs per-claim placebo -> accept_grounded -> apply_verdict per claim; writes tier + evidence
    back to claims.json. Oracle-blind loop; grade_fix_all inside the run-card seam is the sole oracle read."""
    from collections import Counter

    from groundloop.kb.attribute import attribute_and_govern, load_archive, screen_claims
    from groundloop.kb.claim import CLAIMS_PATH, load_claims, save_claims

    payloads = load_archive(args.archive)
    if not payloads:
        print(f"kb-attribute: no plan archive at {args.archive} — nothing to attribute "
              f"(run `gloop fixeval --claims candidate` first)")
        return 0

    store_path = args.claims_store or CLAIMS_PATH
    claims = load_claims(store_path)
    shortlist = screen_claims(payloads, claims, threshold=args.screen_threshold)
    if args.max_lofo and len(shortlist) > args.max_lofo:
        shortlist = shortlist[: args.max_lofo]
    if not shortlist:
        print(f"kb-attribute: screened {len(payloads)} plan(s) -> 0 shortlisted "
              f"(no claim cleared |screen_lift| >= {args.screen_threshold})")
        return 0

    run_card_fn = _build_attribute_run_card_fn(args, claims)
    updated = attribute_and_govern(claims, shortlist, run_card_fn, cost_budget=args.cost_budget)
    save_claims(store_path, updated)

    print(f"kb-attribute: screened {len(payloads)} plan(s) -> shortlist {len(shortlist)} -> {store_path}")
    print("  tiers:", dict(Counter(c.tier for c in updated.values())))
    for cid in shortlist:
        c = updated[cid]
        print(f"  {cid}: {c.tier}  (lofo_delta={c.evidence.get('measured_lift', {}).get('lofo_delta')})")
    return 0


def _run_compare(args) -> int:
    import json
    from pathlib import Path
    from groundloop.fixeval.compare import accept, accept_grounded, compare, compare_metrics

    def _arms(path):
        return json.loads(Path(path).read_text()).get("arms", {})

    base_arms, head_arms = _arms(args.base), _arms(args.head)
    # Default: compare EVERY arm present in both scorecards, so the signal-bearing arm is never silently
    # dropped. (The old default — the first-inserted arm — is often `membership+text`, which carries no plan
    # metrics for log-based cases, giving a misleading Δ=None verdict.) `--arm` still selects a single arm.
    if args.arm:
        arms = [args.arm]
    else:
        arms = [a for a in base_arms if a in head_arms] or ([next(iter(base_arms))] if base_arms else [])
    cost_budget = getattr(args, "cost_budget", None)
    out: dict = {}
    for arm in arms:
        base_arm, head_arm = base_arms.get(arm, {}), head_arms.get(arm, {})
        resolved = compare(base_arm.get("resolved_by_case", {}), head_arm.get("resolved_by_case", {}))
        metrics = compare_metrics(base_arm, head_arm)
        verdict = accept(metrics, resolved, cost_budget=cost_budget)
        grounded = accept_grounded(metrics, resolved, cost_budget=cost_budget)
        out[arm] = {"resolved": resolved, "metrics": metrics, "verdict": verdict,
                    "grounded_verdict": grounded}
        print(f"compare[{arm}]: Δfile_recall@1={metrics['file_recall@1']['delta']} "
              f"Δfabrication={metrics['fabrication_rate']['delta']} "
              f"newly_solved={verdict['newly_solved']} newly_broken={verdict['newly_broken']} "
              f"-> {'ACCEPT' if verdict['accepted'] else 'REJECT'} {verdict['reasons']}")
        print(f"  grounded: Δplan_target_recall@1={metrics['plan_target_recall@1']['delta']} "
              f"Δresolved_strict={metrics['resolved_rate_strict']['delta']} "
              f"Δgroundedness={metrics['plan_groundedness']['delta']} "
              f"-> {'ACCEPT' if grounded['accepted'] else 'REJECT'} {grounded['reasons']}")
    if args.out:
        Path(args.out).write_text(json.dumps({"arms": out}, indent=2))
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


def _run_build_textprofile(args) -> int:
    import json
    import os
    from pathlib import Path
    from groundloop.adapters.index.text_profile import build_text_profiles, gather_repo_texts
    names = [c["name"] for c in json.loads(Path(args.catalog).read_text())]
    profiles = {n: gather_repo_texts(os.path.join(args.corpus, n))
                for n in names if os.path.isdir(os.path.join(args.corpus, n))}
    if os.environ.get("KLOOP_TEXTPROFILE_STUB") == "1":
        from groundloop.engines.atlas.embed import StubEmbedder
        emb = StubEmbedder()
    else:
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        emb = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model,
                              batch=32, timeout=180.0, retries=6)
    build_text_profiles(profiles, args.out, emb)
    print(f"profiles: {len(profiles)} repos -> {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gloop")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    for flag in ("--dataset", "--catalog", "--work", "--changes"):
        r.add_argument(flag, required=True)
    r.add_argument("--case", default=None,
                   help="single-case mode; omit and pass --out for batch over --dataset")
    r.add_argument("--out", default=None,
                   help="batch mode: write oracle-free run-records to <out>/runs/<case>.json")
    r.add_argument("--repos", default="",
                   help="batch: owner-repo snapshots dir (CheckoutEstate). REQUIRED with --fixer model; "
                        "empty -> MockEstate (empty worktrees, hermetic only)")
    r.add_argument("--fixer", choices=["canned", "model", "plan"], default="plan",
                   help="batch fix engine: plan (grounded plan→gate→abstain PlanningFixEngine — the "
                        "production default; abstains rather than fabricate) | model (single-shot "
                        "ModelPatchEngine opt-out) | canned (dev-only hermetic stub)")
    r.add_argument("--max-replan", type=int, default=1,
                   help="plan fixer: max re-plan attempts before abstaining (default 1)")
    # --index and --index-db are mutually exclusive; at least one must be provided
    idx_group = r.add_mutually_exclusive_group(required=True)
    idx_group.add_argument("--index", default=None,
                           help="path to token-index JSON (M0 stub)")
    idx_group.add_argument("--index-db", default=None,
                           help="path to atlas.db (real AtlasIndex)")
    r.add_argument("--profile", choices=["core", "labs"], default="core",
                   help="core (default) | labs (experimental defaults: routing match + semantic localize; "
                        "also KLOOP_LABS=1). Explicit --match-arm/--localize always override the profile.")
    r.add_argument("--match-arm",
                   choices=["flood", "routing", "component", "semantic", "judge", "functional", "dispatch"],
                   default=None,
                   help="Stage-1 match index (default resolved by --profile: component in core, routing in "
                        "labs): component (affinity prior via --affinity/KLOOP_AFFINITY, RRF-fused onto "
                        "AtlasIndex; falls back to flood if no affinity artifact) | flood (AtlasIndex "
                        "baseline) | routing (FaultRoutingIndex) | semantic (bge-m3 vector, needs "
                        "KLOOP_EMBED_BASE_URL) | judge (LLM rerank, needs creds) | functional "
                        "(FunctionalTextIndex, needs embedder + repo-text profile) | dispatch "
                        "(FaultRouting+FunctionalText, needs embedder + profile)")
    r.add_argument("--affinity", default="",
                   help="component_affinity.json for --match-arm component (else KLOOP_AFFINITY)")
    r.add_argument("--functional-profile", default="",
                   help="repo-text profile db (gloop build-textprofile) for --match-arm functional/dispatch; "
                        "else KLOOP_FUNCTIONAL_PROFILE")
    r.add_argument("--localize", choices=["atlas", "semantic", "dispatch"], default=None,
                   help="localize retriever, chosen independently of --match-arm (default resolved by "
                        "--profile: atlas in core, semantic in labs): atlas (FTS5) | semantic (bge-m3 vector, "
                        "needs KLOOP_EMBED_BASE_URL) | dispatch (per-ticket: prose-only/no-anchor -> bge-m3 "
                        "vector, crash/anchored -> FTS5; needs KLOOP_EMBED_BASE_URL). When it differs from the "
                        "match arm's native retrieve, the index is wrapped (SplitIndex / LocalizeDispatchIndex). "
                        "A labs-DEFAULTED semantic/dispatch localize degrades to atlas (warn) without an "
                        "embedder; explicit --localize semantic/dispatch fails closed.")
    r.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)

    grun = sub.add_parser("grade-run", help="offline per-stage scorecard over a gloop run --out dir")
    grun.add_argument("--runs", required=True, help="the <out> dir written by gloop run --out")
    grun.add_argument("--dataset", required=True, help="the dataset the run was over (for the hidden oracle)")
    grun.add_argument("--index-db", default=None, help="atlas.db — enables the isolated-localize diagnostic")
    grun.add_argument("--out", required=True, help="scorecard JSON path (a .md table is written alongside)")
    grun.add_argument("--compare", default=None,
                      help="a previous grade-run card.json — append a per-stage regression section")

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

    bp = sub.add_parser("build-textprofile", help="build the lightweight bge-m3 repo-text profile db")
    bp.add_argument("--corpus", required=True, help="dir with one subdir per repo (README/manifest/ids)")
    bp.add_argument("--catalog", required=True, help="catalog.json listing repo names to profile")
    bp.add_argument("--out", required=True, help="destination profile atlas.db path")

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

    ma = sub.add_parser("mine-affinity", help="offline: build component->repo affinity json from a dataset")
    ma.add_argument("--dataset", required=True, help="dataset root (ticket.json component + _oracle owner)")
    ma.add_argument("--out", required=True, help="component_affinity.json output path")

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

    lb = sub.add_parser("label-bugkind", help="offline: stamp bug_kind (crash|functional) into oracle.json")
    lb.add_argument("--dataset", required=True, help="dataset root (case dirs with _oracle/oracle.json)")

    co = sub.add_parser("combine-oracle", help="assemble a combined crash+functional oracle from datasets")
    co.add_argument("--sources", nargs="+", required=True, help="source dataset roots to merge")
    co.add_argument("--out", required=True, help="destination combined dataset root (must be fresh)")
    co.add_argument("--no-label", action="store_true", help="skip stamping bug_kind (crash|functional)")

    fx = sub.add_parser("fixeval", help="run the downstream fix/RCA loop over a dataset -> fix-scorecard")
    fx.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    fx.add_argument("--catalog", required=True, help="path to catalog.json")
    fx.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    fx.add_argument("--repos", required=True, help="fixtures/repos root for @base materialization")
    fx.add_argument("--out", required=True, help="fix-scorecard.json output path (a .md twin is written too)")
    fx.add_argument("--tau-margin", type=float, default=1.0)
    fx.add_argument("--tau-score", type=float, default=1.0)
    fx.add_argument("--skills", choices=["none", "mock", "kb", "placebo", "distilled"], default="none",
                    help="dev-experience KB arm: none | mock | kb (raw corpus) | placebo | "
                         "distilled (the kb-distill output, distilled.toml)")
    fx.add_argument("--skills-seed", dest="skills_seed", default=None,
                    help="override the KB/placebo corpus TOML path (default: the packaged seed)")
    fx.add_argument("--skills-inject", dest="skills_inject", choices=["both", "fix-only"], default="both",
                    help="how a skill arm injects: both (localize query + fix prompt) | fix-only "
                         "(fix/plan prompt only — isolates KB fix-content value from retrieval)")
    fx.add_argument("--claims", choices=["none", "candidate", "validated"], default="none",
                    help="claim-KB arm (claims.json): none | candidate (EVAL floor — includes "
                         "unvalidated candidates) | validated (PRODUCTION floor — validated+canonical only)")
    fx.add_argument("--claims-store", dest="claims_store", default=None,
                    help="claim store JSON to read (default: groundloop/kb/data/claims.json)")
    fx.add_argument("--fixer", choices=["direct", "plan"], default="direct",
                    help="fix engine: direct (single-shot ModelPatchEngine) | "
                         "plan (two-phase PlanningFixEngine: plan->gate->re-plan->abstain->patch)")
    fx.add_argument("--max-replan", dest="max_replan", type=int, default=1,
                    help="plan fixer: bounded re-plan attempts before abstaining (default 1)")

    sy = sub.add_parser("synth", help="synthesize AAOS failure-log tickets from a mined dataset")
    sy.add_argument("--src", required=True, help="mined dataset root (case dirs + catalog.json)")
    sy.add_argument("--atlas-db", default="",
                    help="path to atlas.db for crash-site symbols (overrides KLOOP_ATLAS_DB)")
    sy.add_argument("--out", required=True, help="destination synth dataset root")
    sy.add_argument("--catalog", default="",
                    help="path to catalog.json (default: <src>/catalog.json)")
    sy.add_argument("--mode", choices=["failurelog", "faultlog", "functional"], default="failurelog",
                    help="failurelog | faultlog | functional (no-crash prose + optional log)")
    sy.add_argument("--difficulty", choices=["clean", "hard"], default="clean",
                    help="faultlog only: clean (owner tokens only in fault block) | hard (with decoys)")
    sy.add_argument("--noise-lines", dest="noise_lines", type=int, default=3000,
                    help="faultlog only: framework-noise line count (default 3000)")

    fe = sub.add_parser("faulteval", help="fault-localization + attribution eval over a faultlog dataset")
    fe.add_argument("--dataset", required=True, help="faultlog dataset root (case dirs + catalog.json)")
    fe.add_argument("--index-db", required=True, help="path to atlas.db")
    fe.add_argument("--out", required=True, help="scorecard.json output path")
    fe.add_argument("--arms", default="flood,faultslice,routing",
                    help="comma list of arms: flood,faultslice,routing (routing needs Phase 2)")

    fn = sub.add_parser("funceval", help="functional-bug matching eval (text-primary + optional logs)")
    fn.add_argument("--dataset", required=True, help="labeled dataset root (bug_kind in oracle.json)")
    fn.add_argument("--profile-db", required=True, help="repo-text profile db (gloop build-textprofile)")
    fn.add_argument("--index-db", required=True, help="atlas.db for the optional log-FTS channel + ablations")
    fn.add_argument("--arms", default="functional,dispatch,flood,faultslice,routing",
                    help="comma list of arms")
    fn.add_argument("--out", required=True, help="scorecard.json output path")
    fn.add_argument("--affinity", default="", help="component_affinity.json for the 'component' arm")
    fn.add_argument("--loo", action="store_true", help="leave-one-out affinity (no train/test leak)")

    kab = sub.add_parser("kb-ab",
                         help="A/B the dev-experience KB {none,kb,placebo} -> scorecards + accept verdict")
    kab.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    kab.add_argument("--catalog", required=True, help="path to catalog.json")
    kab.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    kab.add_argument("--repos", required=True, help="fixtures/repos root for @base materialization")
    kab.add_argument("--out", required=True, help="output dir for scorecard-{none,kb,placebo}.json + verdict.json")
    kab.add_argument("--eval-arm", dest="eval_arm", default="membership+logs",
                     help="which eval arm to read for the verdict (default: membership+logs)")
    kab.add_argument("--cost-budget", dest="cost_budget", type=float, default=None,
                     help="reject if Δcost_per_solved exceeds this (default: advisory only)")

    kpr = sub.add_parser("kb-promote",
                         help="fold a kb-ab verdict into the KB provenance sidecar (tier transitions)")
    kpr.add_argument("--verdict", required=True, help="path to a kb-ab verdict.json")
    kpr.add_argument("--provenance", default=None,
                     help="provenance sidecar path (default: groundloop/kb/data/provenance.json)")

    kds = sub.add_parser("kb-distill",
                         help="GATED harvest->distill->revalidate driver (dormant unless kb-ab accepted)")
    kds.add_argument("--verdict", required=True, help="path to a kb-ab verdict.json (the Phase-A gate)")
    kds.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    kds.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    kds.add_argument("--repos", required=True, help="fixtures/repos root for @base materialization")
    kds.add_argument("--provenance", default=None,
                     help="provenance sidecar path (default: groundloop/kb/data/provenance.json); "
                          "the distilled corpus is written as distilled.toml beside it")
    kds.add_argument("--margin", type=float, default=0.0,
                     help="re-validation slack: distilled form must clear form-A lift within this "
                          "(0.0 = demand the full baseline lift)")

    kex = sub.add_parser("kb-extract",
                         help="decompose feedstock Skills -> candidate Claims (LLM propose + ground-check)")
    kex.add_argument("--skills-seed", dest="skills_seed", default=None,
                     help="feedstock corpus TOML (default: groundloop/kb/data/aaos_kb_seed.toml)")
    kex.add_argument("--index-db", required=True, help="atlas.db for the grounding existence check")
    kex.add_argument("--out", default=None,
                     help="claim store JSON to merge into (default: groundloop/kb/data/claims.json)")

    kat = sub.add_parser("kb-attribute",
                         help="staged per-claim attribution: archive screen -> LOFO confirm vs placebo -> "
                              "promote/retire (per-claim governance of claims.json)")
    kat.add_argument("--archive", required=True,
                     help="plan archive dir (<out>/plans from `gloop fixeval --claims candidate`)")
    kat.add_argument("--dataset", required=True, help="dataset root (case dirs + catalog.json)")
    kat.add_argument("--catalog", default="", help="catalog.json (default: <dataset>/catalog.json)")
    kat.add_argument("--index-db", required=True, help="path to atlas.db (membership AtlasIndex)")
    kat.add_argument("--repos", required=True, help="fixtures/repos root for @base materialization")
    kat.add_argument("--claims-store", dest="claims_store", default=None,
                     help="claim store JSON to govern (default: groundloop/kb/data/claims.json)")
    kat.add_argument("--screen-threshold", dest="screen_threshold", type=float, default=0.0,
                     help="|screen_lift| shortlist threshold (default 0.0 = shortlist any claim with contrast)")
    kat.add_argument("--max-lofo", dest="max_lofo", type=int, default=20,
                     help="cap the LOFO-confirm shortlist (bounds the real fix-loop spend)")
    kat.add_argument("--cost-budget", dest="cost_budget", type=float, default=None,
                     help="reject a claim if Δcost_per_solved exceeds this (default: advisory only)")

    cmp = sub.add_parser("compare", help="diff two fix-scorecards -> newly_solved/newly_broken")
    cmp.add_argument("--base", required=True, help="base fix-scorecard.json")
    cmp.add_argument("--head", required=True, help="head fix-scorecard.json")
    cmp.add_argument("--arm", default="", help="arm to compare (default: every arm in both scorecards)")
    cmp.add_argument("--out", default="", help="write the full compare (metrics+verdict) JSON here")
    cmp.add_argument("--cost-budget", dest="cost_budget", type=float, default=None,
                     help="reject if Δcost_per_solved exceeds this (default: advisory only)")

    return ap


def _repos_has_snapshots(repos: str, catalog_path: str) -> bool:
    """True iff the --repos dir exists and holds a snapshot subdir for at least one catalog repo. Guards
    against a wrong-but-nonempty --repos yielding empty worktrees (which a real fixer fabricates over)."""
    import json
    from pathlib import Path
    if not repos:
        return False
    root = Path(repos)
    if not root.is_dir():
        return False
    try:
        cat = json.loads(Path(catalog_path).read_text())
    except Exception:
        return False
    # catalog.json is a JSON list of {"name": ...} objects (tests/fixtures/android_ivi/catalog.json);
    # tolerate a {"repos": [...]} wrapper too.
    entries = cat if isinstance(cat, list) else cat.get("repos", [])
    names = {e["name"] for e in entries if isinstance(e, dict) and "name" in e}
    subdirs = {p.name for p in root.iterdir() if p.is_dir()}
    return bool(names & subdirs)


def _env_flag(name: str) -> bool:
    """True iff env var `name` is set to an affirmative value. Treats '', '0', 'false', 'no', 'off'
    (case-insensitive) as False, so `KLOOP_X=0` disables rather than silently enabling the switch."""
    import os
    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no", "off")


def _resolve_arms(args):
    """Resolve requested (match_arm, localize) from flags + the labs profile. Explicit flags win; the labs
    profile only fills a left-at-default (None) flag. Returns (match_arm, localize, profile)."""
    labs = args.profile == "labs" or _env_flag("KLOOP_LABS")
    match_arm = args.match_arm if args.match_arm is not None else ("routing" if labs else "component")
    localize = args.localize if args.localize is not None else ("semantic" if labs else "atlas")
    return match_arm, localize, ("labs" if labs else "core")


def _build_embedder():
    """GatewayEmbedder when KLOOP_EMBED_BASE_URL is set, else None (mirrors _run_kb_ab / _run_fixeval).
    Used by the semantic / functional / dispatch match arms and the semantic localize retriever."""
    import os
    if not os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        return None
    from groundloop.config.settings import Settings
    from groundloop.engines.atlas.embed import GatewayEmbedder
    st = Settings.load()
    return GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)


def _build_run_fixer(kind: str, max_replan: int = 1):
    """Returns (FixEngine, cost_model|None). cost_model is the GatewayModel whose .cost_usd the batch
    driver snapshots per case; None for the canned stub. `main` fail-closes on a missing key BEFORE this
    for kind in {model, plan}, so no silent degrade-to-stub here."""
    from groundloop.adapters.fix.canned import CannedFixEngine
    from groundloop.adapters.mock.model import CannedModel
    if kind in ("model", "plan"):
        from groundloop.adapters.model.gateway import GatewayModel
        from groundloop.config.settings import Settings
        s = Settings.load()
        gm = GatewayModel(s.produce_base_url, s.produce_api_key, s.produce_main_model)
        if kind == "plan":
            from groundloop.adapters.fix.planning import PlanningFixEngine
            return PlanningFixEngine(gm, max_replan=max_replan), gm
        from groundloop.adapters.fix.model_patch import ModelPatchEngine
        return ModelPatchEngine(gm), gm
    return CannedFixEngine(CannedModel({"default": "patch"})), None


def _run_grade_run(args) -> int:
    import json
    from pathlib import Path
    from groundloop.run.grade_run import grade_run
    from groundloop.run.report import render_run_markdown
    card = grade_run(args.runs, args.dataset, index_db=args.index_db or None)
    Path(args.out).write_text(json.dumps(card, indent=2, ensure_ascii=False, default=str))
    Path(args.out).with_suffix(".md").write_text(render_run_markdown(card))
    ov = card["overall"]
    fx = ov["fix"] or {}
    iso = ov["localize"].get("isolated") or {}
    print(f"grade-run: {card['n_cases']} cases · match recall@1={ov['match']['recall@1']:.2f} · "
          f"localize as-run@1={ov['localize']['as_run'].get('file@1')} "
          f"isolated@1={iso.get('file@1')} · "
          f"fix gradeable={fx.get('n_gradeable')} ungradeable={fx.get('n_ungradeable_no_source')}")
    if args.compare:
        from groundloop.run.compare import compare_cards
        prev = json.loads(Path(args.compare).read_text())
        comp = compare_cards(card, prev)
        Path(args.out).with_suffix(".compare.json").write_text(
            json.dumps(comp, indent=2, ensure_ascii=False, default=str))
        regs = comp["regressions"]
        line = f"compare vs {args.compare}: verdict={comp['verdict']} · regressions={len(regs)}"
        if regs:
            line += f" ({', '.join(regs)})"
        print(line)
    from groundloop.run.promotion import promotion_notes
    for _note in promotion_notes(card):
        print(_note)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "run":
        import os
        extractor = AndroidSignalExtractor()
        # Dev gate: --index (M0 TokenIndex stub → forces flood), --fixer canned (emits a literal "patch"),
        # and --case (single-case demo that ignores --fixer/--repos) each SILENTLY degrade a production run.
        # Reject them unless the operator explicitly opts into dev mode (KLOOP_DEV=1 / hidden --dev). Placed
        # before any index construction so a gated run exits before doing work.
        dev = bool(args.dev) or _env_flag("KLOOP_DEV")
        if args.index and not dev:
            print("gloop run --index is dev-only (M0 TokenIndex; production uses --index-db). "
                  "Set KLOOP_DEV=1 for hermetic runs.")
            return 2
        if args.fixer == "canned" and not dev:
            print("gloop run --fixer canned is a dev-only hermetic stub. "
                  "Set KLOOP_DEV=1 (or use --fixer plan/model).")
            return 2
        if args.case and not dev:
            print("gloop run --case is a dev-only single-case demo (ignores --fixer/--repos); "
                  "production uses batch --out. Set KLOOP_DEV=1.")
            return 2
        # Resolve the requested arms from flags + the labs profile (--profile labs / KLOOP_LABS=1 flips the
        # defaults to routing match + semantic localize); explicit --match-arm/--localize always win.
        arm_req, localize_req, profile = _resolve_arms(args)
        localize_explicit = args.localize is not None
        match_arm = arm_req            # the arm that ACTUALLY runs (honest run-record); "flood" on any fallback
        affinity_path = ""             # set only on the component path; kept in scope for the manifest
        if args.index_db:
            index = AtlasIndex(args.index_db)
            if arm_req == "routing":
                from groundloop.adapters.index.fault_routing import FaultRoutingIndex
                from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor
                index, extractor = FaultRoutingIndex(args.index_db), FaultSignalExtractor()
            elif arm_req == "component":
                affinity_path = args.affinity or os.environ.get("KLOOP_AFFINITY", "").strip()
                if affinity_path:
                    from groundloop.adapters.index.component_prior import ComponentPriorIndex
                    from groundloop.domains.android_ivi.component_affinity import ComponentAffinity
                    from groundloop.domains.android_ivi.component_signals import ComponentExtractor
                    index = ComponentPriorIndex(AtlasIndex(args.index_db),
                                                ComponentAffinity.load(affinity_path))
                    extractor = ComponentExtractor(AndroidSignalExtractor())
                else:
                    # No affinity artifact: the prior is the production-validated lever, but degrading to the
                    # honest (weaker) flood baseline beats hard-failing. Warn loudly — never degrade silently —
                    # and record the arm as "flood" so the run-record does not claim the prior engaged.
                    match_arm = "flood"
                    print("gloop run --match-arm component: no affinity artifact (--affinity / KLOOP_AFFINITY) "
                          "— falling back to the flood baseline (recall@1 ~0.10 [production] vs ~0.50 with the "
                          "prior). Mine one with `gloop mine-affinity` to engage the validated lever.")
            elif arm_req == "semantic":
                emb = _build_embedder()
                if emb is None:
                    print("gloop run --match-arm semantic: no embedder — set KLOOP_EMBED_BASE_URL "
                          "(bge-m3 gateway). This arm needs the vector index.")
                    return 2
                from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                index = SemanticAtlasIndex(args.index_db, emb)
            elif arm_req == "judge":
                if not os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
                    print("gloop run --match-arm judge: no judge creds — set KLOOP_PRODUCE_API_KEY.")
                    return 2
                from groundloop.adapters.index.atlas_judge import GatewayJudge, LLMJudgeIndex
                from groundloop.config.settings import Settings as _S
                s = _S.load()
                index = LLMJudgeIndex(AtlasIndex(args.index_db), GatewayJudge(
                    s.produce_base_url, s.produce_api_key, s.produce_main_model))
            elif arm_req in ("functional", "dispatch"):
                emb = _build_embedder()
                profile_db = args.functional_profile or os.environ.get("KLOOP_FUNCTIONAL_PROFILE", "").strip()
                if emb is None or not profile_db:
                    print("gloop run --match-arm functional/dispatch: needs an embedder "
                          "(KLOOP_EMBED_BASE_URL) AND a repo-text profile "
                          "(--functional-profile / KLOOP_FUNCTIONAL_PROFILE, built by `gloop build-textprofile`).")
                    return 2
                from groundloop.adapters.index.functional_text import DispatchIndex, FunctionalTextIndex
                from groundloop.domains.android_ivi.functional_signals import (
                    DispatchExtractor, FunctionalTextExtractor)
                ftext = FunctionalTextIndex(profile_db, emb, atlas_db=args.index_db)
                if arm_req == "functional":
                    index, extractor = ftext, FunctionalTextExtractor()
                else:
                    from groundloop.adapters.index.fault_routing import FaultRoutingIndex
                    from groundloop.funceval.arms import _FAULT_SCALE   # tuned fault/functional scale (SSOT)
                    index = DispatchIndex(FaultRoutingIndex(args.index_db), ftext, fault_scale=_FAULT_SCALE)
                    extractor = DispatchExtractor()
            # localize retriever, independent of the match arm (semantic-match already retrieves via vectors)
            if localize_req == "semantic" and arm_req != "semantic":
                emb = _build_embedder()
                if emb is None:
                    if localize_explicit:
                        print("gloop run --localize semantic: no embedder — set KLOOP_EMBED_BASE_URL.")
                        return 2
                    # labs-DEFAULTED semantic localize: degrade to atlas FTS5 (warn) rather than fail closed;
                    # record the localize that ACTUALLY ran (atlas) in the manifest below.
                    print("gloop run (labs): --localize semantic wanted but no embedder — falling back to "
                          "atlas FTS5 localize. Set KLOOP_EMBED_BASE_URL to engage semantic localize.")
                    localize_req = "atlas"
                else:
                    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                    from groundloop.adapters.index.split import SplitIndex
                    index = SplitIndex(index, SemanticAtlasIndex(args.index_db, emb))
            elif localize_req == "atlas" and arm_req == "semantic":
                from groundloop.adapters.index.split import SplitIndex
                index = SplitIndex(index, AtlasIndex(args.index_db))
            elif localize_req == "dispatch":
                emb = _build_embedder()
                if emb is None:
                    if localize_explicit:
                        print("gloop run --localize dispatch: no embedder — set KLOOP_EMBED_BASE_URL "
                              "(bge-m3 gateway). The functional branch needs the vector index.")
                        return 2
                    # labs-DEFAULTED dispatch localize: degrade to atlas FTS5 (warn), record honestly.
                    print("gloop run (labs): --localize dispatch wanted but no embedder — falling back "
                          "to atlas FTS5 localize. Set KLOOP_EMBED_BASE_URL to engage dispatch localize.")
                    localize_req = "atlas"
                else:
                    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
                    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
                    index = LocalizeDispatchIndex(index, AtlasIndex(args.index_db),
                                                  SemanticAtlasIndex(args.index_db, emb))
        else:
            index, match_arm = TokenIndex(args.index), "flood"   # M0 stub is baseline membership, not component
        issues = MockJira(args.dataset)
        if args.case:  # single-case: hermetic demo path (canned fixer + MockEstate); production uses batch --out
            rec = run_ticket(args.case, issues=issues, extractor=extractor,
                             estate=MockEstate(args.catalog, args.work), index=index,
                             fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                             changes=MockGerrit(args.changes, issues))
            print(f"case={rec.ticket_id} matched={rec.chosen.name} change={rec.change.change_id}")
            return 0
        if args.out:                                              # batch -> self-scoring run-records
            from groundloop.adapters.estate import CheckoutEstate, RecordingEstate
            from groundloop.adapters.extractor_recording import RecordingExtractor
            from groundloop.run.batch import run_dataset
            # Record the signals the loop computes so the run-record can carry them (batch path only; the
            # single-case demo above stays unwrapped). Wraps the FINAL extractor (post component/routing swap).
            extractor = RecordingExtractor(extractor)
            # Fail-closed on the production path (--fixer model): a real fixer with no model or no checked-out
            # sources silently fabricates (the 2026-07-11 fix 0/10 lesson). Only the explicit hermetic
            # `--fixer canned` may run over empty MockEstate worktrees.
            if args.fixer in ("model", "plan"):
                if not os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip():
                    print("gloop run --fixer model/plan: KLOOP_PRODUCE_API_KEY unset — refusing to run a "
                          "real fixer with no model (it would fabricate patches). Configure gateway creds, "
                          "or pass --fixer canned for a hermetic run.")
                    return 2
                if not _repos_has_snapshots(args.repos, args.catalog):
                    print("gloop run --fixer model/plan: --repos has no snapshots for the catalog repos — a "
                          "real fixer over empty worktrees fabricates file paths. Point --repos at an "
                          "owner-snapshots dir (a subdir per catalog repo).")
                    return 2
            inner = (CheckoutEstate(args.catalog, args.repos, args.work) if args.repos
                     else MockEstate(args.catalog, args.work))
            fixer, cost_model = _build_run_fixer(args.fixer, args.max_replan)
            n = run_dataset(args.dataset, issues=issues, extractor=extractor,
                            estate=RecordingEstate(inner), index=index,
                            fixer=fixer,
                            changes=MockGerrit(args.changes, issues),
                            match_arm=match_arm, out=args.out,
                            extractor_rec=extractor, cost_model=cost_model, fixer_kind=args.fixer)
            from groundloop.run.manifest import write_manifest
            from groundloop.config.settings import Settings as _S
            _s = _S.load()
            write_manifest(args.out, atlas_db=args.index_db, match_arm=match_arm, fixer=args.fixer,
                           affinity=affinity_path, produce_model=_s.produce_main_model,
                           embed_model=getattr(_s, "embed_model", "bge-m3"), n_cases=n,
                           profile=profile, localize=localize_req)
            print(f"runs written: {n} -> {args.out}/runs (+ manifest.json)")
            return 0
        print("gloop run: pass --case <id> (single) or --out <dir> (batch over --dataset)")
        return 2
    if args.cmd == "grade-run":
        return _run_grade_run(args)
    if args.cmd == "index":
        return _run_index(args)
    if args.cmd == "doctor":
        return _run_doctor(args)
    if args.cmd == "produce":
        return _run_produce(args)
    if args.cmd == "build-atlas":
        return _run_build_atlas(args)
    if args.cmd == "build-textprofile":
        return _run_build_textprofile(args)
    if args.cmd == "mine":
        return _run_mine(args)
    if args.cmd == "mine-affinity":
        return _run_mine_affinity(args)
    if args.cmd == "eval":
        return _run_eval(args)
    if args.cmd == "label-bugkind":
        return _run_label_bugkind(args)
    if args.cmd == "combine-oracle":
        return _run_combine_oracle(args)
    if args.cmd == "fixeval":
        return _run_fixeval(args)
    if args.cmd == "synth":
        return _run_synth(args)
    if args.cmd == "faulteval":
        return _run_faulteval(args)
    if args.cmd == "funceval":
        return _run_funceval(args)
    if args.cmd == "kb-ab":
        return _run_kb_ab(args)
    if args.cmd == "kb-promote":
        return _run_kb_promote(args)
    if args.cmd == "kb-distill":
        return _run_kb_distill(args)
    if args.cmd == "kb-extract":
        return _run_kb_extract(args)
    if args.cmd == "kb-attribute":
        return _run_kb_attribute(args)
    if args.cmd == "compare":
        return _run_compare(args)
    return 1
