from groundloop.skills.adapters.mock import MockSkillRegistry, load_skills, SEED_PATH
from groundloop.core.types import Signals
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.skills.ctx import SkillCtx

CRASH = ("java.lang.unsatisfiedlinkerror: no implementation found for "
         "org.wysaid.nativeport.cgeimagehandler.nativecreatehandler()\n"
         "e/libcge_java: load library for 'cge' failed!: couldn't find \"libffmpeg.so\"")


def _ctx(text):
    return SkillCtx(signals=Signals(), repo="android-gpuimage-plus", text=text)


def test_load_seed_skills_have_predicates_and_provenance():
    skills = load_skills(SEED_PATH)
    ids = {s.id for s in skills}
    assert {"aaos-native-lib-load-failure", "jni-native-handle-lifecycle"} <= ids
    assert all(s.provenance and callable(s.applies_to) for s in skills)


def test_select_fires_native_playbooks_on_crash_log():
    reg = MockSkillRegistry.load(SEED_PATH)
    hit = {s.id for s in reg.select(_ctx(CRASH))}
    assert "aaos-native-lib-load-failure" in hit and "jni-native-handle-lifecycle" in hit
    assert "cbm-index-ops" not in hit and "produce-giant-repo" not in hit    # ops null-controls silent


def test_select_silent_on_non_native_ticket():
    reg = MockSkillRegistry.load(SEED_PATH)
    ctx = _ctx("live preview freezes intermittently; no crash; ui stops refreshing")
    assert reg.select(ctx) == []      # empty -> empty preamble -> byte-identical none arm


def test_predicate_only_is_deterministic():
    reg = MockSkillRegistry.load(SEED_PATH)
    assert [s.id for s in reg.select(_ctx(CRASH))] == [s.id for s in reg.select(_ctx(CRASH))]


def test_optional_embedder_rerank_is_deterministic_and_capped():
    # StubEmbedder = offline deterministic vectors; rerank must return a stable, <=top_k ordering
    reg = MockSkillRegistry.load(SEED_PATH, embedder=StubEmbedder(), top_k=1)
    out = reg.select(_ctx(CRASH))
    assert len(out) == 1
    assert [s.id for s in out] == [s.id for s in MockSkillRegistry.load(
        SEED_PATH, embedder=StubEmbedder(), top_k=1).select(_ctx(CRASH))]
