"""End-to-end vertical slice using the real AtlasIndex (FTS5 over atlas.db).

Mirrors tests/test_e2e_vertical_slice.py but replaces TokenIndex with
AtlasIndex backed by the hermetic atlas_fixture — proving the port swap is
transparent to core.
"""
import shutil
import json
from pathlib import Path

from groundloop.core.workflow import run_ticket
from groundloop.grade.grader import grade
from groundloop.core.types import Oracle
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.estate import MockEstate
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from tests.fixtures.atlas_fixture import build_atlas_fixture

FIX = Path(__file__).parent / "fixtures" / "android_ivi"


def test_e2e_real_index_matches_localizes_fixes_binds(tmp_path):
    """M0 vertical slice with AtlasIndex instead of TokenIndex.

    The atlas fixture contains android-gpuimage-plus units that match the
    crash log signals (org.wysaid.nativePort.CGEImageHandler, libCGE …).
    Asserts: match android-gpuimage-plus + bind + repo_recall@1 == 1.0.
    """
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(FIX / "gpuimage-352", ds / "GP-352")

    issues = MockJira(str(ds))
    est = MockEstate(str(FIX / "catalog.json"), str(tmp_path / "work"))

    # Build the hermetic atlas.db fixture and wire it to AtlasIndex
    db_path = str(tmp_path / "atlas.db")
    build_atlas_fixture(db_path)
    idx = AtlasIndex(db_path)

    sink = MockGerrit(str(tmp_path / "changes.jsonl"), issues)
    fixer = CannedFixEngine(CannedModel({"default": "patch"}))

    rec = run_ticket(
        "GP-352",
        issues=issues,
        extractor=AndroidSignalExtractor(),
        estate=est,
        index=idx,
        fixer=fixer,
        changes=sink,
    )

    # MATCH: the owning repo won purely from the log signals via FTS5
    assert rec.chosen.name == "android-gpuimage-plus"
    assert rec.events == ["intake", "extract", "match", "materialize", "localize", "fix", "submit", "bind"]

    # BIND: change recorded + ticket transitioned (write-back)
    assert rec.change.change_id.startswith("I")
    assert "Resolved" in (ds / "GP-352" / "ledger.jsonl").read_text()

    # OFFLINE GRADE against the hidden oracle
    oracle_raw = json.loads((ds / "GP-352" / "_oracle" / "oracle.json").read_text())
    oracle = Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                       for k, v in oracle_raw.items()
                       if k in {"owning_repo", "expected_files", "required_apis"}})
    sc = grade(rec, oracle)
    assert sc.repo_recall_at_1 == 1.0 and sc.repo_rank == 1 and sc.bound
