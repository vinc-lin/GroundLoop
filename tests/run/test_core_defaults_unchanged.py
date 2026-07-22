"""Governance lock on the `gloop run` defaults: match `component`, localize `cascade_judge`, fix `plan`.
`cascade_judge` was promoted to the core (production) localize default on an owner override 2026-07-21
(was `atlas_rerank`), on `[proxy]`/`[authored]` evidence — NOT a `[production]` read — under the
Provisional-Core "default it so the next production run tests it" bargain (the `[production]` GEI file@k read
is the resolver: confirm→Core, else revert to `--localize atlas_rerank`/`atlas`). This test locks the
current default so a *further* drift is caught (see capabilities.md §4). `--localize atlas_rerank`/`atlas`
remain the explicit reverts."""
from __future__ import annotations


def test_core_defaults_match_component_localize_cascade_judge_fix_plan(monkeypatch):
    monkeypatch.delenv("KLOOP_LABS", raising=False)
    from groundloop.cli import _resolve_arms, build_parser
    args = build_parser().parse_args(
        ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
         "--index-db", "a.db", "--out", "o", "--repos", "r"])
    assert _resolve_arms(args) == ("component", "cascade_judge", "core")   # core defaults, profile off
    assert args.fixer == "plan"                                     # Provisional-Core fix default (unchanged)


# Localize arms whose candidate-gen needs a real embedder and fail-fasts without one (see `--localize
# rerank` in `groundloop/cli/__init__.py`: `if emb is None: print(...); return 2`). The default must never be
# one of these — `cascade_judge` degrades gracefully (the bge-m3 semantic tier is simply omitted when no
# embedder is configured), so it can never fail-close a run for lack of an embedder.
_EMBEDDER_GATED_LOCALIZE_ARMS = {"rerank"}


def test_localize_default_is_cascade_judge_both_profiles(monkeypatch):
    """(a) `_resolve_arms` resolves localize to `cascade_judge` by default in BOTH profiles (the labs match
    default differs — `routing` — but localize is `cascade_judge` in each). (b) It is not an embedder-gated
    arm (`{"rerank"}`): it degrades gracefully with no embedder, so a default `gloop run` with no
    KLOOP_EMBED_BASE_URL is never rejected on account of localize."""
    from groundloop.cli import _resolve_arms, build_parser

    def parse(extra):
        return build_parser().parse_args(
            ["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
             "--index-db", "a.db", "--out", "o", "--repos", "r", *extra])

    monkeypatch.delenv("KLOOP_LABS", raising=False)
    match_core, localize_core, profile_core = _resolve_arms(parse([]))
    assert (match_core, localize_core, profile_core) == ("component", "cascade_judge", "core")

    match_labs, localize_labs, profile_labs = _resolve_arms(parse(["--profile", "labs"]))
    assert (match_labs, localize_labs, profile_labs) == ("routing", "cascade_judge", "labs")

    monkeypatch.setenv("KLOOP_LABS", "1")
    _, localize_env_labs, profile_env_labs = _resolve_arms(parse([]))
    assert (localize_env_labs, profile_env_labs) == ("cascade_judge", "labs")

    assert localize_core not in _EMBEDDER_GATED_LOCALIZE_ARMS   # cascade_judge degrades, never fail-closes
    assert localize_labs not in _EMBEDDER_GATED_LOCALIZE_ARMS

    # explicit --localize atlas_rerank / atlas still opt out (the reverts), in either profile
    assert _resolve_arms(parse(["--localize", "atlas"]))[1] == "atlas"
    assert _resolve_arms(parse(["--localize", "atlas_rerank"]))[1] == "atlas_rerank"
    assert _resolve_arms(parse(["--profile", "labs", "--localize", "atlas"]))[1] == "atlas"
