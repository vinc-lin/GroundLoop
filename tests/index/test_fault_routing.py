from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.adapters.index.fault_routing import FaultRoutingIndex
from groundloop.core.types import RepoRef, Signals

CATALOG = [RepoRef(r) for r in ("organicmaps", "androidx-media", "cameraview", "android-gpuimage-plus")]


def test_routing_injects_and_ranks_owner_first(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = FaultRoutingIndex(db)
    sig = Signals(packages=("app.organicmaps",), classes=("Framework",))
    ranked = idx.rank_repos(sig, CATALOG)
    assert ranked[0].repo.name == "organicmaps" and ranked[0].score > 0


def test_routing_union_recovers_dropped_owner(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = FaultRoutingIndex(db)
    sig = Signals(packages=("app.organicmaps.unindexedsub",))
    ranked = idx.rank_repos(sig, CATALOG)
    assert "organicmaps" in [r.repo.name for r in ranked if r.score > 0]


def test_retrieve_delegates(tmp_path):
    db = build_atlas_fixture(str(tmp_path / "atlas.db"))
    idx = FaultRoutingIndex(db)
    assert isinstance(idx.retrieve(RepoRef("organicmaps"), "Framework"), list)
