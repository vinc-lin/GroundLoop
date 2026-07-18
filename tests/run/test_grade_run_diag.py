import json
from pathlib import Path
from groundloop.run.record import RunRecordIO, MaterializeOutcome
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.grade_run import grade_run
from groundloop.run.report import render_run_markdown


class _FakeAtlas:
    """Stand-in for AtlasIndex: retrieve(repo, query) returns the oracle file only for the oracle repo."""
    def __init__(self, db):
        pass

    def retrieve(self, repo, query):
        return ["Real.kt"] if repo.name == "alpha" else ["Wrong.kt"]


def _case(ds, out, cid, chosen, owner, as_run_loc, expected, bug_kind):
    cdir = Path(ds) / cid
    cdir.mkdir(parents=True)
    (cdir / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                                  "component": "c", "logs": []}))
    (cdir / "_oracle").mkdir()
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": expected, "bug_kind": bug_kind}))
    patch = Patch(diff="", files=())
    rec = RunRecord(ticket_id=cid, ranked=[RepoScore(RepoRef(chosen), 0.9)], chosen=RepoRef(chosen),
                    locations=as_run_loc, patch=patch, change=Change("g", "s", cid, patch),
                    bound=True, events=[])
    RunRecordIO.write(f"{out}/runs/{cid}.json", rec,
                      materialize=MaterializeOutcome(chosen, "", False, 0), match_arm="flood",
                      patch_applies=False)


def test_isolated_localize_differs_from_as_run(tmp_path, monkeypatch):
    import groundloop.run.grade_run as gr
    monkeypatch.setattr(gr, "AtlasIndex", _FakeAtlas)
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    # match MISSED (chosen=beta != owner=alpha): as-run localize runs on beta -> "Wrong.kt" (miss),
    # but the isolated diagnostic runs on the oracle repo alpha -> "Real.kt" (hit)
    _case(ds, out, "M", chosen="beta", owner="alpha", as_run_loc=["Wrong.kt"], expected=["Real.kt"],
          bug_kind="functional")
    card = grade_run(out, ds, index_db="atlas.db")
    assert card["overall"]["localize"]["as_run"]["file@1"] == 0.0     # contaminated by match miss
    assert card["overall"]["localize"]["isolated"]["file@1"] == 1.0   # the "7/10 not 0/10" correction
    assert card["overall"]["localize"]["isolated_arm"] == "atlas"      # honest arm attribution (no manifest)
    assert "functional" in card["by_bug_kind"]
    md = render_run_markdown(card)
    assert "| M |" in md and "isolated" in md.lower()


def test_isolated_none_without_index(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    _case(ds, out, "M", chosen="alpha", owner="alpha", as_run_loc=["Real.kt"], expected=["Real.kt"],
          bug_kind="crash")
    card = grade_run(out, ds)                                          # no index_db -> isolated stays None
    assert card["overall"]["localize"]["isolated"] is None
    assert render_run_markdown(card)                                  # renders without crashing


def test_bind_defaults_to_mock_without_manifest(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    _case(ds, out, "M", chosen="alpha", owner="alpha", as_run_loc=["Real.kt"], expected=["Real.kt"],
          bug_kind="crash")
    card = grade_run(out, ds)                                          # no manifest.json written by _case
    assert card["bind"] == "mock"                                      # honest default, not silently omitted
    assert "bind: mock" in render_run_markdown(card)
