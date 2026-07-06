"""`gloop kb-ab` composition-root wrapper over run_ab + strengthened_accept — hermetic (no network/LLM).

Monkeypatches groundloop.kb.ab._make_fixer to a scripted CannedModel (emits GOLD only when the KB
preamble fired, "" otherwise), builds a tiny synth-shaped dataset + the fix atlas fixture, keeps the
embedder path UNSET (so the CLI passes embedder=None, the hermetic predicate-only select), runs the CLI,
and asserts the 3 arm scorecards + verdict.json (with BOTH kb_vs_placebo/kb_vs_none verdicts) land on
disk. NOT a real-lift claim (that is the Type-2 gated measurement)."""
import json
import shutil
from pathlib import Path

import groundloop.cli as cli
from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.mock.model import CannedModel
from groundloop.kb import ab
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [{"name": n} for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
GOLD = ("```diff\n"
        "--- a/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "+++ b/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
        "@@ -1,4 +1,4 @@\n"
        "-// bug\n"
        "+// fixed nativeCreateHandler\n"
        ' #include "cgeImageHandler.h"\n'
        " namespace CGE {\n"
        " jlong nativeCreateHandler(JNIEnv*, jclass) {\n"
        "```")


def test_gloop_kb_ab_writes_scorecards_and_verdict(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)   # keep the embedder UNSET (hermetic path)

    def _fx():
        return ModelPatchEngine(CannedModel({"# Applicable playbooks": GOLD, "default": ""}))
    monkeypatch.setattr(ab, "_make_fixer", _fx)

    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(CATALOG))
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    out = tmp_path / "out"

    rc = cli.main(["kb-ab", "--dataset", str(ds), "--catalog", str(catalog_path),
                   "--index-db", db, "--repos", str(FIX / "repos"), "--out", str(out)])
    assert rc == 0

    # all three arm scorecards land on disk
    for arm in ("none", "kb", "placebo"):
        assert (out / f"scorecard-{arm}.json").is_file()

    # verdict.json carries the eval arm + BOTH strengthened_accept verdicts
    verdict = json.loads((out / "verdict.json").read_text())
    assert verdict["eval_arm"] == "membership+logs"
    assert set(verdict) >= {"eval_arm", "kb_vs_placebo", "kb_vs_none"}
    for key in ("kb_vs_placebo", "kb_vs_none"):
        assert "accepted" in verdict[key]
        assert "reasons" in verdict[key]

    # the CLI prints an ACCEPT/REJECT decision + reasons for the primary (kb_vs_placebo) verdict
    printed = capsys.readouterr().out
    assert ("ACCEPT" in printed) or ("REJECT" in printed)


def test_kb_ab_help_lists_flags():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "groundloop.cli", "kb-ab", "--help"],
                         capture_output=True, text=True)
    for flag in ("--dataset", "--catalog", "--index-db", "--repos", "--out",
                 "--eval-arm", "--cost-budget"):
        assert flag in out.stdout
