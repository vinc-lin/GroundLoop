from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals, RepoRef
from groundloop.engines.atlas.store import Store, Unit
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


def test_retrieve_returns_only_symbol_files_not_doc_units(tmp_path):
    """localize (retrieve) must return source files, never wiki doc-unit .md filenames —
    a doc unit's `file` is its wiki basename, which can never match a source expected_files."""
    db = str(tmp_path / "atlas.db")
    s = Store(db)
    units = [
        Unit(repo="r", kind="symbol", name="Player", qualified_name="com.x.Player",
             file="src/main/Player.kt", repo_head="h", text="Player playback engine", meta={}),
        Unit(repo="r", kind="doc", name="PlayerModule", qualified_name="PlayerModule",
             file="PlayerModule.md", repo_head="h", text="Player playback engine wiki", meta={}),
    ]
    s.reindex_repo("r", list(zip(units, [[0.0]] * len(units))), repo_head="h")
    files = AtlasIndex(db).retrieve(RepoRef("r"), "playback")
    assert "src/main/Player.kt" in files
    assert "PlayerModule.md" not in files
