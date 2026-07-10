from groundloop.adapters.index.fault_routing import FaultRoutingIndex
from groundloop.adapters.index.functional_text import DispatchIndex, FunctionalTextIndex
from groundloop.adapters.index.text_profile import build_text_profiles
from groundloop.core.types import LogAttachment, RepoRef, Ticket
from groundloop.domains.android_ivi.functional_signals import DispatchExtractor, PROSE_MARK
from groundloop.engines.atlas.embed import StubEmbedder
from tests.fixtures.atlas_fixture import build_atlas_fixture

CAT = [RepoRef("organicmaps"), RepoRef("android-gpuimage-plus")]
_CRASH = ("E AndroidRuntime: FATAL EXCEPTION: main\n"
          "\tat app.organicmaps.Framework.nativeThrow(Framework.java:10)")


def _dispatch(tmp_path):
    prof = build_text_profiles({"organicmaps": ["maps navigation offline"],
                                "android-gpuimage-plus": ["image gpu filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    return DispatchIndex(FaultRoutingIndex(atlas), FunctionalTextIndex(prof, StubEmbedder(dim=16), atlas))


def test_dispatch_extractor_routes_crash_vs_prose():
    crash = DispatchExtractor().extract((LogAttachment("l", "logcat", _CRASH),),
                                        Ticket("t", "crash", "boom"))
    prose = DispatchExtractor().extract((), Ticket("t", "wrong label on settings", "UI text bug"))
    assert not (crash.symbols and crash.symbols[0].startswith(PROSE_MARK))   # crash -> fault signals
    assert prose.symbols and prose.symbols[0].startswith(PROSE_MARK)         # no anchor -> prose


def test_dispatch_index_sends_crash_to_fault_and_prose_to_functional(tmp_path):
    idx = _dispatch(tmp_path)
    ex = DispatchExtractor()
    crash_sig = ex.extract((LogAttachment("l", "logcat", _CRASH),), Ticket("t", "x", "y"))
    prose_sig = ex.extract((), Ticket("t", "offline maps navigation broken", "no route"))
    assert idx.rank_repos(crash_sig, CAT)[0].repo.name == "organicmaps"      # fault routing wins
    assert idx.rank_repos(prose_sig, CAT)[0].repo.name == "organicmaps"      # text sim wins
