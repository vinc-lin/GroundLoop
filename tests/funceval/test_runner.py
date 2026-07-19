import json
from pathlib import Path

from tests.fixtures.atlas_fixture import build_atlas_fixture

from groundloop.adapters.index.labs.text_profile import build_text_profiles
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.funceval.runner import run_funceval


def _func_case(root, cid, owner, summary, files):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": summary, "description": summary}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "expected_files": files, "is_answerable": True, "bug_kind": "functional"}))


def test_run_funceval_reports_by_bug_kind(tmp_path):
    ds = tmp_path / "ds"
    _func_case(ds, "f1", "organicmaps", "offline maps navigation route missing", ["x.java"])
    (ds / "catalog.json").write_text(json.dumps([{"name": "organicmaps"}, {"name": "android-gpuimage-plus"}]))
    prof = build_text_profiles({"organicmaps": ["offline maps navigation route"],
                                "android-gpuimage-plus": ["gpu image filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    card = run_funceval(str(ds), prof, atlas, embedder=StubEmbedder(dim=16),
                        arms=("functional", "dispatch"))
    assert {"functional", "dispatch"} <= set(card["attribution"]["arms"])
    bbk = card["attribution"]["arms"]["functional"]["by_bug_kind"]
    assert bbk["functional"]["forced"]["recall@1"]["value"] == 1.0
