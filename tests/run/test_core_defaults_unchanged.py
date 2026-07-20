"""Governance lock: with the labs profile OFF (KLOOP_LABS unset, no --profile), the `gloop run` defaults
MUST stay Core-aligned — match `component`, localize `atlas_rerank` (the Provisional-Core default since
2026-07-19: the plain FTS5 `atlas` pool reordered by the LLM file-judge, fail-safe — with no judge creds it
degrades to the byte-identical FTS5 `atlas` order and needs no embedder, so the flip never regresses or
fail-closes), fix `plan`. The labs arms are opt-in Candidates; none may become a silent production default.
If this test fails, a default drifted (see capabilities.md §4)."""
from __future__ import annotations


def test_core_defaults_unchanged_without_labs(monkeypatch):
    monkeypatch.delenv("KLOOP_LABS", raising=False)
    from groundloop.cli import _resolve_arms, build_parser
    args = build_parser().parse_args(
        ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
         "--index-db", "a.db", "--out", "o", "--repos", "r"])
    assert _resolve_arms(args) == ("component", "atlas_rerank", "core")   # Core-aligned defaults, profile off
    assert args.fixer == "plan"                                     # Provisional-Core fix default (unchanged)


# Localize arms whose candidate-gen needs a real embedder and fail-fasts without one (see `--localize
# rerank` in `groundloop/cli/__init__.py`: `if emb is None: print(...); return 2`). The atlas_rerank
# default must never be one of these — its candidate pool is the plain FTS5 AtlasIndex.retrieve (built
# with embedder=None unconditionally), so it can never fail-close a run for lack of an embedder.
_EMBEDDER_GATED_LOCALIZE_ARMS = {"rerank"}


def test_localize_default_core_atlas_rerank_labs_cascade_judge(monkeypatch):
    """(a) `_resolve_arms` resolves localize per PROFILE: the core (production) default is `atlas_rerank`,
    the labs default is `cascade_judge` (the peak Candidate stack, opt-in via --profile labs / KLOOP_LABS=1
    — never the silent production default). (b) NEITHER default is an embedder-gated arm (`{"rerank"}`):
    both degrade gracefully with no embedder (cascade_judge omits only its bge-m3 semantic tier), so a
    default `gloop run` with no KLOOP_EMBED_BASE_URL is never rejected on account of localize, in either
    profile."""
    from groundloop.cli import _resolve_arms, build_parser

    def parse(extra):
        return build_parser().parse_args(
            ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
             "--index-db", "a.db", "--out", "o", "--repos", "r", *extra])

    monkeypatch.delenv("KLOOP_LABS", raising=False)
    match_core, localize_core, profile_core = _resolve_arms(parse([]))
    assert (match_core, localize_core, profile_core) == ("component", "atlas_rerank", "core")

    match_labs, localize_labs, profile_labs = _resolve_arms(parse(["--profile", "labs"]))
    assert (match_labs, localize_labs, profile_labs) == ("routing", "cascade_judge", "labs")

    monkeypatch.setenv("KLOOP_LABS", "1")
    _, localize_env_labs, profile_env_labs = _resolve_arms(parse([]))
    assert (localize_env_labs, profile_env_labs) == ("cascade_judge", "labs")

    assert localize_core not in _EMBEDDER_GATED_LOCALIZE_ARMS
    assert localize_labs not in _EMBEDDER_GATED_LOCALIZE_ARMS   # cascade_judge degrades, never fail-closes

    # explicit --localize atlas still opts out to the plain FTS5 floor, in either profile
    assert _resolve_arms(parse(["--localize", "atlas"]))[1] == "atlas"
    assert _resolve_arms(parse(["--profile", "labs", "--localize", "atlas"]))[1] == "atlas"
