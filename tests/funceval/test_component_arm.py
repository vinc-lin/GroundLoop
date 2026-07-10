import json

from tests.fixtures.atlas_fixture import build_atlas_fixture

from groundloop.funceval.runner import run_funceval


def _case(ds, cid, component, owner):
    d = ds / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "x", "description": "x",
                                               "component": component}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "is_answerable": True, "bug_kind": "functional"}))


def _setup(tmp_path):
    ds = tmp_path / "ds"
    _case(ds, "c1", "MapUI", "organicmaps")
    _case(ds, "c2", "MapUI", "organicmaps")
    _case(ds, "c3", "CamUI", "cameraview")
    (ds / "catalog.json").write_text(json.dumps(
        [{"name": "organicmaps"}, {"name": "cameraview"}, {"name": "android-gpuimage-plus"}]))
    aff = tmp_path / "aff.json"
    aff.write_text(json.dumps({"MapUI": {"organicmaps": 2}, "CamUI": {"cameraview": 1}}))
    return ds, aff, build_atlas_fixture(str(tmp_path / "a.db"))


def test_component_arm_full_table_ranks_owner(tmp_path):
    ds, aff, atlas = _setup(tmp_path)
    from groundloop.engines.atlas.embed import StubEmbedder
    prof = build_atlas_fixture(str(tmp_path / "p.db"))     # reuse fixture as a stand-in profile db
    card = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                        arms=("component",), affinity_path=str(aff), loo=False)
    arm = card["attribution"]["arms"]["component"]
    assert arm["forced"]["recall@1"]["value"] == 1.0      # component prior ranks the owner #1


def test_loo_is_load_bearing(tmp_path):
    # c3 is the SOLE contributor to CamUI -> under LOO its own boost vanishes, so it can no longer be
    # attributed by the prior alone; full-table mode still attributes it. Proves LOO actually excludes.
    ds, aff, atlas = _setup(tmp_path)
    from groundloop.engines.atlas.embed import StubEmbedder
    prof = build_atlas_fixture(str(tmp_path / "p.db"))
    full = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                        arms=("component",), affinity_path=str(aff), loo=False)
    loo = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                       arms=("component",), affinity_path=str(aff), loo=True)
    r_full = full["attribution"]["arms"]["component"]["forced"]["recall@1"]["value"]
    r_loo = loo["attribution"]["arms"]["component"]["forced"]["recall@1"]["value"]
    assert r_loo < r_full                                  # LOO removes the memorized sole-contributor win
