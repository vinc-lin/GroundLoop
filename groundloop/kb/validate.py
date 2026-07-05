"""Validator + loader for the dev-experience KB feedstock corpus (`groundloop/kb/data/*.toml`).

The corpus is DATA conforming to the SP3 Skill TOML contract (`groundloop/skills/base.Skill` +
`skills/predicate.compile_predicate`, currently on the `worktree-sp3-kb-arm` branch). This module is a
DECOUPLED mirror of that contract so the corpus is authorable + regression-checkable on master before
SP3 merges. Two gates:

1. **Closed-vocab predicate conformance** — every `[skill.match]` key must be in the SP3 vocabulary
   (`_VALID_MATCH_KEYS` mirrors `skills/predicate._VALID`); regexes must compile. We additionally
   FORBID `always`/`repo_in` here: a repo-pinned or always-on Skill is a lookup-table row / overfit,
   the opposite of a generalizing playbook.
2. **Leak red-test** — `guidance`/`signals`/`hint_apis`/`match` values may name NO fleet owner token
   (repo name + namespaces + slugs + sonames, sourced from the authoritative `FLEET_OWNER_TOKENS`),
   so every playbook stays generic to the crash SIGNATURE. `KEEP` dependency tokens (android./androidx.
   /SurfaceTexture/libaaudio.so …) are NOT leaks and are intentionally excluded from the denylist.

Post-merge, `tests/kb/test_feedstock.py` additionally loads the corpus through the REAL
`groundloop.skills` loader (`pytest.importorskip`) to catch any drift from this mirror.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from groundloop.domains.android_ivi.owner_tokens import FLEET_OWNER_TOKENS

# --- closed match vocabulary: MUST mirror groundloop/skills/predicate._VALID (SP3) ---
_FAMILIES = ("packages", "classes", "methods", "symbols", "libraries", "errors")
_LIT_KEYS = ("any_text", "all_text") + tuple(f"any_{f}" for f in _FAMILIES)
_RE_KEYS = ("any_text_regex",) + tuple(f"any_{f}_regex" for f in _FAMILIES)
_VALID_MATCH_KEYS = {"always", "repo_in"} | set(_LIT_KEYS) | set(_RE_KEYS)
_REGEX_KEYS = set(_RE_KEYS)

# authoring policy (stricter than the SP3 contract): Skills must be repo-agnostic, so these are banned
_FORBIDDEN_MATCH_KEYS = {"always", "repo_in"}
_REQUIRED_CLAUSES = ("Signature:", "Localize:", "Fix:")

SEED_PATH = str(Path(__file__).parent / "data" / "aaos_kb_seed.toml")


def owner_denylist() -> set[str]:
    """Lowercased owner-identifying tokens whose presence in a Skill is a leak: each fleet repo's
    short name + its namespaces + slugs + sonames. `KEEP` (generic dependency) tokens are excluded."""
    deny: set[str] = set()
    for repo, row in FLEET_OWNER_TOKENS.items():
        deny.add(repo.lower())
        for key in ("namespaces", "slugs", "sonames"):
            for tok in row.get(key, ()):
                if tok:
                    deny.add(str(tok).lower())
    return deny


def load_corpus(path: str) -> list[dict]:
    """Parse a corpus TOML into a list of raw skill dicts (the `[[skill]]` array)."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return list(raw.get("skill", []))


def _skill_haystack(sk: dict) -> str:
    parts = [sk.get("guidance", ""), " ".join(sk.get("signals", ())), " ".join(sk.get("hint_apis", ()))]
    for v in (sk.get("match", {}) or {}).values():
        if isinstance(v, (list, tuple)):
            parts.append(" ".join(str(x) for x in v))
    return "\n".join(parts).lower()


def validate_corpus(path: str) -> list[str]:
    """Return a list of human-readable issues; empty == conforming + leak-safe."""
    issues: list[str] = []
    skills = load_corpus(path)
    if not skills:
        return [f"{path}: no [[skill]] entries"]
    deny = owner_denylist()
    seen_ids: set[str] = set()
    for sk in skills:
        sid = sk.get("id") or "<no-id>"
        if not sk.get("id"):
            issues.append(f"{sid}: missing id")
        if sid in seen_ids:
            issues.append(f"{sid}: duplicate id")
        seen_ids.add(sid)
        if not sk.get("provenance"):
            issues.append(f"{sid}: missing provenance")
        guidance = sk.get("guidance", "")
        for clause in _REQUIRED_CLAUSES:
            if clause not in guidance:
                issues.append(f"{sid}: guidance missing '{clause}' clause")
        match = sk.get("match", {}) or {}
        if not match:
            issues.append(f"{sid}: empty match (would never fire — 'always' is forbidden)")
        for key, val in match.items():
            if key not in _VALID_MATCH_KEYS:
                issues.append(f"{sid}: unknown match key '{key}'")
                continue
            if key in _FORBIDDEN_MATCH_KEYS:
                issues.append(f"{sid}: forbidden match key '{key}' (Skills must be repo-agnostic)")
            if key in _REGEX_KEYS:
                for pat in val:
                    try:
                        re.compile(str(pat))
                    except re.error as e:
                        issues.append(f"{sid}: bad regex '{pat}' in {key}: {e}")
        hay = _skill_haystack(sk)
        for tok in sorted(deny):
            if tok in hay:
                issues.append(f"{sid}: LEAK — owner token '{tok}' present in guidance/signals/match")
    return issues
