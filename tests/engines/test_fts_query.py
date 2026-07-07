"""_fts_query must produce a query that NEVER crashes FTS5 — even when the free text contains FTS5
reserved words (NOT/AND/OR/NEAR). Regression for `sqlite3.OperationalError: fts5: syntax error near
"NOT"` hit when a KB skill's Localize hint ("…the native site, NOT the abort frame…") reaches localize."""
from __future__ import annotations

import sqlite3

import pytest

from groundloop.engines.atlas.store import _fts_query


def _match(query: str) -> list[str]:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    db.execute("INSERT INTO t(body) VALUES ('the native site is NOT the abort frame free malloc')")
    db.execute("INSERT INTO t(body) VALUES ('unrelated content here')")
    fts = _fts_query(query)
    rows = db.execute("SELECT body FROM t WHERE t MATCH ? ORDER BY rank", [fts]).fetchall()
    return [r[0] for r in rows]


@pytest.mark.parametrize("q", [
    "onDestroy NOT called",     # the real KB-skill trigger
    "free OR malloc",
    "double free AND detected",
    "NEAR the frame",
    "NOT",
])
def test_reserved_words_do_not_crash_fts5(q):
    # Must not raise sqlite3.OperationalError — reserved words are quoted to literal terms.
    _match(q)


def test_matches_preserved_for_normal_tokens():
    rows = _match("native abort")
    assert any("native" in r for r in rows)          # the seeded row still matches


def test_reserved_word_matches_as_literal():
    rows = _match("NOT")                              # 'NOT' is now a literal term, not the operator
    assert any("NOT" in r for r in rows)              # matches the row that contains the word NOT


def test_tokens_are_quoted():
    assert _fts_query("free NOT malloc") == '"free" OR "NOT" OR "malloc"'
    assert _fts_query("") == '""'                     # empty stays an empty phrase
