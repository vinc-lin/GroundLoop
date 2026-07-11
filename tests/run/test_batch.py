import json
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.adapters.estate import MockEstate, RecordingEstate
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.run.batch import run_dataset
from groundloop.run.record import RunRecordIO


class _StubIndex:
    def rank_repos(self, signals, catalog):
        from groundloop.core.types import RepoScore
        return [RepoScore(r, 1.0 - i * 0.1) for i, r in enumerate(catalog)]
    def retrieve(self, repo, query):
        return ["Main.kt"]


def _dataset(tmp_path):
    root = tmp_path / "ds"
    (root / "GEI-1").mkdir(parents=True)
    (root / "GEI-1" / "ticket.json").write_text(json.dumps(
        {"id": "GEI-1", "summary": "audio glitch", "description": "d", "component": "Audio", "logs": []}))
    (root / "GEI-1" / "_oracle").mkdir()
    (root / "GEI-1" / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "alpha", "expected_files": ["Main.kt"]}))     # BOOBY-TRAP: must not be read
    cat = root / "catalog.json"
    cat.write_text(json.dumps([{"name": "alpha"}, {"name": "beta"}]))
    return str(root), str(cat)


def test_run_dataset_writes_oracle_free_records(tmp_path):
    ds, cat = _dataset(tmp_path)
    out = tmp_path / "out"
    issues = MockJira(ds)
    estate = RecordingEstate(MockEstate(cat, str(tmp_path / "work")))
    n = run_dataset(ds, issues=issues, extractor=AndroidSignalExtractor(), estate=estate,
                    index=_StubIndex(), fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                    changes=MockGerrit(str(out / "changes.jsonl"), issues),
                    match_arm="component", out=str(out))
    assert n == 1
    doc = RunRecordIO.read(str(out / "runs" / "GEI-1.json"))
    assert doc.chosen == "alpha" and doc.locations == ["Main.kt"]
    assert doc.materialize.repo == "alpha"                             # outcome for CHOSEN attached
    blob = json.loads((out / "runs" / "GEI-1.json").read_text())
    assert "owning_repo" not in json.dumps(blob)                      # oracle-blind: never leaked
