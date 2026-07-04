"""Verify the hermetic atlas.db fixture builder works correctly."""
from tests.fixtures.atlas_fixture import build_atlas_fixture
from groundloop.engines.atlas.store import Store


def test_build_atlas_fixture_creates_searchable_db(tmp_path):
    db_path = str(tmp_path / "atlas.db")
    result = build_atlas_fixture(db_path)
    assert result == db_path

    # Verify data was inserted and is searchable via FTS5
    store = Store(db_path)
    hits = store.keyword_search("CGEImageHandler", repos=["android-gpuimage-plus"], k=5)
    assert len(hits) > 0
    repos_found = {u.repo for u, _rank in hits}
    assert "android-gpuimage-plus" in repos_found

    # Verify all four repos are indexed
    states = store.list_repo_states()
    repo_names = {s.repo for s in states}
    assert repo_names == {"android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview"}
    for state in states:
        assert state.unit_count > 0

    # Verify FTS5 works for organicmaps symbols
    hits2 = store.keyword_search("organicmaps", repos=["organicmaps"], k=5)
    assert any(u.repo == "organicmaps" for u, _ in hits2)
