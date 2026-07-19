import json
from groundloop.adapters.index.labs.simple import TokenIndex
from groundloop.core.types import Signals, RepoRef


def test_rank_repos_picks_owning_repo_by_namespace(tmp_path):
    (tmp_path / "index.json").write_text(json.dumps({
        "android-gpuimage-plus": ["org.wysaid", "org.wysaid.nativePort.CGEImageHandler", "libCGE"],
        "organicmaps": ["app.organicmaps", "storage::Storage"],
        "androidx-media": ["androidx.media3", "ExoPlayer"],
    }))
    idx = TokenIndex(str(tmp_path / "index.json"))
    sig = Signals(classes=("org.wysaid.nativePort.CGEImageHandler",), packages=("org.wysaid.nativePort",),
                  libraries=("libCGE.so",))
    ranked = idx.rank_repos(sig, [RepoRef("android-gpuimage-plus"), RepoRef("organicmaps"), RepoRef("androidx-media")])
    assert ranked[0].repo.name == "android-gpuimage-plus" and ranked[0].score > 0
    assert ranked[0].evidence  # some matched token recorded
    # retrieve is a stub returning candidate files (empty is fine in M0)
    assert idx.retrieve(RepoRef("android-gpuimage-plus"), "crash") == []
