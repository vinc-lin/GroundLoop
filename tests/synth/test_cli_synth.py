"""`gloop synth` composition-root wrapper over build_synth_dataset — hermetic (no network/LLM).

Seeds a tiny mined-shaped dataset (ticket.json + _oracle/oracle.json + catalog.json) over the
fixture atlas, runs the CLI, and asserts the synth dataset (catalog + per-case synth crash log)
lands on disk with the expected per-kind summary."""
import json
from pathlib import Path

import groundloop.cli as cli
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _seed_mined(root: Path):
    """A 2-case mined-shaped dataset: one native owner (gpuimage) + one java owner (cameraview)."""
    cases = {
        "gl-nat01": ("android-gpuimage-plus",
                     ["library/src/main/jni/cge/CGEImageHandler.cpp"]),
        "gl-jav01": ("cameraview",
                     ["cameraview/src/main/java/com/otaliastudios/cameraview/CameraView.java"]),
    }
    for cid, (owner, files) in cases.items():
        d = root / cid
        (d / "_oracle").mkdir(parents=True)
        (d / "ticket.json").write_text(json.dumps(
            {"id": cid, "summary": "app crash", "description": "user prose, no failure signal"}))
        (d / "_oracle" / "oracle.json").write_text(json.dumps(
            {"owning_repo": owner, "expected_files": files}))
    (root / "catalog.json").write_text(json.dumps(
        [{"name": "android-gpuimage-plus"}, {"name": "cameraview"},
         {"name": "organicmaps"}, {"name": "androidx-media"}]))


def test_gloop_synth_writes_dataset(tmp_path, capsys):
    src = tmp_path / "mined"
    _seed_mined(src)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "synth"

    rc = cli.main(["synth", "--src", str(src), "--atlas-db", db, "--out", str(out)])
    assert rc == 0

    # catalog carried through verbatim (names from <src>/catalog.json)
    assert (out / "catalog.json").is_file()
    names = {c["name"] for c in json.loads((out / "catalog.json").read_text())}
    assert names == {"android-gpuimage-plus", "cameraview", "organicmaps", "androidx-media"}

    # each positive case got a synthesized failure log the loop can read
    assert (out / "gl-nat01" / "logs" / "crash.txt").is_file()
    assert (out / "gl-jav01" / "logs" / "crash.txt").is_file()
    # the transformed ticket points at the synth log
    tk = json.loads((out / "gl-nat01" / "ticket.json").read_text())
    assert tk["logs"] == [{"path": "logs/crash.txt", "kind": "native"}]

    printed = capsys.readouterr().out
    assert "synth: 2 cases ->" in printed
    assert str(out) in printed
    assert "native: 1" in printed    # gpuimage -> native backtrace
    assert "logcat: 1" in printed    # cameraview -> java logcat


def test_gloop_synth_explicit_catalog_path(tmp_path):
    src = tmp_path / "mined"
    _seed_mined(src)
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "synth"
    # a separate catalog file (subset) resolves catalog_names when --catalog is given
    cat = tmp_path / "sub-catalog.json"
    cat.write_text(json.dumps([{"name": "android-gpuimage-plus"}, {"name": "cameraview"}]))

    rc = cli.main(["synth", "--src", str(src), "--atlas-db", db, "--out", str(out),
                   "--catalog", str(cat)])
    assert rc == 0
    names = {c["name"] for c in json.loads((out / "catalog.json").read_text())}
    assert names == {"android-gpuimage-plus", "cameraview"}


def test_synth_help_lists_flags():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "groundloop.cli", "synth", "--help"],
                         capture_output=True, text=True)
    for flag in ("--src", "--atlas-db", "--out", "--catalog"):
        assert flag in out.stdout
