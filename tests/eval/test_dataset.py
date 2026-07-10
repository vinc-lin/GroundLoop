import json
from pathlib import Path

from groundloop.eval.dataset import load_cases, load_oracle, CaseRef
from groundloop.core.types import Oracle


def _mk_case(root, cid, owner):
    d = Path(root) / cid
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps(
        {"id": cid, "summary": "s", "description": "d", "component": "", "logs": []}))
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": ["a/b.java"], "required_apis": ["f"],
         "owning_repo_sha": "deadbeef", "is_answerable": True}))


def test_load_cases_finds_case_dirs(tmp_path):
    _mk_case(tmp_path, "GP-1", "gpuimage")
    _mk_case(tmp_path, "ND-2", "newpipe")
    (tmp_path / "catalog.json").write_text("[]")   # not a case dir
    cases = load_cases(str(tmp_path))
    assert {c.case_id for c in cases} == {"GP-1", "ND-2"}
    assert all(isinstance(c, CaseRef) for c in cases)


def test_load_oracle_reads_hidden_oracle_and_drops_extra_keys(tmp_path):
    _mk_case(tmp_path, "GP-1", "gpuimage")
    (case,) = [c for c in load_cases(str(tmp_path)) if c.case_id == "GP-1"]
    oracle = load_oracle(case)
    assert isinstance(oracle, Oracle)
    assert oracle.owning_repo == "gpuimage"
    assert oracle.expected_files == ("a/b.java",)     # list -> tuple
    assert oracle.required_apis == ("f",)
    # extra keys (owning_repo_sha, is_answerable) dropped, no crash


def test_load_cases_does_not_read_oracle(tmp_path, monkeypatch):
    _mk_case(tmp_path, "GP-1", "gpuimage")
    import pathlib
    reads = []
    orig = pathlib.Path.read_text

    def spy(self, *a, **k):
        reads.append(str(self))
        return orig(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", spy)
    load_cases(str(tmp_path))
    assert not any("_oracle" in r for r in reads), f"load_cases read the oracle: {reads}"


def test_eval_oracle_reads_bug_kind(tmp_path):
    import json
    from groundloop.eval.dataset import CaseRef, load_eval_oracle
    d = tmp_path / "c1"
    (d / "_oracle").mkdir(parents=True)
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": "oboe", "is_answerable": True, "bug_kind": "functional"}))
    o = load_eval_oracle(CaseRef(case_id="c1", case_dir=str(d)))
    assert o.bug_kind == "functional"


def test_eval_oracle_bug_kind_defaults_none(tmp_path):
    import json
    from groundloop.eval.dataset import CaseRef, load_eval_oracle
    d = tmp_path / "c2"
    (d / "_oracle").mkdir(parents=True)
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "oboe"}))
    assert load_eval_oracle(CaseRef(case_id="c2", case_dir=str(d))).bug_kind is None
