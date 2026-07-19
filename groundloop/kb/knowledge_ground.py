"""Deterministic, oracle-blind ground-check for a candidate Knowledge item (design spec §5.2).

A knowledge item is admitted to the store only if it (a) is WELL-FORMED — a non-empty `signature` OR
`content` body, a non-empty `id`, an optional `type` that (when set) is one of `_VALID_TYPES`, and a
compilable applies_when predicate (reuse skills/predicate.compile_predicate). This is shape-tolerant by
design (expand-migrate-contract): a LEGACY item (from kb/extract.py) sets `type`/`content`; a new
playbook item (from seed/mint) sets `signature`/`localize`/`fix`/`required_apis` and leaves `type` blank
— both ground the same way. (b) is GROUNDED — every
grounding_ref resolves in the atlas (some unit exists for it, fleet-wide) — and (c) is LEAK-SAFE — its
content / grounding_refs / applies_when name NO fleet-owner token (the same FLEET_OWNER_TOKENS red-test the
KB corpus passes, via kb/validate.owner_denylist). Checking FLEET-WIDE existence reveals nothing about WHICH
repo owns the defect, so the gate stays oracle-blind; the atlas is code reality, never the answer.

`resolver(ref) -> bool` decouples the gate from a live atlas so it is hermetic-testable. The production
resolver is `atlas_resolver(store)`, a thin wrapper over Store.keyword_search (queried across ALL repos —
never scoped to the predicted/owning repo).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from groundloop.kb.validate import owner_denylist
from groundloop.skills.predicate import compile_predicate

_VALID_TYPES = ("localize_hint", "fix_step", "api_requirement")


@dataclass(frozen=True)
class GroundCheck:
    grounded: bool
    resolved_refs: tuple[str, ...]
    missing_refs: tuple[str, ...]
    leak_tokens: tuple[str, ...]
    reasons: tuple[str, ...]


def _bounded(ref: str) -> re.Pattern:
    """A whole-identifier matcher for a grounding ref: the ref must appear delimited by non-identifier
    chars (treating `_` as part of the identifier). This rejects a fabricated `get_totally_fake_buffer`
    that would otherwise ride on a real `getBuffer`, and a qualified `std::totally_made_up::lock` that
    would otherwise ride on a real `lock`. A qualified ref may still match as a boundary-delimited suffix
    of a longer indexed qualified_name (e.g. `Foo::bar` inside `ns::Foo::bar`) — tolerant of over-
    qualification, but never of the bare last segment alone."""
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(ref)}(?![A-Za-z0-9_])", re.IGNORECASE)


def atlas_resolver(store, *, k: int = 20) -> Callable[[str], bool]:
    """A fleet-wide EXACT existence probe over the atlas: a ref resolves iff some indexed unit actually
    NAMES it — its whole identifier appears verbatim (whole-word) in a returned unit's name /
    qualified_name / text, across ALL repos (oracle-blind — never scoped to the predicted/owning repo).

    Why the post-filter: Store.keyword_search runs the ref through `_fts_query`, which OR-splits a
    qualified/snake ref (`std::weak_ptr::lock` -> std OR weak OR ptr OR lock) — so a bare truthiness check
    grounds a *fabricated* ref whenever ANY subtoken exists standalone fleet-wide. We use keyword_search
    only for RECALL (candidate units), then require the FULL ref to appear verbatim in a candidate before
    admitting it — defeating hallucinated qualified/snake refs.

    Implementer-verify (confirmed in engines/atlas/store.py): Store.keyword_search(query, k=20, repos=None,
    kinds=None) -> list[(Unit, rank)]; Unit carries .name/.qualified_name/.text; an empty query is
    sanitized safely by _fts_query.
    """
    def _resolves(ref: str) -> bool:
        ref = (ref or "").strip()
        if not ref:
            return False
        pat = _bounded(ref)
        try:
            hits = store.keyword_search(ref, k=k)
        except sqlite3.Error:                          # a malformed FTS term is 'not found', not masked infra
            return False
        for unit, _rank in hits:
            hay = " ".join((getattr(unit, "name", "") or "",
                            getattr(unit, "qualified_name", "") or "",
                            getattr(unit, "text", "") or ""))
            if pat.search(hay):
                return True
        return False
    return _resolves


def _leak_haystack(knowledge) -> str:
    """Lowercased signature/localize/fix/required_apis/content/grounding_refs + applies_when values — the
    same surface validate_corpus scans. Shape-tolerant (getattr with a default) so it scans whichever
    fields a legacy `content`-shaped item or a new `signature`-shaped playbook item actually carries."""
    parts = [
        getattr(knowledge, "signature", "") or "",
        " ".join(getattr(knowledge, "localize", ()) or ()),
        " ".join(getattr(knowledge, "fix", ()) or ()),
        " ".join(getattr(knowledge, "required_apis", ()) or ()),
        getattr(knowledge, "content", "") or "",
        " ".join(getattr(knowledge, "grounding_refs", ()) or ()),
    ]
    for v in (knowledge.applies_when or {}).values():
        if isinstance(v, (list, tuple)):
            parts.append(" ".join(str(x) for x in v))
    return "\n".join(parts).lower()


def check_knowledge_grounded(knowledge, resolver: Callable[[str], bool], *,
                             denylist: Optional[set[str]] = None) -> GroundCheck:
    """Dispose one candidate Knowledge item. Grounded iff there are no reasons: well-formed AND every
    grounding_ref resolves AND no fleet-owner leak. `denylist` defaults to the
    FLEET_OWNER_TOKENS-derived owner_denylist()."""
    deny = owner_denylist() if denylist is None else denylist
    reasons: list[str] = []

    # (a) well-formedness — an item that can't type-check or can't fire is never grounded/effective.
    # Shape-tolerant during the expand-migrate-contract reshape: a legacy item carries `type`/`content`,
    # a new playbook item carries `signature` (+ `localize`/`fix`/`required_apis`) and leaves `type` blank
    # — so `type` is only checked when non-empty, and the body check accepts EITHER `signature` OR `content`.
    if knowledge.type and knowledge.type not in _VALID_TYPES:
        reasons.append(f"bad_type:{knowledge.type}")
    if not ((knowledge.signature or "").strip() or (knowledge.content or "").strip()):
        reasons.append("empty_body")
    if not (knowledge.id or "").strip():
        reasons.append("empty_id")
    if not knowledge.applies_when:
        reasons.append("empty_predicate")             # would never fire
    else:
        try:
            compile_predicate(knowledge.applies_when)  # reuse: closed-vocab keys + eager regex compile
        except ValueError as e:
            reasons.append(f"bad_predicate:{e}")

    # (b) existence — every grounding_ref must resolve fleet-wide in the atlas (else hallucinated).
    resolved: list[str] = []
    missing: list[str] = []
    for ref in knowledge.grounding_refs:
        (resolved if resolver(ref) else missing).append(ref)
    if not knowledge.grounding_refs:
        reasons.append("no_grounding_refs")           # cites nothing -> nothing grounded
    if missing:
        reasons.append("unresolved_refs:" + ",".join(missing))

    # (c) leak red-test — no fleet-owner token in content/grounding_refs/applies_when (generic android.*
    #     / androidx.* / sonames are KEPT, exactly as validate_corpus).
    hay = _leak_haystack(knowledge)
    leak = tuple(tok for tok in sorted(deny) if tok in hay)
    if leak:
        reasons.append("leak:" + ",".join(leak))

    return GroundCheck(grounded=not reasons, resolved_refs=tuple(resolved),
                       missing_refs=tuple(missing), leak_tokens=leak, reasons=tuple(reasons))
