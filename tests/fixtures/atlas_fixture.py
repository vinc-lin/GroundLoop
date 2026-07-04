"""Hermetic atlas.db fixture builder — FTS5 only, no CBM/embedder required."""
from groundloop.engines.atlas.store import Store, Unit


# repo -> distinctive symbols/namespaces (mirrors what CBM would index)
_UNITS = {
    "android-gpuimage-plus": ["org.wysaid.nativePort.CGEImageHandler", "CGEImageHandler", "libCGE"],
    "organicmaps": ["app.organicmaps.Framework", "storage::Storage::CountryLeafByCountryId"],
    "androidx-media": ["androidx.media3.exoplayer.ExoPlayer", "MediaCodecVideoRenderer"],
    "cameraview": ["com.otaliastudios.cameraview.CameraView"],
}


def build_atlas_fixture(db_path: str) -> str:
    s = Store(db_path)
    for repo, syms in _UNITS.items():
        units = [Unit(repo=repo, kind="symbol", name=sym.split(".")[-1].split("::")[-1],
                      qualified_name=sym, file=f"{repo}/src.ext", repo_head="fixsha",
                      text=sym, meta={}) for sym in syms]
        s.reindex_repo(repo, list(zip(units, [[0.0]] * len(units))), repo_head="fixsha")
    return db_path
