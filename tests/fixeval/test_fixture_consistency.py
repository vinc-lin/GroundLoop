import json
from pathlib import Path

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import RepoRef
from groundloop.fixeval.patch import norm_path, touched_files
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

ROOT = Path(__file__).parent.parent / "fixtures"
GOLDEN = ("--- a/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
          "+++ b/library/src/main/jni/interface/cgeImageHandlerAndroid.cpp\n"
          "@@ -1 +1 @@\n-// bug\n+// fixed by nativeCreateHandler\n")


def test_three_surface_path_agreement(tmp_path):
    # 1) oracle expected_files[0]
    oracle = json.loads((ROOT / "android_ivi" / "gpuimage-352" / "_oracle" / "oracle.json").read_text())
    expected = norm_path(oracle["expected_files"][0])
    # 2) atlas retrieve returns that path
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    hits = [norm_path(h) for h in AtlasIndex(db).retrieve(RepoRef("android-gpuimage-plus"),
                                                          "CGEImageHandler nativeCreateHandler")]
    assert expected in hits, f"retrieve {hits} missing oracle path {expected}"
    # 3) checked-in fixture repo contains that path
    assert (ROOT / "repos" / "android-gpuimage-plus" / expected).is_file()
    # 4) golden diff touches that path
    assert norm_path(touched_files(GOLDEN)[0]) == expected
