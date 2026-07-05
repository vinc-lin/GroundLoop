from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals, RepoRef
from tests.fixtures.atlas_fixture import build_atlas_fixture


def test_atlas_rank_repos_matches_owner_over_real_db(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = AtlasIndex(db)
    sig = Signals(classes=("org.wysaid.nativePort.CGEImageHandler",),
                  packages=("org.wysaid.nativePort",), libraries=("libCGE.so",))
    catalog = [RepoRef("androidx-media"), RepoRef("organicmaps"),
               RepoRef("android-gpuimage-plus"), RepoRef("cameraview")]
    ranked = idx.rank_repos(sig, catalog)
    assert ranked[0].repo.name == "android-gpuimage-plus" and ranked[0].score > 0
    assert ranked[0].evidence  # matched tokens recorded
