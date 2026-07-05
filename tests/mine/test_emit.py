import json
from pathlib import Path  # noqa: F401 (kept for parity with the Case oracle-loading contract below)

from groundloop.mine.emit import emit_case, emit_catalog, MinedCase
from groundloop.adapters.mock.jira import MockJira
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
