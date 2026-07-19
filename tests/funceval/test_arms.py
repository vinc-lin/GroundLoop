from tests.fixtures.atlas_fixture import build_atlas_fixture

from groundloop.adapters.index.labs.text_profile import build_text_profiles
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.funceval.arms import build_functional_arms


def test_build_functional_arms_names_and_taus(tmp_path):
    prof = build_text_profiles({"organicmaps": ["maps"]}, str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    arms = {a.name: a for a in build_functional_arms(prof, atlas, embedder=StubEmbedder(dim=16))}
    assert {"functional", "dispatch", "flood", "faultslice", "routing"} <= set(arms)
    from groundloop.funceval.arms import TAU_FUNC
    assert (arms["functional"].tau_margin, arms["functional"].tau_score) == TAU_FUNC
