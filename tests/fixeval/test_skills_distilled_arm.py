# tests/fixeval/test_skills_distilled_arm.py
from groundloop.cli import _load_skills, build_parser          # adjust factory name if different
from groundloop.kb.validate import SEED_PATH as KB_SEED


def test_distilled_kind_loads_a_corpus():
    # distilled.toml has the SAME shape as the KB seed; prove the 'distilled' kind resolves + loads a
    # corpus (the KB seed stands in for distilled.toml here via the --skills-seed override path).
    reg = _load_skills("distilled", KB_SEED, None)
    assert reg is not None


def test_fixeval_accepts_skills_distilled():
    args = build_parser().parse_args(
        ["fixeval", "--dataset", "d", "--catalog", "c", "--index-db", "x", "--repos", "r",
         "--out", "o", "--fixer", "plan", "--skills", "distilled"])
    assert args.skills == "distilled"
