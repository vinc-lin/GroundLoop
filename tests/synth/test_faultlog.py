import json
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.faultlog import build_faultlog_case


def _src_case(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "boom", "description": "crash"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_faultlog_clean_case(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _src_case(tmp_path, "C1", "organicmaps", ["app/organicmaps/Framework.java"])
    cid = build_faultlog_case(src, store, str(tmp_path / "out"), difficulty="clean", noise_lines=300)
    assert cid == "C1"
    out = tmp_path / "out" / "C1"
    log = (out / "logs" / "000.txt").read_text()
    oracle = json.loads((out / "_oracle" / "oracle.json").read_text())
    assert len(log.splitlines()) > 300
    assert ("FATAL EXCEPTION" in log) or ("signal " in log) or ("ANR in" in log)
    assert oracle["fault_frame"] and oracle["fault_file"] and oracle["fault_family"] in ("java", "native", "anr")
    assert oracle["fault_frame"].split(".")[-1] in log or oracle["fault_frame"].split("::")[-1] in log
    ticket = json.loads((out / "ticket.json").read_text())
    assert ticket["logs"][0]["path"] == "logs/000.txt"


def test_faultlog_is_deterministic(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _src_case(tmp_path, "C2", "organicmaps", ["app/organicmaps/Framework.java"])
    build_faultlog_case(src, store, str(tmp_path / "o1"), difficulty="clean", noise_lines=200)
    build_faultlog_case(src, store, str(tmp_path / "o2"), difficulty="clean", noise_lines=200)
    assert (tmp_path / "o1" / "C2" / "logs" / "000.txt").read_text() == \
           (tmp_path / "o2" / "C2" / "logs" / "000.txt").read_text()
