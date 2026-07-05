import json
from pathlib import Path  # noqa: F401 (kept for parity with the Case oracle-loading contract below)

from groundloop.mine.emit import emit_case, emit_catalog, MinedCase
from groundloop.adapters.mock.jira import MockJira
from groundloop.eval.dataset import CaseRef, load_eval_oracle, case_catalog
import tests.conftest as conftest  # noqa: F401 (for the Case oracle-loading contract)


def _case():
    return MinedCase(
        case_id="ND-100", summary="Crash on search", description="It crashes.",
        logs=[{"kind": "stacktrace", "text": "java.lang.NullPointerException\n  at a.b.c()"}],
        owning_repo="newpipe", expected_files=["app/src/main/java/org/schabi/newpipe/Foo.java"],
        required_apis=["doSearch"], owning_repo_sha="deadbeef", is_answerable=True,
        provenance={"issue": {"number": 100}}, leakage={"leakage_flags": {}, "scrubber_version": "1.0.0"},
        raw={"issue": {"n": 1}, "pr_files": []},
    )


def test_emit_case_writes_loadable_layout(tmp_path):
    emit_case(str(tmp_path), _case())
    d = tmp_path / "ND-100"
    # loop-visible
    assert (d / "ticket.json").is_file()
    t = json.loads((d / "ticket.json").read_text())
    assert t["id"] == "ND-100" and t["component"] == "" and isinstance(t["comments"], list)
    assert t["logs"][0]["path"].startswith("logs/")
    assert (d / t["logs"][0]["path"]).is_file()
    # hidden, nested under _oracle/
    assert (d / "_oracle" / "oracle.json").is_file()
    assert (d / "_oracle" / "provenance.json").is_file()
    assert (d / "_oracle" / "leakage.json").is_file()
    assert (d / "_oracle" / "raw" / "issue.json").is_file()


def test_emitted_ticket_loads_via_mockjira(tmp_path):
    emit_case(str(tmp_path), _case())
    ticket = MockJira(str(tmp_path)).fetch("ND-100")
    assert ticket.id == "ND-100"
    assert ticket.component == ""
    assert ticket.logs[0].content.startswith("java.lang.NullPointerException")


def test_oracle_roundtrips_and_drops_extra_keys(tmp_path):
    emit_case(str(tmp_path), _case())
    raw = json.loads((tmp_path / "ND-100" / "_oracle" / "oracle.json").read_text())
    assert raw["owning_repo"] == "newpipe"
    assert isinstance(raw["expected_files"], list)     # array, not string
    assert raw["owning_repo_sha"] == "deadbeef"        # extra key present on disk...
    from groundloop.core.types import Oracle
    _ORACLE_KEYS = {"owning_repo", "expected_files", "required_apis"}
    oracle = Oracle(**{k: (tuple(v) if isinstance(v, list) else v)
                       for k, v in raw.items() if k in _ORACLE_KEYS})   # ...dropped by the loader
    assert oracle.owning_repo == "newpipe"
    assert oracle.expected_files == ("app/src/main/java/org/schabi/newpipe/Foo.java",)


def test_emit_catalog_writes_name_array(tmp_path):
    emit_catalog(str(tmp_path), ["newpipe", "osmand", "media3"])
    cat = json.loads((tmp_path / "catalog.json").read_text())
    assert cat == [{"name": "newpipe"}, {"name": "osmand"}, {"name": "media3"}]


def _neg(**kw):
    base = dict(case_id="gl-abc123def456", summary="s", description="d", logs=[],
                owning_repo="cameraview", expected_files=[], required_apis=[])
    base.update(kw)
    return MinedCase(**base)


def test_emit_oracle_carries_negative_fields(tmp_path):
    d = emit_case(str(tmp_path), _neg(is_answerable=False, negative_class="out_of_fleet",
                                      held_out_repo="cameraview", case_catalog=["organicmaps", "media3"]))
    o = json.loads((Path(d) / "_oracle" / "oracle.json").read_text())
    assert o["is_answerable"] is False and o["negative_class"] == "out_of_fleet" and o["held_out_repo"] == "cameraview"


def test_emit_holdout_writes_percase_catalog_excluding_owner(tmp_path):
    d = emit_case(str(tmp_path), _neg(is_answerable=False, negative_class="out_of_fleet",
                                      held_out_repo="cameraview", case_catalog=["organicmaps", "media3"]))
    ref = CaseRef(case_id=Path(d).name, case_dir=d)
    ev = load_eval_oracle(ref)
    assert ev.is_answerable is False and ev.negative_class == "out_of_fleet"
    names = [r.name for r in case_catalog(ref)]
    assert "cameraview" not in names and len(names) >= 2      # proves emit⇄SP1a-reader contract


def test_positive_emits_unchanged(tmp_path):
    d = emit_case(str(tmp_path), _neg())                       # defaults: positive
    assert not (Path(d) / "catalog.json").is_file()
    o = json.loads((Path(d) / "_oracle" / "oracle.json").read_text())
    assert o["negative_class"] is None and o["is_answerable"] is True
    assert case_catalog(CaseRef(case_id=Path(d).name, case_dir=d)) is None


def test_emit_rejects_unknown_negative_class(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        emit_case(str(tmp_path), _neg(negative_class="typo"))


def test_emit_rejects_owner_in_percase_catalog(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        emit_case(str(tmp_path), _neg(negative_class="out_of_fleet", held_out_repo="cameraview",
                                      case_catalog=["cameraview", "media3"]))
