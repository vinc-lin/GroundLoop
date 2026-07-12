import json
import os

from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store
from groundloop.synth.dataset import write_synth_case


def _mk_case(dirp, owner, files):
    os.makedirs(os.path.join(dirp, "_oracle"), exist_ok=True)
    json.dump({"summary": "boom", "logs": []}, open(os.path.join(dirp, "ticket.json"), "w"))
    json.dump({"owning_repo": owner, "expected_files": files, "required_apis": []},
              open(os.path.join(dirp, "_oracle", "oracle.json"), "w"))


def test_positive_oracle_required_apis_is_a_list(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    store = Store(db)
    src = tmp_path / "src" / "C1"
    _mk_case(str(src), "android-gpuimage-plus", ["src/main/cpp/GPUImageFilter.cpp"])
    cid = write_synth_case(str(src), store, str(tmp_path / "out"))
    assert cid == "C1"
    oracle = json.load(open(tmp_path / "out" / "C1" / "_oracle" / "oracle.json"))
    assert isinstance(oracle["required_apis"], list)
    # this native gpuimage case fires a gradeable crash class, so the planted required_api must land
    # in the oracle (overriding the empty source list) — resolution is now gradeable.
    assert oracle["required_apis"], "planted required_api must land in the oracle"
