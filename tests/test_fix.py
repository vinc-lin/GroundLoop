from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.core.types import WorkTree, RepoRef, Ticket


def test_canned_fix_produces_deterministic_patch():
    model = CannedModel({"default": "PATCH:cgeImageHandlerAndroid.cpp"})
    fx = CannedFixEngine(model)
    p = fx.propose(WorkTree(RepoRef("android-gpuimage-plus"), "/tmp/x"),
                   Ticket("GP-352", "crash", "..."), ["cgeImageHandlerAndroid.cpp"])
    assert "cgeImageHandlerAndroid.cpp" in p.files and p.diff  # non-empty deterministic diff
