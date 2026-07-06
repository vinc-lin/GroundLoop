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
    if args.skills != "none" and os.environ.get("KLOOP_EMBED_BASE_URL", "").strip():
        from groundloop.config.settings import Settings
        from groundloop.engines.atlas.embed import GatewayEmbedder
        st = Settings.load()
        embedder = GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model)
    skills = _load_skills(args.skills, args.skills_seed, embedder)
    runner = FixEvalRunner(issues=MockJira(args.dataset),
                           estate=GitFixtureEstate(args.repos, args.dataset + "/_work"),
                           catalog=catalog, tau_margin=args.tau_margin, tau_score=args.tau_score,
                           skills=skills)
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
    """Synthesize AAOS failure-log tickets from a mined dataset (wraps build_synth_dataset)."""
    import json
    import os
    from pathlib import Path
    from groundloop.config.settings import Settings
    from groundloop.synth.dataset import build_synth_dataset

    atlas_db = args.atlas_db or Settings.load().atlas_db
    if not atlas_db:
        print("gloop synth: --atlas-db is required (or set KLOOP_ATLAS_DB)")
        return 2

    # --catalog names a catalog.json path (default: the one alongside the mined dataset).
    catalog_path = args.catalog or os.path.join(args.src, "catalog.json")
    catalog_names = [c["name"] for c in json.loads(Path(catalog_path).read_text())]

    made = build_synth_dataset(args.src, atlas_db, args.out, catalog_names)

    # Tally the synth-log kind (native | logcat) per written case for a coverage summary.
    kinds: dict[str, int] = {}
    for cid in made:
        oracle = json.loads((Path(args.out) / cid / "_oracle" / "oracle.json").read_text())
        k = oracle.get("synth_log", "?")
        kinds[k] = kinds.get(k, 0) + 1

    print(f"synth: {len(made)} cases -> {args.out}")
    for k in sorted(kinds):
        print(f"  {k}: {kinds[k]}")
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


def _run_compare(args) -> int:
    import json
    from pathlib import Path
    from groundloop.fixeval.compare import accept, accept_grounded, compare, compare_metrics

    def _arms(path):
        return json.loads(Path(path).read_text()).get("arms", {})

    base_arms, head_arms = _arms(args.base), _arms(args.head)
    arm = args.arm if args.arm else (next(iter(base_arms)) if base_arms else None)
    base_arm, head_arm = base_arms.get(arm, {}), head_arms.get(arm, {})
    resolved = compare(base_arm.get("resolved_by_case", {}), head_arm.get("resolved_by_case", {}))
    metrics = compare_metrics(base_arm, head_arm)
    cost_budget = getattr(args, "cost_budget", None)
    verdict = accept(metrics, resolved, cost_budget=cost_budget)
    grounded = accept_grounded(metrics, resolved, cost_budget=cost_budget)
    result = {"arm": arm, "resolved": resolved, "metrics": metrics, "verdict": verdict,
              "grounded_verdict": grounded}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"compare[{arm}]: Δfile_recall@1={metrics['file_recall@1']['delta']} "
          f"Δfabrication={metrics['fabrication_rate']['delta']} "
          f"newly_solved={verdict['newly_solved']} newly_broken={verdict['newly_broken']} "
          f"-> {'ACCEPT' if verdict['accepted'] else 'REJECT'} {verdict['reasons']}")
    print(f"  grounded: Δplan_target_recall@1={metrics['plan_target_recall@1']['delta']} "
          f"Δresolved_strict={metrics['resolved_rate_strict']['delta']} "
          f"Δgroundedness={metrics['plan_groundedness']['delta']} "
          f"-> {'ACCEPT' if grounded['accepted'] else 'REJECT'} {grounded['reasons']}")
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


def build_parser() -> argparse.ArgumentParser:
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
    fx.add_argument("--skills", choices=["none", "mock", "kb", "placebo", "distilled"], default="none",
                    help="dev-experience KB arm: none | mock | kb (raw corpus) | placebo | "
                         "distilled (the kb-distill output, distilled.toml)")
    fx.add_argument("--skills-seed", dest="skills_seed", default=None,
                    help="override the KB/placebo corpus TOML path (default: the packaged seed)")
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

    cmp = sub.add_parser("compare", help="diff two fix-scorecards -> newly_solved/newly_broken")
    cmp.add_argument("--base", required=True, help="base fix-scorecard.json")
    cmp.add_argument("--head", required=True, help="head fix-scorecard.json")
    cmp.add_argument("--arm", default="", help="arm to compare (default: the first arm)")
    cmp.add_argument("--out", default="", help="write the full compare (metrics+verdict) JSON here")
    cmp.add_argument("--cost-budget", dest="cost_budget", type=float, default=None,
                     help="reject if Δcost_per_solved exceeds this (default: advisory only)")

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    if args.cmd == "synth":
        return _run_synth(args)
    if args.cmd == "kb-ab":
        return _run_kb_ab(args)
    if args.cmd == "kb-promote":
        return _run_kb_promote(args)
    if args.cmd == "kb-distill":
        return _run_kb_distill(args)
    if args.cmd == "compare":
        return _run_compare(args)
    return 1
