import json
import shutil
from pathlib import Path

from groundloop.cli import main
from tests.fixtures.atlas_fixture import build_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures" / "android_ivi"


def test_eval_cli_scores_oof_case(tmp_path):
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(FIX / "gpuimage-352", ds / "GP-352")              # a positive case
    shutil.copytree(FIX / "negatives" / "oof-hold-1", ds / "oof-hold-1")  # an OOF negative
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "scorecard.json"
    rc = main(["eval", "--dataset", str(ds), "--catalog", str(FIX / "catalog.json"),
               "--index-db", db, "--out", str(out)])
    assert rc == 0
    card = json.loads(out.read_text())
    sel = card["arms"]["membership+logs"]["selective"]
    assert sel["abstention_recall_oof"]["n_unanswerable"] == 1        # the OOF case counted
    assert "n_answerable" in card["arms"]["membership+logs"]["forced"]
