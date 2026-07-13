"""Anti-leak invariant tests (testing-strategy §2.3).

Each test encodes a constraint that, if violated, silently corrupts the evaluation. They are
regression guards: the GroundLoop design already honors them, so these MUST stay green — a failure
here means a real leak was reintroduced (e.g. the owning repo bleeding into ticket-visible fields).
"""
from __future__ import annotations

import pathlib

import pytest

_EVENTS = ["intake", "extract", "match", "materialize", "localize", "fix", "submit", "bind"]
# The loop must never READ these: anything inside an `_oracle/` dir, or a bind-output ledger file.
_ORACLE_DIR = "_oracle"
_BIND_FILES = {"oracle.json", "binding.jsonl", "changes.jsonl", "ledger.jsonl"}


# Invariant 1 — the ticket the loop actually reads never names the owning repo.
def test_ticket_does_not_name_owning_repo(harness):
    ticket = harness.issues.fetch(harness.case.case_id)
    repo = harness.case.oracle().owning_repo
    assert ticket.component != repo, "owning repo leaked into ticket.component"
    visible = " ".join([ticket.component, ticket.summary, ticket.description,
                        *[c.content for c in ticket.logs],
                        *[str(c) for c in ticket.comments]])
    assert repo not in visible, "owning repo leaked into a loop-visible ticket field"


# Invariant 2 — owning_repo lives only in the hidden oracle, never in loop-visible case files.
def test_owning_repo_only_in_oracle(case):
    repo = case.oracle().owning_repo
    ticket_txt = (case.case_dir / "ticket.json").read_text()
    logs_txt = "\n".join(p.read_text() for p in (case.case_dir / "logs").glob("*"))
    assert repo not in ticket_txt, "owning repo leaked into ticket.json"
    assert repo not in logs_txt, "owning repo leaked into the logs"
    assert repo in (case.case_dir / "_oracle" / "oracle.json").read_text(), "oracle must hold owning_repo"


# Invariant 4 — the loop never READS the oracle or any bind-output ledger.
def test_loop_never_reads_oracle_or_bindings(harness, monkeypatch):
    reads: list[str] = []
    orig = pathlib.Path.read_text

    def spy(self, *a, **k):
        reads.append(str(self))
        return orig(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", spy)
    harness.run()
    assert reads, "expected the loop to read at least the ticket"
    leaked = [p for p in reads
              if _ORACLE_DIR in pathlib.Path(p).parts or pathlib.Path(p).name in _BIND_FILES]
    assert not leaked, f"loop read oracle/bind-output files: {leaked}"


# Invariant 5 — the matcher's inputs (extracted signals) do not encode the answer; the catalog is a
# genuine N-way choice with the owner as just one candidate among hard negatives (FR-3).
def test_signals_do_not_encode_owning_repo(harness):
    ticket = harness.issues.fetch(harness.case.case_id)
    signals = harness.extractor.extract(ticket.logs, ticket)
    repo = harness.case.oracle().owning_repo
    assert repo not in signals.tokens(), "owning repo appeared as a matcher signal token"
    for field in (signals.packages, signals.classes, signals.methods,
                  signals.symbols, signals.libraries, signals.errors):
        assert repo not in field, "owning repo leaked into an extracted signal field"
    names = [r.name for r in harness.estate.catalog()]
    assert repo in names, "owner must be a candidate in the catalog"
    assert len(names) >= 3, "catalog must offer a real N-way choice (not a singleton)"


# Invariant 6 — control flow is deterministic: same inputs → identical sequence, choice, and Change-Id.
def test_control_flow_is_deterministic(harness):
    r1 = harness.run()
    r2 = harness.run()
    assert r1.events == r2.events == _EVENTS
    assert r1.chosen == r2.chosen
    assert r1.change.change_id == r2.change.change_id
    assert [rs.repo.name for rs in r1.ranked] == [rs.repo.name for rs in r2.ranked]


# Invariant 3 (weak form) — materialize() provisions an isolated throwaway work-tree, not a shared or
# source checkout. The full "@base = fix^ with fix + later history scrubbed, fix-added tests excluded"
# invariant lands with the real RepoEstate (Type-2), which MockEstate does not yet implement.
def test_materialize_yields_isolated_worktree(harness, tmp_path):
    wt = harness.estate.materialize(harness.estate.catalog()[0])
    assert pathlib.Path(wt.path).is_dir()
    assert str(tmp_path) in wt.path, "work-tree must be isolated under the throwaway work root"


@pytest.mark.skip(reason="@base=fix^ history-scrub invariant lands with the real RepoEstate (Type-2), "
                         "not MockEstate")
def test_base_is_fix_parent_with_history_scrubbed():
    """Pending Type-2: real RepoEstate must materialize @base = fix^ with the fix and all later
    history removed and fix-added tests excluded, so the loop cannot see the answer in git history."""


# Invariant 7 (self-scoring) — the persisted run-record is oracle-free; a booby-trapped oracle never
# bleeds into <out>/runs/<case>.json. The batch loop reads only loop-visible fields.
def test_run_record_has_no_oracle_fields(tmp_path):
    import json

    from groundloop.adapters.estate import MockEstate, RecordingEstate
    from groundloop.adapters.fix.canned import CannedFixEngine
    from groundloop.adapters.mock.gerrit import MockGerrit
    from groundloop.adapters.mock.jira import MockJira
    from groundloop.adapters.mock.model import CannedModel
    from groundloop.core.types import RepoScore
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
    from groundloop.run.batch import run_dataset

    class _Stub:
        def rank_repos(self, signals, catalog):
            return [RepoScore(r, 1.0 - i) for i, r in enumerate(catalog)]

        def retrieve(self, repo, query):
            return ["Main.kt"]

    (tmp_path / "ds" / "GEI-1").mkdir(parents=True)
    (tmp_path / "ds" / "GEI-1" / "ticket.json").write_text(json.dumps(
        {"id": "GEI-1", "summary": "glitch", "description": "d", "component": "Audio", "logs": []}))
    (tmp_path / "ds" / "GEI-1" / "_oracle").mkdir()
    (tmp_path / "ds" / "GEI-1" / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "SECRETOWNER", "expected_files": ["Main.kt"], "required_apis": ["secretApi"]}))
    (tmp_path / "ds" / "catalog.json").write_text(json.dumps([{"name": "alpha"}, {"name": "beta"}]))
    issues = MockJira(str(tmp_path / "ds"))
    run_dataset(str(tmp_path / "ds"), issues=issues, extractor=AndroidSignalExtractor(),
                estate=RecordingEstate(MockEstate(str(tmp_path / "ds" / "catalog.json"),
                                                  str(tmp_path / "work"))),
                index=_Stub(), fixer=CannedFixEngine(CannedModel({"default": "patch"})),
                changes=MockGerrit(str(tmp_path / "out" / "changes.jsonl"), issues),
                match_arm="flood", out=str(tmp_path / "out"))
    blob = (tmp_path / "out" / "runs" / "GEI-1.json").read_text()
    for leaked in ("SECRETOWNER", "secretApi", "owning_repo", "expected_files", "required_apis"):
        assert leaked not in blob, f"oracle field {leaked!r} leaked into the run-record"


