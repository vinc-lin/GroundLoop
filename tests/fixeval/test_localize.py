from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals
from groundloop.fixeval.localize import localize
from groundloop.fixeval.patch import norm_path
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture


def test_localize_returns_gold_path_first(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    sig = Signals(classes=("CGEImageHandler",), methods=("nativeCreateHandler",))
    locs = localize(AtlasIndex(db), "android-gpuimage-plus", sig, summary="crash", k=5)
    assert locs and "cgeImageHandlerAndroid.cpp" in norm_path(locs[0])


def test_localize_empty_signals_returns_empty(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    assert localize(AtlasIndex(db), "android-gpuimage-plus", Signals(), summary="", k=5) == []
