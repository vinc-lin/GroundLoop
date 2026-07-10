from groundloop.adapters.index.functional_text import FunctionalTextIndex
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.core.types import RepoRef
from groundloop.domains.android_ivi.functional_signals import FunctionalTextExtractor
from groundloop.core.types import Ticket
from groundloop.engines.atlas.embed import StubEmbedder
from tests.fixtures.atlas_fixture import build_atlas_fixture

CATALOG = [RepoRef("oboe"), RepoRef("newpipe")]


def _profile_db(tmp_path):
    return build_text_profiles(
        {"oboe": ["audio playback streaming low latency"], "newpipe": ["video player youtube feed"]},
        str(tmp_path / "profiles.db"), StubEmbedder(dim=16))


def test_functional_index_ranks_by_prose_similarity(tmp_path):
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16))
    sig = FunctionalTextExtractor().extract((), Ticket("t", "audio playback", "no sound streaming"))
    ranked = idx.rank_repos(sig, CATALOG)
    assert ranked[0].repo.name == "oboe" and ranked[0].score > 0


def test_functional_index_empty_query_all_zero(tmp_path):
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16))
    sig = FunctionalTextExtractor().extract((), Ticket("t", "", ""))
    ranked = idx.rank_repos(sig, CATALOG)
    assert all(r.score == 0.0 for r in ranked)


def test_retrieve_without_atlas_returns_empty(tmp_path):
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16))   # no code atlas
    assert idx.retrieve(RepoRef("oboe"), "audio") == []


def test_retrieve_delegates_to_code_atlas(tmp_path):
    atlas = build_atlas_fixture(str(tmp_path / "atlas.db"))              # has CGEImageHandler symbol
    idx = FunctionalTextIndex(_profile_db(tmp_path), StubEmbedder(dim=16), atlas_db=atlas)
    files = idx.retrieve(RepoRef("android-gpuimage-plus"), "CGEImageHandler")
    assert files and all(isinstance(f, str) for f in files)
