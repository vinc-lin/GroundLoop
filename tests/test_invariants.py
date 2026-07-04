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