# Invariant 8 (self-scoring) — the batch run loop is oracle-blind; grade_run is the SOLE oracle reader.
def test_selfscore_grader_is_sole_oracle_reader():
    import groundloop
    root = pathlib.Path(groundloop.__file__).parent
    batch = (root / "run" / "batch.py").read_text()
    assert "load_eval_oracle" not in batch and "load_oracle" not in batch, \
        "the batch run loop must be oracle-blind (no oracle-read API)"
    grade = (root / "run" / "grade_run.py").read_text()
    assert "load_eval_oracle" in grade, "grade_run must be the sole oracle reader"


# Invariant 9 (anti-leak) — the production PlanningFixEngine re-gates its EXECUTED diff, not just the
# plan: a diff touching a file outside the localize candidate set must abstain (empty Patch), so a fix
# can never write outside the scope the loop was given.
def test_planning_fixer_abstains_on_out_of_scope_diff(tmp_path):
    from groundloop.adapters.fix.planning import PlanningFixEngine
    from groundloop.core.types import RepoRef, Ticket, WorkTree

    class _Seq:                                   # scripted model: replies in order, last repeats
        def __init__(self, replies):
            self._r, self.i = list(replies), 0

        def complete(self, prompt):
            r = self._r[self.i]
            self.i = min(self.i + 1, len(self._r) - 1)
            return r

    (tmp_path / "in_scope.py").write_text("def fix_me():\n    return 1\n")
    plan_json = ('{"root_cause":"npe","targets":[{"file":"in_scope.py","symbol":"fix_me"}],'
                 '"required_apis":[],"strategy":"guard","citations":["in_scope.py"]}')
    out_of_scope_diff = ("```diff\n--- a/other/secret.py\n+++ b/other/secret.py\n@@ -1 +1 @@\n"
                         "-x = 1\n+x = 2\n```")
    eng = PlanningFixEngine(_Seq([plan_json, out_of_scope_diff]))
    wt = WorkTree(repo=RepoRef(name="r"), path=str(tmp_path))
    _plan, patch, meta = eng.propose_with_plan(wt, Ticket(id="c1", summary="s", description="d"),
                                               ["in_scope.py"])
    assert patch.diff == "", "executed diff left the candidate set but was not abstained (anti-leak)"
    assert meta.get("abstain_reason") == "diff_out_of_scope"


# Bridge to Type-2 — the invariants hold over the REAL FTS5 matcher too, and it beats the 1/N guess
# baseline (fleet-integrity backstop, §3.4): a matcher that guessed would not rank the owner first.
def test_atlas_matcher_honors_invariants(atlas_harness):
    r1 = atlas_harness.run()
    r2 = atlas_harness.run()
    repo = atlas_harness.case.oracle().owning_repo
    assert r1.chosen.name == repo, "real AtlasIndex must match the owning repo from log signals alone"
    assert r1.events == r2.events == _EVENTS and r1.chosen == r2.chosen, "must be deterministic"
    n = len(atlas_harness.estate.catalog())
    assert r1.ranked[0].score > 0 and n >= 3, "owner must win on evidence over an N-way field, not a guess"
