import json

from tests.fixtures.atlas_fixture import build_atlas_fixture

from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.engines.atlas.embed import StubEmbedder


def test_cli_funceval(tmp_path, monkeypatch, capsys):
    from groundloop.cli import main
    ds = tmp_path / "ds"
    d = ds / "f1"
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": "f1", "summary": "offline maps route", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "organicmaps", "is_answerable": True, "bug_kind": "functional"}))
    (ds / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "android-gpuimage-plus"}]))
    prof = build_text_profiles({"organicmaps": ["offline maps route navigation"],
                                "android-gpuimage-plus": ["image filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    monkeypatch.setenv("KLOOP_TEXTPROFILE_STUB", "1")     # force StubEmbedder in the CLI
    rc = main(["funceval", "--dataset", str(ds), "--profile-db", prof, "--index-db", atlas,
               "--arms", "functional,dispatch", "--out", str(tmp_path / "card.json")])
    assert rc == 0 and (tmp_path / "card.json").exists()
    assert "functional" in capsys.readouterr().out
