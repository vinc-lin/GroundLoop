import json

from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.functional import build_functional_case


def _src(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "orig", "description": "orig"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_functional_case_is_prose_only_no_fault_frame(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    src = _src(tmp_path, "U1", "android-gpuimage-plus",
               ["library/src/main/java/org/wysaid/view/ImageGLSurfaceView.java"])
    out = tmp_path / "ds"
    cid = build_functional_case(src, Store(db), str(out), klass="ui_text")
    assert cid == "U1"
    oracle = json.loads((out / "U1" / "_oracle" / "oracle.json").read_text())
    ticket = json.loads((out / "U1" / "ticket.json").read_text())
    assert oracle["bug_kind"] == "functional" and "fault_frame" not in oracle
    assert ticket["logs"] == []                          # UI-text: no logs at all
    assert oracle["owning_repo"] == "android-gpuimage-plus"


def test_carplay_case_has_optional_connection_log(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    src = _src(tmp_path, "C1", "organicmaps",
               ["android/app/src/main/java/app/organicmaps/car/CarAppSession.java"])
    out = tmp_path / "ds"
    build_functional_case(src, Store(db), str(out), klass="carplay")
    ticket = json.loads((out / "C1" / "ticket.json").read_text())
    log = (out / "C1" / ticket["logs"][0]["path"]).read_text() if ticket["logs"] else ""
    assert "connection" in log.lower() or "projection" in log.lower()      # non-crash connection log
    assert "FATAL EXCEPTION" not in log                                    # NOT a crash


def test_functional_negatives_are_unanswerable(tmp_path):
    from groundloop.synth.functional import build_functional_negatives
    out = tmp_path / "neg"
    ids = build_functional_negatives(str(out), n=2)
    assert len(ids) == 2
    for cid in ids:
        oracle = json.loads((out / cid / "_oracle" / "oracle.json").read_text())
        ticket = json.loads((out / cid / "ticket.json").read_text())
        assert oracle["is_answerable"] is False and oracle["bug_kind"] == "functional"
        assert oracle["negative_class"] == "not_a_defect"
        assert oracle["owning_repo"] == "__NOT_A_DEFECT__" and ticket["logs"] == []
