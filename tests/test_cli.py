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


def test_cli_index_dispatches_and_prints_counts(tmp_path, monkeypatch, capsys):
    """Monkeypatched: index_all stub returns {"repoA": 3}; main(["index","--registry",...]) rc 0."""
    # Write a minimal registry file (raw TOML, no third-party writer needed)
    registry_path = tmp_path / "atlas.toml"
    registry_path.write_text(
        f'[[repo]]\nname = "repoA"\nrepo_path = "{tmp_path}"\nwiki_dir = "{tmp_path}"\n'
    )

    async def _stub_index_all(entries, store, embedder):
        return {"repoA": 3}

    monkeypatch.setattr("groundloop.engines.atlas.index.index_all", _stub_index_all)

    rc = main(["index", "--registry", str(registry_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "indexed repoA: 3" in out


def test_cli_run_with_index_db_no_index_flag(tmp_path, monkeypatch, capsys):
    """--index-db selects AtlasIndex; --index is not required when --index-db is given."""
    import shutil
    from pathlib import Path
    from tests.fixtures.atlas_fixture import build_atlas_fixture

    fix = Path(__file__).parent / "fixtures" / "android_ivi"
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(fix / "gpuimage-352", ds / "GP-352")

    # Build a real atlas.db using the hermetic fixture builder
    atlas_db = build_atlas_fixture(str(tmp_path / "atlas.db"))

    rc = main(["run", "--case", "GP-352", "--dataset", str(ds),
               "--catalog", str(fix / "catalog.json"),
               "--index-db", atlas_db,
               "--work", str(tmp_path / "work"),
               "--changes", str(tmp_path / "changes.jsonl")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "android-gpuimage-plus" in out
