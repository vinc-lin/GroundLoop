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
# a native crash whose symbol FTS-hits organicmaps but hits NO routing prefix/soname -> a bare
# fts-only RRF margin (~0.017), which sits below TAU_FUNC's cosine tau_margin without rescaling.
_NATIVE = ("F DEBUG   : signal 11 (SIGSEGV), code 1 (SEGV_MAPERR)\n"
           "F DEBUG   :     #00 pc 0000012345  libmapcore.so (storage::Storage::CountryLeafByCountryId+40)\n"
           "F DEBUG   :     #01 pc 0000067890  libmapcore.so (storage::Storage::Load+12)\n")


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


def _dispatch_scaled(tmp_path, fault_scale):
    prof = build_text_profiles({"organicmaps": ["maps navigation offline"],
                                "android-gpuimage-plus": ["image gpu filter"]},
                               str(tmp_path / "p.db"), StubEmbedder(dim=16))
    atlas = build_atlas_fixture(str(tmp_path / "a.db"))
    ftext = FunctionalTextIndex(prof, StubEmbedder(dim=16), atlas)
    return DispatchIndex(FaultRoutingIndex(atlas), ftext, fault_scale=fault_scale)


def test_dispatch_index_sends_crash_to_fault_and_prose_to_functional(tmp_path):
    idx = _dispatch(tmp_path)
    ex = DispatchExtractor()
    crash_sig = ex.extract((LogAttachment("l", "logcat", _CRASH),), Ticket("t", "x", "y"))
    prose_sig = ex.extract((), Ticket("t", "offline maps navigation broken", "no route"))
    assert idx.rank_repos(crash_sig, CAT)[0].repo.name == "organicmaps"      # fault routing wins
    assert idx.rank_repos(prose_sig, CAT)[0].repo.name == "organicmaps"      # text sim wins


def test_fault_scale_makes_crash_branch_predict_under_tau_func(tmp_path):
    # the single TAU_FUNC gate is on the cosine scale; the fault branch is RRF-scaled, so without
    # rescaling the crash margin sits below tau_margin and dispatch would wrongly ABSTAIN.
    from groundloop.eval.abstain import decide
    from groundloop.funceval.arms import TAU_FUNC
    crash_sig = DispatchExtractor().extract((LogAttachment("l", "logcat", _NATIVE),), Ticket("t", "x", "y"))
    scaled = _dispatch_scaled(tmp_path, fault_scale=10.0).rank_repos(crash_sig, CAT)
    raw = _dispatch_scaled(tmp_path, fault_scale=1.0).rank_repos(crash_sig, CAT)
    assert decide(scaled, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1]).predicted == "organicmaps"
    assert decide(raw, tau_margin=TAU_FUNC[0], tau_score=TAU_FUNC[1]).predicted is None
