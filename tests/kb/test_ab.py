"""Hermetic A/B: run_ab returns the 3 KB arms {none, kb, placebo} and the kb arm RESOLVES the native
positive (GP-352) that the none arm abstains on — proving the KB injection flows through the per-arm
orchestration (FixEvalRunner + grade_fix_all reused once per arm). A scripted CannedModel emits the GOLD
diff ONLY when a '# Applicable playbooks' preamble is present (mirrors tests/fixeval/test_skill_effect.py).
NOT a real-lift claim (that is the Type-2 gated measurement)."""
import json
import shutil
from pathlib import Path

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


def test_run_ab_three_arms_kb_beats_none(tmp_path, monkeypatch):
    # scripted fix-stage model: GOLD only when the KB preamble fired, "" (abstain) otherwise.
    def _fx():
        return ModelPatchEngine(CannedModel({"# Applicable playbooks": GOLD, "default": ""}))
    monkeypatch.setattr(ab, "_make_fixer", _fx)

    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(CATALOG))
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))

    cards = ab.run_ab(dataset=str(ds), repos=str(FIX / "repos"), index_db=db,
                      catalog_path=str(catalog_path), out_dir=str(tmp_path / "out"))

    assert set(cards) == {"none", "kb", "placebo"}
    for arm in ("none", "kb", "placebo"):
        assert (tmp_path / "out" / f"scorecard-{arm}.json").is_file()
    none_rr = cards["none"]["arms"]["membership+logs"]["resolved_rate"]["value"]
    kb_rr = cards["kb"]["arms"]["membership+logs"]["resolved_rate"]["value"]
    assert none_rr == 0.0        # no preamble -> "" -> patch_unappliable abstain -> unresolved
    assert kb_rr == 1.0          # KB skill fires -> preamble -> GOLD -> applies -> resolved
    assert kb_rr > none_rr       # the direction-of-effect the A/B measures
