from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals, RepoRef
from groundloop.engines.atlas.store import Store, Unit
from tests.fixtures.atlas_fixture import build_atlas_fixture


def _u(repo, text, i=0):
    return Unit(repo=repo, kind="symbol", name=f"S{i}", qualified_name=f"{repo}.S{i}",
                file=f"{repo}/f.java", repo_head="h", text=text, meta={})


def test_rank_repos_idf_beats_big_repo_generic_volume(tmp_path):
    """Size-normalization: a small repo owning a RARE token must outrank a big repo that only
    matches several SHARED/generic tokens by volume. Old count scoring gave the big repo the win
    (3 hits > 2); IDF weights the rare token above the shared ones so the true owner wins."""
    db = str(tmp_path / "a.db")
    s = Store(db)
    # 'gcommon' is in all 3 repos (df=3 -> idf 0); 'gtwo'/'gthree' in big+mid (df=2 -> small idf);
    # 'srare' only in small (df=1 -> max idf). big also has VOLUME (many gcommon units).
    big = ([_u("big", "gcommon", i) for i in range(20)] +
           [_u("big", "gtwo", 100), _u("big", "gthree", 101)])
    mid = [_u("mid", "gcommon", 0), _u("mid", "gtwo", 1), _u("mid", "gthree", 2)]
    small = [_u("small", "gcommon", 0), _u("small", "srare", 1)]
    for repo, units in (("big", big), ("mid", mid), ("small", small)):
        s.reindex_repo(repo, list(zip(units, [[0.0]] * len(units))), repo_head="h")

    idx = AtlasIndex(db)
    sig = Signals(classes=("gcommon", "gtwo", "gthree", "srare"))
    ranked = idx.rank_repos(sig, [RepoRef("big"), RepoRef("mid"), RepoRef("small")])
    by = {r.repo.name: r for r in ranked}
    assert by["big"].evidence == ("gcommon", "gthree", "gtwo")   # big still matches 3 tokens...
    assert by["small"].evidence == ("gcommon", "srare")          # ...small only 2
    assert ranked[0].repo.name == "small"                        # ...but IDF puts the rare owner first
    assert by["small"].score > by["big"].score


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
