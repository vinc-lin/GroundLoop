import json


def test_cli_build_textprofile_hermetic(tmp_path, monkeypatch, capsys):
    from groundloop.cli import main
    # a 2-repo corpus dir with README + a catalog
    for repo, body in {"oboe": "audio playback", "newpipe": "video player"}.items():
        (tmp_path / "corpus" / repo).mkdir(parents=True)
        (tmp_path / "corpus" / repo / "README.md").write_text(body)
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([{"name": "oboe"}, {"name": "newpipe"}]))
    # force the hermetic StubEmbedder (no gateway)
    monkeypatch.setenv("KLOOP_TEXTPROFILE_STUB", "1")
    out = tmp_path / "profiles.db"
    rc = main(["build-textprofile", "--corpus", str(tmp_path / "corpus"),
               "--catalog", str(cat), "--out", str(out)])
    assert rc == 0 and out.exists()
    assert "profiles: 2 repos" in capsys.readouterr().out
