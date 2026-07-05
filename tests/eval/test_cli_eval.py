import json
from pathlib import Path
import groundloop.cli as cli
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _seed(root):
    d = Path(root) / "GP-352"
    (d / "logs").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({
        "id": "GP-352", "summary": "crash", "description": "UnsatisfiedLinkError CGEImageHandler",
        "component": "", "logs": [{"path": "logs/c.txt", "kind": "logcat"}]}))
    (d / "logs" / "c.txt").write_text("org.wysaid.nativePort.CGEImageHandler nativeCreateHandler")
    (d / "_oracle").mkdir()
    (d / "_oracle" / "oracle.json").write_text(json.dumps({"owning_repo": "android-gpuimage-plus"}))
    (Path(root) / "catalog.json").write_text(json.dumps(
        [{"name": "android-gpuimage-plus"}, {"name": "organicmaps"},
         {"name": "androidx-media"}, {"name": "cameraview"}]))


def test_gloop_eval_writes_scorecard(tmp_path):
    _seed(tmp_path)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "card.json"
    rc = cli.main(["eval", "--dataset", str(tmp_path), "--catalog", str(tmp_path / "catalog.json"),
                   "--index-db", db, "--out", str(out)])
    assert rc == 0
    card = json.loads(out.read_text())
    assert "arms" in card and "membership+logs" in card["arms"]
    assert (tmp_path / "card.md").is_file()   # markdown twin next to --out
