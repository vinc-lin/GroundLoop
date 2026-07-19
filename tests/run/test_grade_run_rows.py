"""Task 7: per-case grade-run rows now surface the §15 canonical-record fields (predicted/oracle repo,
signals, cost, fixer) in addition to the original 5 keys. Purely additive — block aggregations unchanged."""
import shutil
from pathlib import Path

from groundloop.cli import main
from groundloop.grade.grade_run import grade_run
from groundloop.run.record import RunRecordIO

_FIX = Path(__file__).parent.parent / "fixtures" / "android_ivi"


def _build_gradeable_run(tmp_path):
    """Reuse the test_cli_selfscore recipe: build a one-case dataset from the gpuimage-352 fixture and run
    the loop in batch mode (hermetic TokenIndex + canned fixer) to produce a gradeable run dir."""
    ds = tmp_path / "dataset"
    ds.mkdir()
    shutil.copytree(_FIX / "gpuimage-352", ds / "GP-352")            # carries ticket.json + _oracle
    run_out = tmp_path / "run"
    rc = main(["run", "--dataset", str(ds), "--catalog", str(_FIX / "catalog.json"),
               "--index", str(_FIX / "index.json"), "--work", str(tmp_path / "work"),
               "--changes", str(tmp_path / "changes.jsonl"), "--out", str(run_out), "--fixer", "canned"])
    assert rc == 0
    return str(ds), str(run_out)


def test_case_rows_surface_predicted_oracle_signals_cost_fixer(tmp_path):
    ds, run_out = _build_gradeable_run(tmp_path)
    card = grade_run(run_out, ds)

    cases = card["cases"]
    assert cases, "expected at least one graded case"
    required = {"case_id", "rank", "as_run@1", "isolated@1", "fix",       # the original 5
                "predicted_repo", "oracle_repo", "signals", "cost_usd", "fixer"}
    for row in cases:
        assert required <= set(row), f"missing keys: {required - set(row)}"

    # predicted_repo mirrors the persisted RunDoc.chosen; oracle_repo is the hidden oracle owner.
    doc = RunRecordIO.read(f"{run_out}/runs/GP-352.json")
    gp = next(r for r in cases if r["case_id"] == "GP-352")
    assert gp["predicted_repo"] == doc.chosen
    assert gp["oracle_repo"] == "android-gpuimage-plus"
