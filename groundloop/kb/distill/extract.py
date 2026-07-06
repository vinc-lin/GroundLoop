"""Oracle-blind guidance distiller (Phase C, GATED).

`distill_guidance(traces)` turns a batch of LOOP-VISIBLE fix-loop traces into one distilled guidance
string by EXTRACTING verbatim spans from the `injected_guidance` of traces that HELPED — never by
free-synthesizing new prose. It is oracle-blind by construction:

* it REFUSES any trace carrying an oracle-ish key (`owning_repo` / `expected_files`) — raising
  ValueError for the whole batch, and
* it RE-RUNS the KB leak check (`groundloop.kb.validate.owner_denylist`) over each extracted span,
  dropping any span that names a fleet owner token, so the distilled form stays generic to the crash
  SIGNATURE.

A trace is LOOP-VISIBLE ONLY:
    {"ticket_summary": str, "signals": dict, "injected_guidance": str, "patch_diff": str,
     "helped": bool}
"""
from __future__ import annotations

from groundloop.kb.validate import owner_denylist

# Presence of any of these proves the trace was assembled with oracle knowledge — refuse the batch.
_ORACLE_KEYS = frozenset({"owning_repo", "expected_files"})


def _has_leak(span: str, deny: set[str]) -> bool:
    """True if any owner-denylist token is a substring of `span` (same test as validate_corpus)."""
    hay = span.lower()
    return any(tok in hay for tok in deny)


def distill_guidance(traces: list[dict]) -> str:
    """Extract + leak-scrub distilled guidance from helped fix-loop traces.

    Raises ValueError if ANY trace carries an oracle-ish key (owning_repo / expected_files).
    Returns verbatim, order-preserving, de-duplicated non-empty lines drawn ONLY from the
    `injected_guidance` of `helped` traces, with every owner-token line dropped (leak-scrub).
    """
    for i, trace in enumerate(traces):
        leaked = _ORACLE_KEYS.intersection(trace)
        if leaked:
            raise ValueError(
                f"trace[{i}] carries oracle key(s) {sorted(leaked)} — distiller is oracle-blind"
            )

    deny = owner_denylist()
    out: list[str] = []
    seen: set[str] = set()
    for trace in traces:
        if not trace.get("helped"):
            continue
        for raw in str(trace.get("injected_guidance", "")).splitlines():
            line = raw.strip()
            if not line or line in seen:
                continue
            if _has_leak(line, deny):
                continue
            seen.add(line)
            out.append(line)
    return "\n".join(out)
