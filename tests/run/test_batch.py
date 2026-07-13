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


class _FakeCost:
    """Stub GatewayModel-shaped cost handle: the batch driver snapshots these four attrs per case."""
    def __init__(self):
        self.cost_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0


class _BumpExtractor:
    """Inner extractor that also bumps the cost handle on extract() — simulates model spend during the
    loop so the per-case delta the driver records is deterministically non-zero."""
    def __init__(self, inner, cost):
        self.inner = inner
        self.cost = cost

    def extract(self, logs, ticket):
        self.cost.cost_usd += 0.5
        self.cost.input_tokens += 100
        self.cost.output_tokens += 20
        self.cost.calls += 1
        return self.inner.extract(logs, ticket)


def test_run_dataset_persists_signals_cost_and_fixer(tmp_path):
    from groundloop.adapters.extractor_recording import RecordingExtractor

    ds, cat = _dataset(tmp_path)
    out = tmp_path / "out"
    issues = MockJira(ds)
    estate = RecordingEstate(MockEstate(cat, str(tmp_path / "work")))
    cost = _FakeCost()
    extractor = RecordingExtractor(_BumpExtractor(AndroidSignalExtractor(), cost))
    run_dataset(ds, issues=issues, extractor=extractor, estate=estate,
                index=_StubIndex(), fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                changes=MockGerrit(str(out / "changes.jsonl"), issues),
                match_arm="component", out=str(out),
                extractor_rec=extractor, cost_model=cost, fixer_kind="canned")
    doc = RunRecordIO.read(str(out / "runs" / "GEI-1.json"))
    assert isinstance(doc.signals, dict) and doc.signals != {}         # extractor signals captured
    assert "packages" in doc.signals
    assert isinstance(doc.cost_usd, float) and doc.cost_usd == 0.5     # per-case delta of the bump
    assert isinstance(doc.tokens, dict) and doc.tokens == {"input": 100, "output": 20}
    assert isinstance(doc.model_calls, int) and doc.model_calls == 1
    assert doc.fixer == "canned"


def _dataset_2case(tmp_path):
    """Two cases (GEI-1, GEI-2) sharing a catalog — needed to catch a cumulative-vs-delta cost
    regression (a single-case dataset can't: case 1's delta always equals its cumulative)."""
    root = tmp_path / "ds2"
    for cid in ("GEI-1", "GEI-2"):
        (root / cid).mkdir(parents=True)
        (root / cid / "ticket.json").write_text(json.dumps(
            {"id": cid, "summary": "audio glitch", "description": "d", "component": "Audio", "logs": []}))
        (root / cid / "_oracle").mkdir()
        (root / cid / "_oracle" / "oracle.json").write_text(json.dumps(
            {"owning_repo": "alpha", "expected_files": ["Main.kt"]}))
    cat = root / "catalog.json"
    cat.write_text(json.dumps([{"name": "alpha"}, {"name": "beta"}]))
    return str(root), str(cat)


def test_run_dataset_records_per_case_cost_delta_not_cumulative(tmp_path):
    """Each run-record must carry only ITS OWN cost bump, not the running total: with a cost model
    that adds 0.5 on every run_ticket, BOTH cases must record 0.5 (case 2 must NOT read 1.0)."""
    from groundloop.adapters.extractor_recording import RecordingExtractor

    ds, cat = _dataset_2case(tmp_path)
    out = tmp_path / "out"
    issues = MockJira(ds)
    estate = RecordingEstate(MockEstate(cat, str(tmp_path / "work")))
    cost = _FakeCost()
    extractor = RecordingExtractor(_BumpExtractor(AndroidSignalExtractor(), cost))
    n = run_dataset(ds, issues=issues, extractor=extractor, estate=estate,
                    index=_StubIndex(), fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                    changes=MockGerrit(str(out / "changes.jsonl"), issues),
                    match_arm="component", out=str(out),
                    extractor_rec=extractor, cost_model=cost, fixer_kind="canned")
    assert n == 2
    d1 = RunRecordIO.read(str(out / "runs" / "GEI-1.json"))
    d2 = RunRecordIO.read(str(out / "runs" / "GEI-2.json"))
    assert d1.cost_usd == 0.5                                          # first case: own bump
    assert d2.cost_usd == 0.5                                          # second case: delta, NOT 1.0 cumulative
    assert d1.tokens == {"input": 100, "output": 20}
    assert d2.tokens == {"input": 100, "output": 20}
    assert d1.model_calls == 1 and d2.model_calls == 1


def test_run_dataset_cost_zero_without_cost_model(tmp_path):
    """Canned/no-cost-model path: cost keys are present but zero (never None)."""
    from groundloop.adapters.extractor_recording import RecordingExtractor

    ds, cat = _dataset(tmp_path)
    out = tmp_path / "out"
    issues = MockJira(ds)
    estate = RecordingEstate(MockEstate(cat, str(tmp_path / "work")))
    extractor = RecordingExtractor(AndroidSignalExtractor())
    run_dataset(ds, issues=issues, extractor=extractor, estate=estate,
                index=_StubIndex(), fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                changes=MockGerrit(str(out / "changes.jsonl"), issues),
                match_arm="component", out=str(out),
                extractor_rec=extractor, cost_model=None, fixer_kind="canned")
    doc = RunRecordIO.read(str(out / "runs" / "GEI-1.json"))
    assert doc.cost_usd == 0.0 and doc.tokens == {"input": 0, "output": 0}
    assert doc.model_calls == 0 and doc.fixer == "canned"
    assert isinstance(doc.signals, dict)                               # still captured


def test_read_back_compat_on_old_record(tmp_path):
    """OLD run-records (written before signals/cost/fixer) must still load via .get() defaults."""
    p = tmp_path / "runs" / "OLD-1.json"
    p.parent.mkdir(parents=True)
    old = {
        "ticket_id": "OLD-1", "match_arm": "flood", "ranked": [], "chosen": "alpha",
        "locations": [], "patch": {"diff": "", "files": []}, "patch_applies": False,
        "change_id": "gl-0", "bound": False, "events": [],
        "materialize": {"repo": "alpha", "path": "", "present": False, "n_files": 0},
    }
    p.write_text(json.dumps(old))
    doc = RunRecordIO.read(str(p))
    assert doc.signals == {} and doc.cost_usd == 0.0 and doc.tokens == {}
    assert doc.model_calls == 0 and doc.fixer == ""
