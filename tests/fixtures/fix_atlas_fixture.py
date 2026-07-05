"""Fix-eval atlas fixture: android-gpuimage-plus has a Unit whose `file` == the REAL gpuimage-352
oracle expected_files[0], so localize deterministically retrieves the gold path. SEPARATE from
atlas_fixture.py so SP1a's retrieve-dependent tests are not perturbed."""
from groundloop.engines.atlas.store import Store, Unit

_GOLD = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


def build_fix_atlas_fixture(db_path: str) -> str:
    s = Store(db_path)
    units = [
        Unit(repo="android-gpuimage-plus", kind="symbol", name="CGEImageHandler",
             qualified_name="org.wysaid.nativePort.CGEImageHandler", file=_GOLD, repo_head="fixsha",
             text="CGEImageHandler nativeCreateHandler", meta={}),
    ]
    s.reindex_repo("android-gpuimage-plus", list(zip(units, [[0.0]] * len(units))), repo_head="fixsha")
    return db_path
