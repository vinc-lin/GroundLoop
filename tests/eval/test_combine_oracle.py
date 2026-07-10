import json
from pathlib import Path

from groundloop.eval.combine_oracle import combine_oracles


def _case(root, cid, owner, *, fault_frame=None):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d"}))
    oracle = {"owning_repo": owner, "is_answerable": True}
    if fault_frame:
        oracle["fault_frame"] = fault_frame
    (d / "_oracle" / "oracle.json").write_text(json.dumps(oracle))


def _dataset(root, repos, cases):
    Path(root).mkdir(parents=True)
    (Path(root) / "catalog.json").write_text(json.dumps([{"name": r} for r in repos]))
    for cid, owner, ff in cases:
        _case(root, cid, owner, fault_frame=ff)


def test_combine_unions_labels_and_copies(tmp_path):
    _dataset(tmp_path / "crash", ["oboe", "newpipe"],
             [("gl-1", "oboe", "a.B.c"), ("gl-2", "newpipe", "d.E.f")])
    _dataset(tmp_path / "func", ["oboe", "organicmaps"], [("fn-1", "organicmaps", None)])
    out = tmp_path / "combined"
    r = combine_oracles([str(tmp_path / "crash"), str(tmp_path / "func")], str(out))
    assert r["cases"] == 3 and r["labeled"] == 3
    names = {c["name"] for c in json.loads((out / "catalog.json").read_text())}
    assert names == {"oboe", "newpipe", "organicmaps"}                       # union, deduped
    assert json.loads((out / "gl-1" / "_oracle" / "oracle.json").read_text())["bug_kind"] == "crash"
    assert json.loads((out / "fn-1" / "_oracle" / "oracle.json").read_text())["bug_kind"] == "functional"
    # sources are NOT mutated (copy, not symlink)
    assert "bug_kind" not in json.loads((tmp_path / "crash" / "gl-1" / "_oracle" / "oracle.json").read_text())


def test_collision_raises(tmp_path):
    _dataset(tmp_path / "a", ["oboe"], [("dup", "oboe", None)])
    _dataset(tmp_path / "b", ["newpipe"], [("dup", "newpipe", None)])
    try:
        combine_oracles([str(tmp_path / "a"), str(tmp_path / "b")], str(tmp_path / "out"))
        assert False, "expected collision error"
    except ValueError as e:
        assert "collision" in str(e)


def test_no_label_skips_bug_kind(tmp_path):
    _dataset(tmp_path / "c", ["oboe"], [("gl-1", "oboe", "a.B.c")])
    out = tmp_path / "out"
    combine_oracles([str(tmp_path / "c")], str(out), label=False)
    assert "bug_kind" not in json.loads((out / "gl-1" / "_oracle" / "oracle.json").read_text())


def test_cli_combine_oracle(tmp_path, capsys):
    import groundloop.cli as cli
    _dataset(tmp_path / "c", ["oboe"], [("gl-1", "oboe", "a.B.c")])
    rc = cli.main(["combine-oracle", "--sources", str(tmp_path / "c"), "--out", str(tmp_path / "out")])
    assert rc == 0 and "1 cases from 1 sources" in capsys.readouterr().out
