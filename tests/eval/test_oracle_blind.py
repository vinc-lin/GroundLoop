import json
from pathlib import Path
import pathlib

from groundloop.eval.runner import EvalRunner
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.estate import MockEstate
from tests.fixtures.atlas_fixture import build_atlas_fixture


def test_full_run_reads_no_oracle_and_no_bind_output(tmp_path, monkeypatch):
    d = Path(tmp_path) / "GP-352"
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps(
        {"id": "GP-352", "summary": "s", "description": "d", "component": "", "logs": []}))
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "android-gpuimage-plus"}))
    (Path(tmp_path) / "catalog.json").write_text(json.dumps(
        [{"name": "android-gpuimage-plus"}, {"name": "organicmaps"}, {"name": "cameraview"}]))
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))

    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])

    runner = EvalRunner(issues=MockJira(str(tmp_path)),
                        estate=MockEstate(str(Path(tmp_path) / "catalog.json"), str(tmp_path / "w")),
                        tau_margin=0.5, tau_score=1.0)
    runner.run(load_cases(str(tmp_path)), build_arms(membership_index=AtlasIndex(db)))
    # NOTE: tmp_path itself is named after the test function (e.g.
    # ".../test_full_run_reads_no_oracle_and_no_bind_output0"), which contains the
    # substring "_oracle" -- a plain substring check would false-positive on every
    # path under tmp_path. Check path COMPONENTS instead so only an actual "_oracle"
    # directory segment (the hidden oracle dir) trips the guard.
    assert not any("_oracle" in pathlib.Path(r).parts for r in reads), f"leak: {reads}"
