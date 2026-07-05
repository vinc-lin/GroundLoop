import json
import shutil
from pathlib import Path

from groundloop.cli import main
from groundloop.fixeval.report import render_fix_markdown
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"


def test_fixeval_cli_writes_scorecard(tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "fix-scorecard.json"
    # no KLOOP_PRODUCE_API_KEY in the hermetic env -> canned model, all cases abstain (still a valid card)
    rc = main(["fixeval", "--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
               "--index-db", db, "--repos", str(FIX / "repos"), "--out", str(out)])
    assert rc == 0
    card = json.loads(out.read_text())
    assert "arms" in card and "membership+logs" in card["arms"]
    assert out.with_suffix(".md").is_file()


def test_render_fix_markdown_shape():
    card = {"arms": {"membership+logs": {
        "n": 1, "patch_apply_rate": 1.0, "n_gradeable": 1,
        "file_recall@1": {"value": 1.0}, "required_api_pass_rate": {"value": 1.0},
        "resolved_rate": {"value": 1.0}, "fabrication_rate": {"value": 0.0}, "cost_per_solved": None}}}
    md = render_fix_markdown(card)
    assert "# Fix-loop scorecard" in md and "membership+logs" in md and "ADVISORY" in md
