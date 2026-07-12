"""Shared hermetic test fixtures (Type-1 dev-test substrate).

Consolidates the micro-fleet + tiny prebuilt atlas.db + canned-model wiring so tests declare
`harness` / `atlas_harness` / `case` instead of re-wiring the loop by hand. Everything here is
hermetic: no network, no real LLM, no external services (see docs testing-strategy Type-1).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from groundloop.adapters.estate import MockEstate
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.index.simple import TokenIndex
from groundloop.adapters.mock.gerrit import MockGerrit
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.mock.model import CannedModel
from groundloop.core.types import Oracle
from groundloop.core.workflow import RunRecord, run_ticket
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from tests.fixtures.atlas_fixture import build_atlas_fixture

FIXTURES = Path(__file__).parent / "fixtures" / "android_ivi"
_ORACLE_KEYS = {"owning_repo", "expected_files", "required_apis"}


@pytest.fixture(autouse=True)
def _hermetic_dev_mode(monkeypatch):
    """Type-1 suite is dev by definition — arm the dev gate so CLI paths using the fixture doubles
    (--fixer canned / --case / --index) stay reachable. Production (gate off) is asserted in
    tests/run/test_dev_gate.py, which opts out per-test via monkeypatch.delenv."""
    monkeypatch.setenv("KLOOP_DEV", "1")


@dataclass
class Case:
    """A materialized dataset case (writable copy of a fixture case dir + its hidden oracle)."""

    dataset: Path
    case_id: str
    case_dir: Path

    def oracle(self) -> Oracle:
        raw = json.loads((self.case_dir / "_oracle" / "oracle.json").read_text())
        return Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                         for k, v in raw.items() if k in _ORACLE_KEYS})

    def ledger_text(self) -> str:
        p = self.case_dir / "ledger.jsonl"
        return p.read_text() if p.exists() else ""


@dataclass
class Harness:
    """A fully-wired hermetic loop over one case. `run()` executes the deterministic control plane."""

    case: Case
    issues: MockJira
    extractor: AndroidSignalExtractor
    estate: MockEstate
    index: object
    fixer: CannedFixEngine
    changes: MockGerrit

    def run(self) -> RunRecord:
        return run_ticket(self.case.case_id, issues=self.issues, extractor=self.extractor,
                          estate=self.estate, index=self.index, fixer=self.fixer, changes=self.changes)


@pytest.fixture
def fixtures_dir() -> Path:
    """Root of the android_ivi micro-fleet fixtures (catalog.json, index.json, case dirs)."""
    return FIXTURES


@pytest.fixture
def catalog_path() -> Path:
    return FIXTURES / "catalog.json"


@pytest.fixture
def atlas_db(tmp_path) -> str:
    """A tiny real atlas.db (FTS5, no CBM/embedder) over the 4-repo micro-fleet — path as str."""
    return build_atlas_fixture(str(tmp_path / "atlas.db"))


@pytest.fixture
def case(tmp_path) -> Case:
    """The gpuimage-352 case copied into a writable dataset dir (ticket + logs + hidden oracle)."""
    ds = tmp_path / "dataset"
    ds.mkdir()
    case_id = "GP-352"
    shutil.copytree(FIXTURES / "gpuimage-352", ds / case_id)
    return Case(dataset=ds, case_id=case_id, case_dir=ds / case_id)


def _wire(case: Case, tmp_path: Path, index: object) -> Harness:
    issues = MockJira(str(case.dataset))
    estate = MockEstate(str(FIXTURES / "catalog.json"), str(tmp_path / "work"))
    changes = MockGerrit(str(tmp_path / "changes.jsonl"), issues)
    fixer = CannedFixEngine(CannedModel({"default": "patch"}))
    return Harness(case=case, issues=issues, extractor=AndroidSignalExtractor(),
                   estate=estate, index=index, fixer=fixer, changes=changes)


@pytest.fixture
def harness(case, tmp_path) -> Harness:
    """Hermetic loop backed by the TokenIndex membership matcher (the M0 stub index)."""
    return _wire(case, tmp_path, TokenIndex(str(FIXTURES / "index.json")))


@pytest.fixture
def atlas_harness(case, tmp_path, atlas_db) -> Harness:
    """Hermetic loop backed by the real AtlasIndex (FTS5 over the prebuilt atlas.db)."""
    return _wire(case, tmp_path, AtlasIndex(atlas_db))
