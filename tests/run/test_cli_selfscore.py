import shutil
from pathlib import Path

from groundloop.cli import main

_FIX = Path(__file__).parent.parent / "fixtures" / "android_ivi"


def test_run_batch_then_grade(tmp_path, capsys):
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(_FIX / "gpuimage-352", ds / "GP-352")            # carries ticket.json + _oracle
    run_out = tmp_path / "run"

    # batch mode: no --case, with --out (hermetic TokenIndex via --index)
    rc = main(["run", "--dataset", str(ds), "--catalog", str(_FIX / "catalog.json"),
               "--index", str(_FIX / "index.json"), "--work", str(tmp_path / "work"),
               "--changes", str(tmp_path / "changes.jsonl"), "--out", str(run_out)])
    assert rc == 0
    assert (run_out / "runs" / "GP-352.json").is_file()
    assert "runs written: 1" in capsys.readouterr().out

    # offline grade -> per-stage scorecard json + md
    card = tmp_path / "card.json"
    rc = main(["grade-run", "--runs", str(run_out), "--dataset", str(ds), "--out", str(card)])
    assert rc == 0
    assert card.is_file() and card.with_suffix(".md").is_file()
    assert "grade-run: 1 cases" in capsys.readouterr().out


def test_run_requires_case_or_out(tmp_path, capsys):
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(_FIX / "gpuimage-352", ds / "GP-352")
    rc = main(["run", "--dataset", str(ds), "--catalog", str(_FIX / "catalog.json"),
               "--index", str(_FIX / "index.json"), "--work", str(tmp_path / "work"),
               "--changes", str(tmp_path / "changes.jsonl")])       # neither --case nor --out
    assert rc == 2
    assert "--case" in capsys.readouterr().out
