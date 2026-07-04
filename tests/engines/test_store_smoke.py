from groundloop.engines.atlas.store import Store, Unit


def test_store_reindex_and_keyword_search(tmp_path):
    s = Store(str(tmp_path / "atlas.db"))
    units = [Unit(repo="android-gpuimage-plus", kind="symbol",
                  name="CGEImageHandler", qualified_name="org.wysaid.nativePort.CGEImageHandler",
                  file="cgeImageHandlerAndroid.cpp", repo_head="deadbeef",
                  text="CGEImageHandler org.wysaid.nativePort.CGEImageHandler", meta={})]
    s.reindex_repo("android-gpuimage-plus", list(zip(units, [[0.0]])), repo_head="deadbeef")
    hits = s.keyword_search("CGEImageHandler", repos=["android-gpuimage-plus"], k=5)
    # keyword_search returns list[(Unit, rank)] tuples — NOT dicts (store.py:115-121)
    assert any(u.repo == "android-gpuimage-plus" for u, _rank in hits)
