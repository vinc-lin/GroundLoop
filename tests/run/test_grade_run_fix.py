import json
from pathlib import Path
from groundloop.run.record import RunRecordIO, MaterializeOutcome
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.grade_run import grade_run


def _case(ds, out, cid, present, diff, files, owner, expected, applies):
    cdir = Path(ds) / cid
    cdir.mkdir(parents=True)
    (cdir / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                                  "component": "c", "logs": []}))
    (cdir / "_oracle").mkdir()
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": expected, "required_apis": []}))
    patch = Patch(diff=diff, files=tuple(files))
    rec = RunRecord(ticket_id=cid, ranked=[RepoScore(RepoRef(owner), 0.9)], chosen=RepoRef(owner),
                    locations=list(files), patch=patch, change=Change("g", "s", cid, patch),
                    bound=True, events=[])
    RunRecordIO.write(f"{out}/runs/{cid}.json", rec,
                      materialize=MaterializeOutcome(owner, "/w", present, 3 if present else 0),
                      match_arm="flood", patch_applies=applies)


def test_empty_worktree_is_ungradeable_not_localization(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    # fabricated patch on an EMPTY worktree — the exact 10-case bug
    _case(ds, out, "E", present=False, diff="--- a/system/core/init/init.cpp\n+++ b/..\n",
          files=["system/core/init/init.cpp"], owner="alpha", expected=["Real.kt"], applies=False)
    fix = grade_run(out, ds)["overall"]["fix"]
    assert fix["n_ungradeable_no_source"] == 1
    assert fix["n_gradeable"] == 0
    # the fabricated file must NOT count as a resolution hit anywhere
    assert fix["resolved_rate_strict"]["value"] in (None, 0.0)


def test_present_worktree_is_graded(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    _case(ds, out, "G", present=True, diff="--- a/Real.kt\n+++ b/Real.kt\n@@ -1 +1 @@\n-a\n+b\n",
          files=["Real.kt"], owner="alpha", expected=["Real.kt"], applies=True)
    fix = grade_run(out, ds)["overall"]["fix"]
    assert fix["n_gradeable"] == 1 and fix["n_ungradeable_no_source"] == 0
