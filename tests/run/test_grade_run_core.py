import json
from pathlib import Path
from groundloop.run.record import RunRecordIO, MaterializeOutcome
from groundloop.core.workflow import RunRecord
from groundloop.core.types import RepoScore, RepoRef, Patch, Change
from groundloop.run.grade_run import grade_run


def _write_case(ds_root, out_root, cid, ranked_names, chosen, locations, owning_repo, expected):
    cdir = Path(ds_root) / cid
    (cdir).mkdir(parents=True)
    (cdir / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                                  "component": "c", "logs": []}))
    (cdir / "_oracle").mkdir()
    (cdir / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owning_repo, "expected_files": expected}))
    patch = Patch(diff="", files=())
    rec = RunRecord(ticket_id=cid,
                    ranked=[RepoScore(RepoRef(n), 1.0 - i * 0.1) for i, n in enumerate(ranked_names)],
                    chosen=RepoRef(chosen), locations=locations, patch=patch,
                    change=Change("gl", "s", cid, patch), bound=True, events=[])
    RunRecordIO.write(f"{out_root}/runs/{cid}.json", rec,
                      materialize=MaterializeOutcome(chosen, "", False, 0), match_arm="flood",
                      patch_applies=False)


def test_match_and_localize_as_run(tmp_path):
    ds, out = str(tmp_path / "ds"), str(tmp_path / "out")
    _write_case(ds, out, "A", ["alpha", "beta"], "alpha", ["Main.kt"], "alpha", ["Main.kt"])  # match+loc hit
    _write_case(ds, out, "B", ["beta", "alpha"], "beta", ["Zzz.kt"], "alpha", ["Main.kt"])    # match+loc miss
    card = grade_run(out, ds)
    m = card["overall"]["match"]
    assert m["recall@1"] == 0.5 and m["n"] == 2                        # 1 of 2 -> AUTOMATIC count
    lz = card["overall"]["localize"]
    assert lz["as_run"]["file@1"] == 0.5                              # A hit on chosen, B missed
    assert card["overall"]["counts"]["match_hits@1"] == 1             # explicit tally == recall*n
