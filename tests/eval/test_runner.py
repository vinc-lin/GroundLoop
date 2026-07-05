import json
from pathlib import Path

from groundloop.eval.runner import EvalRunner, MatchRecord
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.estate import MockEstate
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _seed_case(root):
    d = Path(root) / "GP-352"
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({
        "id": "GP-352", "summary": "crash on GL thread applying filter",
        "description": "UnsatisfiedLinkError CGEImageHandler",
        "component": "", "logs": [{"path": "logs/c.txt", "kind": "logcat"}]}))
    (d / "logs" / "c.txt").write_text(
        "java.lang.UnsatisfiedLinkError: org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler")
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "android-gpuimage-plus"}))


def _catalog(root):
    p = Path(root) / "catalog.json"
    p.write_text(json.dumps([{"name": "android-gpuimage-plus"}, {"name": "organicmaps"},
                             {"name": "androidx-media"}, {"name": "cameraview"}]))
    return str(p)


def test_runner_produces_records_per_case_x_arm(tmp_path):
    _seed_case(tmp_path)
    cat = _catalog(tmp_path)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    arms = build_arms(membership_index=AtlasIndex(db))
    runner = EvalRunner(issues=MockJira(str(tmp_path)),
                        estate=MockEstate(cat, str(tmp_path / "work")),
                        tau_margin=0.5, tau_score=1.0)
    cases = load_cases(str(tmp_path))
    records = runner.run(cases, arms)

    assert len(records) == 2                      # 1 case x 2 arms
    assert {r.arm for r in records} == {"membership+text", "membership+logs"}
    logs_rec = next(r for r in records if r.arm == "membership+logs")
    # +logs arm should rank the owning repo first from the CGEImageHandler signal
    assert logs_rec.ranked_names[0] == "android-gpuimage-plus"
    assert isinstance(logs_rec, MatchRecord)


def test_runner_never_reads_oracle(tmp_path, monkeypatch):
    _seed_case(tmp_path)
    cat = _catalog(tmp_path)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    arms = build_arms(membership_index=AtlasIndex(db))
    runner = EvalRunner(issues=MockJira(str(tmp_path)),
                        estate=MockEstate(cat, str(tmp_path / "work")),
                        tau_margin=0.5, tau_score=1.0)

    import pathlib
    reads = []
    orig = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text",
                        lambda self, *a, **k: (reads.append(str(self)), orig(self, *a, **k))[1])
    runner.run(load_cases(str(tmp_path)), arms)
    # Check path PARTS (not a raw substring) — tmp_path's own dir name embeds "_oracle" as a
    # substring of this test's name ("..._reads_oracle0"), which would false-positive a naive
    # substring check. Matches the invariant-4 pattern in tests/test_invariants.py.
    leaked = [r for r in reads if "_oracle" in pathlib.Path(r).parts]
    assert not leaked, f"runner read the oracle: {leaked}"
