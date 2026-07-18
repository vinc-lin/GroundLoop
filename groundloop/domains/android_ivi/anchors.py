"""Literal-anchor extraction for functional-ticket localization.

For FUNCTIONAL (no-crash, prose-only) tickets the description often names
LITERAL anchors that appear verbatim in code/resources: quoted UI strings,
file extensions ("JPG"/"PNG"), error text, resource IDs, CamelCase symbols.
A literal FTS match on a *good* anchor lands the oracle file where fuzzy
retrieval misses. The hard part is SELECTION: "log" over-matches thousands of
files (noise) while "PNG" hits a few (gold). :func:`extract_anchor_candidates`
turns prose into shape-based candidates; :func:`rare_anchors` gates them by
atlas rarity so only high-value literals survive.
"""

from __future__ import annotations

import re

# quoted spans ("..." / '...'), backtick code spans, CamelCase identifiers,
# ALL-CAPS/extension tokens, dotted/snake identifiers.
_QUOTED = re.compile(r'"([^"]{2,60})"|\'([^\']{2,60})\'')
_BACKTICK = re.compile(r"`([^`]{2,60})`")
_CAMEL = re.compile(r"\b[A-Za-z]*[a-z][A-Z]\w*\b|\b[A-Z]{2,}[a-z]\w*\b")
_ALLCAPS = re.compile(r"\b[A-Z]{2,5}\b")
_DOTTED = re.compile(r"\b\w+[._]\w[\w._]*\b")
# Version / float / measurement tokens (v1.2.3, 24.0f, 3.5mm, 1.2) — number-dominant, never a code
# anchor. Dropped from shape-derived candidates (a quoted/backtick literal still overrides via forced).
_NUMISH = re.compile(r"^v?\d+(?:[._]\d+)*[a-z]{0,3}$", re.I)

# Common english + code words that over-match. NOTE: "error" is intentionally
# absent — ERROR is a valid ALL-CAPS anchor when it appears literally.
_STOPLIST = {
    "the", "a", "an", "is", "are", "when", "then", "fails", "fail", "app",
    "log", "logs", "file", "value", "null", "true", "false", "should", "not",
    "instead", "of", "in", "and", "this", "that", "shown",
}


def extract_anchor_candidates(text: str) -> list[str]:
    """Extract high-value literal anchor candidates from ticket prose.

    Emits, deduped case-insensitively (first original casing preserved):
    quoted spans and backtick code spans (kept intact, even multi-word),
    CamelCase identifiers, ALL-CAPS/extension tokens, and dotted/snake
    identifiers. Stoplisted common words are dropped UNLESS they came from an
    explicit quote/backtick (an explicit anchor overrides the stoplist).
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str | None, forced: bool = False) -> None:
        if not s:
            return
        s = s.strip()
        key = s.lower()
        if not s or key in seen:
            return
        if not forced and (key in _STOPLIST or _NUMISH.match(s)):
            return
        seen.add(key)
        out.append(s)

    for m in _QUOTED.finditer(text):
        add(m.group(1) or m.group(2), forced=True)
    for m in _BACKTICK.finditer(text):
        add(m.group(1), forced=True)
    for rx in (_CAMEL, _DOTTED, _ALLCAPS):
        for m in rx.finditer(text):
            add(m.group(0))
    return out


def rare_anchors(
    candidates: list[str],
    store,
    repo: str,
    *,
    max_files: int = 10,
    max_anchors: int = 6,
) -> list[str]:
    """Gate anchor candidates by atlas rarity, rarest first.

    For each candidate, count DISTINCT files a literal keyword search over the
    given ``repo`` hits. Keep only candidates whose distinct-file count is in
    ``[1, max_files]`` — a zero-hit anchor has nothing to point at, and an
    over-matching one (>``max_files``, e.g. "log") is noise. Survivors are
    sorted ascending by hit count (rarest = most discriminating first) and the
    first ``max_anchors`` returned. A bad anchor must never sink localize, so a
    store error on any candidate skips just that candidate.
    """
    scored: list[tuple[int, str]] = []
    for c in candidates:
        try:
            rows = store.keyword_search(c, k=max_files + 1, repos=[repo], kinds=["symbol"])
        except Exception:
            continue
        n = len({u.file for u, _ in rows if getattr(u, "file", None)})
        if 1 <= n <= max_files:
            scored.append((n, c))
    scored.sort(key=lambda t: t[0])
    return [c for _, c in scored[:max_anchors]]
