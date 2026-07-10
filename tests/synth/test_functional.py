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


def test_audio_log_so_is_owner_derived_not_hardcoded_oboe(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    src = _src(tmp_path, "A1", "android-gpuimage-plus",
               ["library/src/main/java/org/wysaid/view/ImageGLSurfaceView.java"])
    out = tmp_path / "ds"
    build_functional_case(src, Store(db), str(out), klass="audio")
    log = (out / "A1" / "logs" / "000.txt").read_text()
    assert "liboboe.so" not in log                       # no false oboe signal for a gpuimage case
    assert "libCGE.so" in log                             # owner-derived .so (gpuimage native surface)


_FLEET = {
    "organicmaps": "android/app/src/main/java/app/organicmaps/car/CarAppSession.java",
    "cameraview": "cameraview/src/main/java/com/otaliastudios/cameraview/CameraView.java",
    "oboe": "src/flowgraph/SourceI16.cpp",
}


def test_ticket_text_never_names_the_owner(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "a.db"))
    out = tmp_path / "ds"
    for i, (owner, path) in enumerate(_FLEET.items()):
        cid = f"L{i}"
        src = _src(tmp_path, cid, owner, [path])
        build_functional_case(src, Store(db), str(out), klass="ui_text")
        ticket = json.loads((out / cid / "ticket.json").read_text())
        assert owner not in ticket["summary"].lower()       # symptom prose only — no owner slug
        assert owner not in ticket["description"].lower()    # (spec §10 invariant #3)


def test_carplay_log_channel_extracts_owner_tokens(tmp_path):
    from dataclasses import replace

    from groundloop.core.types import LogAttachment, Ticket
    from groundloop.domains.android_ivi.functional_signals import pack_prose

    db = build_atlas_fixture(str(tmp_path / "a.db"))
    src = _src(tmp_path, "C2", "organicmaps",
               ["android/app/src/main/java/app/organicmaps/car/CarAppSession.java"])
    out = tmp_path / "ds"
    build_functional_case(src, Store(db), str(out), klass="carplay")
    ticket = json.loads((out / "C2" / "ticket.json").read_text())
    log_text = (out / "C2" / ticket["logs"][0]["path"]).read_text()
    log = LogAttachment(path="logs/000.txt", kind="logcat", content=log_text)
    sig = pack_prose(Ticket(id="C2", summary=ticket["summary"], description=ticket["description"]), (log,))
    assert sig.classes                                        # log names the owner's real class
    assert replace(sig, symbols=()).tokens()                 # -> the optional log-RRF channel will fire


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
