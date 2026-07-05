from groundloop.cli import main


def test_mine_warns_without_index_db(tmp_path, capsys, monkeypatch):
    # stub the miner so this test stays offline and fast (we only assert the warning path)
    import groundloop.cli as cli  # noqa: F401
    monkeypatch.setattr("groundloop.mine.gh_miner.mine",
                        lambda *a, **k: {"harvested": 0, "admitted": 0})
    # a registry-less run: Settings.load().registry may be empty → fleet falls back to [repo_name]
    rc = main(["mine", "--slug", "TeamNewPipe/NewPipe", "--repo-name", "newpipe", "--out", str(tmp_path)])
    assert rc == 0
    assert "closed-loop leak reject is OFF" in capsys.readouterr().out
