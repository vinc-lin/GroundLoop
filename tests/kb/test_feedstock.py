"""The KB feedstock corpus must stay conforming to the SP3 Skill contract + leak-safe (grounding)."""
import pytest

from groundloop.kb.validate import SEED_PATH, load_corpus, owner_denylist, validate_corpus

_CLAUSES = ("Signature:", "Localize:", "Fix:")


def test_corpus_validates_clean():
    issues = validate_corpus(SEED_PATH)
    assert issues == [], f"corpus not clean: {issues}"


def test_corpus_nontrivial_with_unique_ids():
    skills = load_corpus(SEED_PATH)
    assert len(skills) >= 11
    ids = [s["id"] for s in skills]
    assert len(ids) == len(set(ids)), "duplicate skill ids"


def test_every_skill_is_localization_first():
    for s in load_corpus(SEED_PATH):
        for clause in _CLAUSES:
            assert clause in s["guidance"], f"{s['id']} missing '{clause}' clause"


def test_no_owner_token_leaks():
    deny = owner_denylist()
    for s in load_corpus(SEED_PATH):
        hay = " ".join([s["guidance"], *s.get("signals", []), *s.get("hint_apis", [])]).lower()
        for tok in deny:
            assert tok not in hay, f"{s['id']} leaks owner token {tok!r}"


def test_loads_under_real_sp3_loader_when_present():
    """Drift guard: once SP3's skills package merges to master, the corpus must load and every
    predicate must compile under the REAL loader (compile_predicate raises on a bad spec).
    Skipped until then."""
    mod = pytest.importorskip("groundloop.adapters.skills.mock")
    skills = mod.load_skills(SEED_PATH)
    assert len(skills) >= 11
