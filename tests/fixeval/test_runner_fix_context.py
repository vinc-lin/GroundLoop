"""fix_context injection through FixEvalRunner. The provider yields (codewiki, cbm) preamble strings
AFTER localize (it keys on the localized files + signals); the runner composes them onto the
skill/knowledge preamble and re-injects via with_preamble. Default OFF (fix_context=None) -> the
proposing fixer carries no such context (byte-identical to today)."""
import shutil
from pathlib import Path

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.adapters.mock.jira import MockJira
from groundloop.adapters.estate import GitFixtureEstate
from groundloop.core.types import Patch, RepoRef
from groundloop.eval.arms import build_arms
from groundloop.eval.dataset import load_cases
from groundloop.fixeval.runner import FixEvalRunner
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"
CATALOG = [RepoRef(n) for n in ("android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview")]
_GOLD = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"


class _SpyFixer:
    """Records the preamble the PROPOSING clone carried. with_preamble clones (mirrors the real engines)."""
    def __init__(self, holder, preamble=""):
        self.holder = holder
        self.preamble = preamble
        self.model = type("M", (), {"cost_usd": 0.0})()

    def with_preamble(self, pre):
        return _SpyFixer(self.holder, preamble=pre)

    def propose(self, wt, ticket, locations):
        self.holder["preamble"] = self.preamble
        self.holder["locations"] = list(locations)
        return Patch(diff="", files=())          # abstain at patch — only the preamble is under test


class _StubFixContext:
    def __init__(self, codewiki="", cbm=""):
        self._cw = codewiki
        self._cbm = cbm
        self.calls = []

    def preambles(self, repo, files, signals):
        self.calls.append((repo, tuple(files)))
        return self._cw, self._cbm


def _runner(tmp_path, tag, *, fix_context=None):
    ds = tmp_path / f"ds-{tag}"
    ds.mkdir(parents=True)
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return (FixEvalRunner(issues=MockJira(str(ds)),
                          estate=GitFixtureEstate(str(FIX / "repos"), str(tmp_path / f"w-{tag}")),
                          catalog=CATALOG, tau_margin=0.0, tau_score=0.0, fix_context=fix_context),
            load_cases(str(ds)))


_CW = "\n\n# CodeWiki module summaries\n## " + _GOLD + "\nNative image handler module."
_CBM = "\n\n# Live code-graph context (CBM)\n## nativeCreateHandler\nsource:\njlong nativeCreateHandler(){}"


def test_fix_context_reaches_the_proposing_fixer(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    holder = {}
    stub = _StubFixContext(codewiki=_CW, cbm=_CBM)
    runner, cases = _runner(tmp_path, "on", fix_context=stub)
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=_SpyFixer(holder))
    assert "# CodeWiki module summaries" in holder["preamble"]
    assert "# Live code-graph context (CBM)" in holder["preamble"]
    assert "Native image handler module." in holder["preamble"]
    # the provider was keyed on the LOCALIZED files (post-localize injection)
    assert stub.calls and _GOLD in stub.calls[-1][1]
    assert _GOLD in holder["locations"]


def test_default_off_no_fix_context_in_preamble(tmp_path):
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    holder = {}
    runner, cases = _runner(tmp_path, "off", fix_context=None)   # default
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=_SpyFixer(holder))
    assert holder["preamble"] == ""                              # byte-identical to today


def test_fix_context_failsafe_when_provider_raises(tmp_path):
    class _Boom:
        def preambles(self, repo, files, signals):
            raise RuntimeError("provider down")
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    holder = {}
    runner, cases = _runner(tmp_path, "boom", fix_context=_Boom())
    runner.run(cases, build_arms(membership_index=AtlasIndex(db)), fixer=_SpyFixer(holder))
    assert holder["preamble"] == ""                              # error degrades to no context, no crash
