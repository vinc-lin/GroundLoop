"""Mint a candidate KnowledgePlaybook from a clean-applying fix (oracle-blind). Trigger: patch_applies.
Fields come from the loop's own artifacts (signals/locations/diff); refs must ground; id = crash-class
fingerprint so same-class fixes dedupe."""
from __future__ import annotations

import hashlib
import re

from groundloop.kb.knowledge import KnowledgePlaybook
from groundloop.kb.knowledge_ground import check_knowledge_grounded

_MINT_EVIDENCE = {"measured_lift": {}, "wilson95": None, "validating_case_ids": [], "fail_count": 0, "demotions": []}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.:]{2,}")


def _sig_tokens(signals) -> list[str]:
    toks: list[str] = []
    for fam in ("errors", "classes", "methods", "symbols", "libraries", "packages"):
        toks += [str(t) for t in (getattr(signals, fam, ()) or ())]
    return toks


def crash_class_id(signals) -> str:
    key = "|".join(sorted(set(_sig_tokens(signals))))
    return "minted-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _refs_from_diff(diff: str, signals) -> tuple[str, ...]:
    """Keep ONLY diff identifiers that are crash-named code entities (guaranteed resolvable + relevant),
    splitting qualified tokens into segments. Comment words / keywords / local vars / qualified prefixes
    that the crash never named are noise and are dropped — so mint grounds on the fix's meaningful refs,
    not on every added-line token (which would make a realistic diff effectively never mint)."""
    added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    segs: set[str] = set()
    for tok in _IDENT.findall(added):
        segs.add(tok)                                  # keep the full qualified token
        segs |= {s for s in re.split(r"[.:]+", tok) if s}   # AND its dot/:: segments
    vocab = set()
    for fam in ("methods", "symbols", "classes", "libraries"):
        vocab |= {str(t) for t in (getattr(signals, fam, ()) or ())}
    return tuple(sorted(s for s in segs if s in vocab))   # keep ONLY crash-named entities the fix touched


def mint_playbook(*, ticket_id, signals, locations, patch_diff, resolver, denylist=None):
    toks = _sig_tokens(signals)
    refs = _refs_from_diff(patch_diff, signals)
    pb = KnowledgePlaybook(
        id=crash_class_id(signals),
        applies_when={"any_text": [t.lower() for t in toks]} if toks else {},
        signature=" ".join(toks) or "(unlabelled crash)", localize=tuple(locations),
        fix=(f"touched: {', '.join(refs)}",) if refs else (), required_apis=refs, grounding_refs=refs,
        provenance=f"minted:{ticket_id}", tier="candidate", evidence=dict(_MINT_EVIDENCE))
    chk = check_knowledge_grounded(pb, resolver, denylist=denylist)
    return pb if chk.grounded else None
