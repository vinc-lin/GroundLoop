import json
import shutil
from pathlib import Path

from groundloop.cli import main
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"


def _ds(tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return ds


def test_fixeval_skills_flag_runs_both_arms(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)   # hermetic canned path
    ds, db = _ds(tmp_path), build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    common = ["--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
              "--index-db", db, "--repos", str(FIX / "repos")]
    assert main(["fixeval", *common, "--skills", "none", "--out", str(tmp_path / "off.json")]) == 0
    assert main(["fixeval", *common, "--skills", "mock", "--out", str(tmp_path / "on.json")]) == 0
    assert (tmp_path / "off.json").is_file() and (tmp_path / "on.json").is_file()


def test_compare_emits_accept_verdict(tmp_path):
    # hand-built off/on boards -> compare CLI writes a verdict json with the accept gate
    def board(fr1, fab):
        return {"arms": {"membership+logs": {
            "n": 1, "patch_apply_rate": 1.0, "n_gradeable": 1, "resolved_by_case": {"GP-352": None},
            "file_recall@1": {"value": fr1}, "file_recall@3": {"value": fr1}, "file_recall@5": {"value": fr1},
            "resolved_rate": {"value": None}, "required_api_pass_rate": {"value": None},
            "fabrication_rate": {"value": fab}, "cost_per_solved": None, "cost_total": 0.0,
            "phi_c": {"1.0": fr1}}}}
    (tmp_path / "off.json").write_text(json.dumps(board(0.0, 0.0)))
    (tmp_path / "on.json").write_text(json.dumps(board(1.0, 0.0)))
    out = tmp_path / "verdict.json"
    rc = main(["compare", "--base", str(tmp_path / "off.json"), "--head", str(tmp_path / "on.json"),
               "--arm", "membership+logs", "--out", str(out)])
    assert rc == 0
    v = json.loads(out.read_text())
    assert v["verdict"]["accepted"] and v["metrics"]["file_recall@1"]["delta"] == 1.0
