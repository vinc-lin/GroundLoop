from groundloop.cli import main


def test_cli_run_returns_zero(tmp_path, monkeypatch, capsys):
    import shutil
    from pathlib import Path
    fix = Path(__file__).parent / "fixtures" / "android_ivi"
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(fix / "gpuimage-352", ds / "GP-352")
    rc = main(["run", "--case", "GP-352", "--dataset", str(ds),
               "--catalog", str(fix / "catalog.json"), "--index", str(fix / "index.json"),
               "--work", str(tmp_path / "work"), "--changes", str(tmp_path / "changes.jsonl")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "android-gpuimage-plus" in out
