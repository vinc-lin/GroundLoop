import shutil
from pathlib import Path
from groundloop.core.workflow import run_ticket
from groundloop.grade.grader import grade
from groundloop.core.types import Oracle
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import MockEstate
from groundloop.adapters.index.simple import TokenIndex
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
import json

FIX = Path(__file__).parent / "fixtures" / "android_ivi"


def test_full_loop_matches_localizes_fixes_binds(tmp_path):
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(FIX / "gpuimage-352", ds / "GP-352")
    issues = MockJira(str(ds))
    est = MockEstate(str(FIX / "catalog.json"), str(tmp_path / "work"))
    idx = TokenIndex(str(FIX / "index.json"))
    sink = MockGerrit(str(tmp_path / "changes.jsonl"), issues)
    fixer = CannedFixEngine(CannedModel({"default": "patch"}))

    rec = run_ticket("GP-352", issues=issues, extractor=AndroidSignalExtractor(),
                     estate=est, index=idx, fixer=fixer, changes=sink)

    # MATCH: the owning repo won purely from the log signals
    assert rec.chosen.name == "android-gpuimage-plus"
    assert rec.events == ["intake", "extract", "match", "materialize", "localize", "fix", "submit", "bind"]
    # BIND: change recorded + ticket transitioned (write-back)
    assert rec.change.change_id.startswith("I")
    assert "Resolved" in (ds / "GP-352" / "ledger.jsonl").read_text()

    # OFFLINE GRADE against the hidden oracle
    oracle = Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                       for k, v in json.loads((ds / "GP-352" / "_oracle" / "oracle.json").read_text()).items()
                       if k in {"owning_repo", "expected_files", "required_apis"}})
    sc = grade(rec, oracle)
    assert sc.repo_recall_at_1 == 1.0 and sc.repo_rank == 1 and sc.bound
