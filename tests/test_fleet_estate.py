import json
from groundloop.adapters.estate import MockEstate
from groundloop.core.types import RepoRef


def test_catalog_and_materialize(tmp_path):
    (tmp_path / "catalog.json").write_text(json.dumps(
        [{"name": "android-gpuimage-plus"}, {"name": "organicmaps"}, {"name": "androidx-media"}]))
    est = MockEstate(str(tmp_path / "catalog.json"), str(tmp_path / "work"))
    names = [r.name for r in est.catalog()]
    assert names == ["android-gpuimage-plus", "organicmaps", "androidx-media"]
    wt = est.materialize(RepoRef("android-gpuimage-plus"))
    assert wt.repo.name == "android-gpuimage-plus"
    import os
    assert os.path.isdir(wt.path)
