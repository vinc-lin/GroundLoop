# tests/fixeval/test_cli_fixer_arg.py
from groundloop.cli import build_parser        # parser factory extracted from main()


def test_fixeval_accepts_fixer_plan():
    args = build_parser().parse_args(
        ["fixeval", "--dataset", "d", "--catalog", "c", "--index-db", "x",
         "--repos", "r", "--out", "o", "--fixer", "plan", "--max-replan", "2"])
    assert args.fixer == "plan" and args.max_replan == 2


def test_fixeval_fixer_defaults_direct():
    args = build_parser().parse_args(
        ["fixeval", "--dataset", "d", "--catalog", "c", "--index-db", "x", "--repos", "r", "--out", "o"])
    assert args.fixer == "direct" and args.max_replan == 1
