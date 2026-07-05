"""Compile a Skill's declarative `match` spec (from the seed TOML) into a pure predicate closure.
Closed vocabulary only (unknown key -> ValueError); regexes compiled eagerly (bad pattern -> ValueError
at load). No eval/exec, no serialized code: the seed stays reviewable data. A block's clauses are OR'd
(the skill applies if ANY fires); an empty spec never fires; `all_text` is the AND escape hatch."""
from __future__ import annotations

import re
from typing import Callable

from groundloop.skills.ctx import SkillCtx

_FAMILIES = ("packages", "classes", "methods", "symbols", "libraries", "errors")
_LIT_KEYS = ("any_text", "all_text") + tuple(f"any_{f}" for f in _FAMILIES)
_RE_KEYS = ("any_text_regex",) + tuple(f"any_{f}_regex" for f in _FAMILIES)
_VALID = {"always", "repo_in"} | set(_LIT_KEYS) | set(_RE_KEYS)


def compile_predicate(spec: dict) -> Callable[[SkillCtx], bool]:
    bad = set(spec) - _VALID
    if bad:
        raise ValueError(f"unknown predicate keys: {sorted(bad)} (valid: {sorted(_VALID)})")
    lits = {k: tuple(str(x).lower() for x in spec[k]) for k in _LIT_KEYS if k in spec}
    try:
        res = {k: tuple(re.compile(str(x), re.I) for x in spec[k]) for k in _RE_KEYS if k in spec}
    except re.error as e:
        raise ValueError(f"bad regex in predicate: {e}") from e
    repo_in = tuple(str(x).lower() for x in spec.get("repo_in", ()))
    always = bool(spec.get("always", False))

    def _pred(ctx: SkillCtx) -> bool:
        clauses = []
        if always:
            clauses.append(True)
        if "any_text" in lits:
            clauses.append(any(t in ctx.text for t in lits["any_text"]))
        if "all_text" in lits:
            clauses.append(all(t in ctx.text for t in lits["all_text"]))
        if "any_text_regex" in res:
            clauses.append(any(p.search(ctx.text) for p in res["any_text_regex"]))
        for f in _FAMILIES:
            toks = [t.lower() for t in getattr(ctx.signals, f)]
            if f"any_{f}" in lits:
                clauses.append(any(lit in tok for lit in lits[f"any_{f}"] for tok in toks))
            if f"any_{f}_regex" in res:
                clauses.append(any(p.search(tok) for p in res[f"any_{f}_regex"] for tok in toks))
        if repo_in:
            clauses.append((ctx.repo or "").lower() in repo_in)
        return any(clauses)

    return _pred
