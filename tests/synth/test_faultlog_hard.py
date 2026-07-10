import json
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.faultlog import build_faultlog_case


def _src(tmp, cid, owner, files):
    d = tmp / "src" / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "b", "description": "x"}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True}))
    return str(d)


def test_hard_injects_nonowner_decoys(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = _src(tmp_path, "H1", "oboe", ["src/aaudio/AAudioStream.cpp"])
    build_faultlog_case(src, store, str(tmp_path / "out"), difficulty="hard", noise_lines=200)
    out = tmp_path / "out" / "H1"
    log = (out / "logs" / "000.txt").read_text()
    oracle = json.loads((out / "_oracle" / "oracle.json").read_text())
    # decoys are recorded and point at NON-owner repos (never the owner's own tokens)
    assert oracle["decoys"] and "oboe" not in " ".join(oracle["decoys"])
    # at least one non-owner namespace/soname decoy appears in the log noise
    assert any(d in log for d in oracle["decoys"])
    # the true fault (owner) is still present
    assert oracle["fault_frame"].split("::")[-1] in log or oracle["fault_frame"].split(".")[-1] in log
