from pathlib import Path
from groundloop.core.types import RepoRef
from groundloop.adapters.estate import MockEstate, RecordingEstate, CheckoutEstate


def _catalog(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text('[{"name": "alpha"}, {"name": "beta"}]')
    return str(p)


def test_recording_estate_records_empty_vs_present(tmp_path):
    inner = MockEstate(_catalog(tmp_path), str(tmp_path / "work"))      # materialize -> empty dir
    est = RecordingEstate(inner)
    assert [r.name for r in est.catalog()] == ["alpha", "beta"]         # delegates
    wt = est.materialize(RepoRef("alpha"))
    out = est.outcome_for("alpha")
    assert out.repo == "alpha" and out.path == wt.path
    assert out.present is False and out.n_files == 0                    # empty work dir


def test_checkout_estate_materializes_snapshot(tmp_path):
    snap = tmp_path / "repos" / "alpha"
    snap.mkdir(parents=True)
    (snap / "Main.kt").write_text("class Main")
    est = RecordingEstate(CheckoutEstate(_catalog(tmp_path), str(tmp_path / "repos"),
                                         str(tmp_path / "work")))
    assert [r.name for r in est.catalog()] == ["alpha", "beta"]
    wt = est.materialize(RepoRef("alpha"))
    assert (Path(wt.path) / "Main.kt").is_file()                       # real source checked out
    assert est.outcome_for("alpha").present is True
    est.materialize(RepoRef("beta"))                                   # no snapshot -> empty
    assert est.outcome_for("beta").present is False
