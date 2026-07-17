"""Identifier tokenization for the FTS query builder (query side, `store.py::_fts_query`) and — once it
lands — the optional index-time CamelCase expansion (build side). One splitter so query/index tokenization
stay identical. Today `_fts_query` is the only caller (and it filters bare-digit/single-char sub-words to
avoid low-idf noise on the shared Match path); the index-time caller is planned (Task 2)."""
from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9]+")
# Split a run into: an ALL-CAPS acronym (stops before the next CamelCase word, a digit, or end),
# a Capitalized-or-lowercase word, or a digit run. Faithful to the store.py inline regex for every
# non-digit token (byte-identical), and additionally splits digit runs so `HTTP2Client` ->
# ['http','2','client'] instead of the old ['htt','p2','client'] acronym/digit mangling.
_SUB = re.compile(r"[A-Z]+(?=[A-Z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+")


def split_identifier(name: str) -> list[str]:
    """`ScreenshotUtils` -> ['screenshot','utils']. Splits on non-alphanumerics AND camelCase/PascalCase/
    digit runs; lowercased, order-preserving, deduped. '' / all-symbols -> []."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in _WORD.findall(name or ""):
        for part in _SUB.findall(tok):
            p = part.lower()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out
