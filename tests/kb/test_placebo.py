"""Hermetic tests for the placebo control-corpus generator (Task A2)."""
from __future__ import annotations

from groundloop.kb.placebo import KB_SEED, build_placebo
from groundloop.kb.validate import load_corpus, validate_corpus


def test_build_placebo_mirrors_matches_and_validates(tmp_path):
    out = str(tmp_path / "placebo.toml")
    n = build_placebo(kb_path=KB_SEED, out_path=out)

    kb = load_corpus(KB_SEED)
    placebo = load_corpus(out)

    # returned count agrees, and there is exactly one placebo per KB skill
    assert n == len(kb)
    assert len(placebo) == len(kb)

    # the generated corpus is conforming + leak-safe (validate returns [] == clean)
    assert validate_corpus(out) == []

    kb_by_id = {sk["id"]: sk for sk in kb}
    assert {p["id"] for p in placebo} == {"placebo-" + i for i in kb_by_id}

    for psk in placebo:
        assert psk["id"].startswith("placebo-")
        origin = psk["id"][len("placebo-"):]
        ksk = kb_by_id[origin]
        # fires identically: the match predicate is copied verbatim (round-trips exactly)
        assert psk["match"] == ksk["match"]
        # but the guidance is different (length-matched irrelevant filler)
        assert psk["guidance"] != ksk["guidance"]
        # still structured with the three required clauses (so it validates + injects at both stages)
        for clause in ("Signature:", "Localize:", "Fix:"):
            assert clause in psk["guidance"]
