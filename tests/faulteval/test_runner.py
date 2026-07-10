import json
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.faultlog import build_faultlog_case
from groundloop.faulteval.runner import run_faulteval


def _mk_case(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "boom", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_faulteval_runs_flood_and_faultslice(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _mk_case(tmp_path, "C1", "organicmaps", ["app/src/main/java/app/organicmaps/Framework.java"])
    out = tmp_path / "ds"
    build_faultlog_case(src, store, str(out), difficulty="clean", noise_lines=200)
    (out / "catalog.json").write_text(json.dumps(
        [{"name": r} for r in ("organicmaps", "androidx-media", "cameraview", "android-gpuimage-plus")]))
    card = run_faulteval(str(out), db, arms=("flood", "faultslice"))
    assert set(card["attribution"]["arms"]) >= {"flood", "faultslice"}
    assert "frame@1" in card["localization"]
    assert card["localization"]["n"] == 1


def test_faulteval_routing_arm(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _mk_case(tmp_path, "C9", "organicmaps", ["app/src/main/java/app/organicmaps/Framework.java"])
    out = tmp_path / "ds9"
    build_faultlog_case(src, store, str(out), difficulty="clean", noise_lines=150)
    (out / "catalog.json").write_text(json.dumps(
        [{"name": r} for r in ("organicmaps", "androidx-media", "cameraview", "android-gpuimage-plus")]))
    card = run_faulteval(str(out), db, arms=("flood", "faultslice", "routing"))
    assert "routing" in card["attribution"]["arms"]
    # routing must rank the true owner (organicmaps) top-1 on the app.organicmaps prefix hit
    assert card["attribution"]["arms"]["routing"]["forced"]["recall@1"]["value"] == 1.0
    # routing must ACTUALLY predict (not abstain) — the selective view catches a tau-scale mismatch
    sel = card["attribution"]["arms"]["routing"]["selective"]
    assert sel["coverage"] == 1.0 and sel["selective_accuracy"]["value"] == 1.0
