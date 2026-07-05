"""GATED (A5): a Skill can bias localization via skill_query. Hermetic — a two-unit atlas where the
gold JNI-loader file is retrievable ONLY by a skill token ('registernatives'), never by the arm's
signal tokens. Proves skill_query surfaces a file plain localize misses (a file_recall bias lever)
and that skill_query='' stays byte-identical to the pre-A5 query."""
from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.core.types import Signals
from groundloop.engines.atlas.store import Store, Unit
from groundloop.fixeval.localize import localize
from groundloop.fixeval.runner import _skill_query
from groundloop.skills.base import Skill

_SIGNAL_FILE = "library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"
_SKILL_FILE = "library/src/main/jni/loader/registerNatives.cpp"


def _build(db_path: str) -> str:
    s = Store(db_path)
    units = [
        Unit(repo="android-gpuimage-plus", kind="symbol", name="CGEImageHandler",
             qualified_name="org.wysaid.CGEImageHandler", file=_SIGNAL_FILE, repo_head="fixsha",
             text="CGEImageHandler nativeCreateHandler", meta={}),
        Unit(repo="android-gpuimage-plus", kind="symbol", name="registerNatives",
             qualified_name="org.wysaid.registerNatives", file=_SKILL_FILE, repo_head="fixsha",
             text="registernatives unsatisfiedlinkerror jni loader", meta={}),
    ]
    s.reindex_repo("android-gpuimage-plus", list(zip(units, [[0.0]] * len(units))),
                   repo_head="fixsha")
    return db_path


def _sig() -> Signals:
    return Signals(classes=("CGEImageHandler",), methods=("nativeCreateHandler",))


def test_default_skill_query_is_byte_identical(tmp_path):
    db = _build(str(tmp_path / "atlas.db"))
    idx = AtlasIndex(db)
    assert localize(idx, "android-gpuimage-plus", _sig(), summary="crash", k=5) == \
        localize(idx, "android-gpuimage-plus", _sig(), summary="crash", k=5, skill_query="")


def test_plain_localize_misses_the_skill_only_file(tmp_path):
    db = _build(str(tmp_path / "atlas.db"))
    plain = localize(AtlasIndex(db), "android-gpuimage-plus", _sig(), summary="crash", k=5)
    assert _SIGNAL_FILE in plain and _SKILL_FILE not in plain


def test_skill_query_biases_file_recall(tmp_path):
    db = _build(str(tmp_path / "atlas.db"))
    boosted = localize(AtlasIndex(db), "android-gpuimage-plus", _sig(), summary="crash",
                       k=5, skill_query="registernatives")
    assert _SKILL_FILE in boosted   # the skill token surfaced a file plain localize missed


def test_skill_query_built_from_signals_and_localize_line():
    s = Skill(id="jni-loader", applies_to=lambda c: True,
              guidance="Signature: UnsatisfiedLinkError\nLocalize: registernatives jniLibs\nFix: register",
              signals=("native", "so"))
    q = _skill_query([s])
    assert "native" in q and "so" in q
    assert "registernatives" in q and "jniLibs" in q
    assert "Signature:" not in q and "Fix:" not in q


def test_skill_query_empty_when_no_skills():
    assert _skill_query([]) == ""
