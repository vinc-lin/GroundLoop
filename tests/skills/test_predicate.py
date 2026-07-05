import pytest

from groundloop.core.types import Signals
from groundloop.skills.ctx import SkillCtx
from groundloop.skills.predicate import compile_predicate


def _ctx(text="", **sig):
    return SkillCtx(signals=Signals(**sig), repo="r", text=text.lower())


def test_unknown_key_raises_at_compile():
    with pytest.raises(ValueError):
        compile_predicate({"any_bogus": ["x"]})


def test_bad_regex_raises_at_compile():
    with pytest.raises(ValueError):
        compile_predicate({"any_text_regex": ["("]})   # unbalanced


def test_empty_spec_never_fires():
    assert compile_predicate({})(_ctx("anything")) is False


def test_any_text_substring_or():
    p = compile_predicate({"any_text": ["unsatisfiedlinkerror", "sigsegv"]})
    assert p(_ctx("...java.lang.UnsatisfiedLinkError: no impl...")) is True
    assert p(_ctx("live preview freezes")) is False


def test_all_text_conjunction():
    p = compile_predicate({"all_text": ["load", "library"]})
    assert p(_ctx("load library for cge failed")) is True
    assert p(_ctx("load only")) is False


def test_any_text_regex_over_haystack():
    p = compile_predicate({"any_text_regex": [r"lib\w+\.so"]})
    assert p(_ctx("couldn't find \"libffmpeg.so\"")) is True
    assert p(_ctx("no native lib here")) is False


def test_family_membership_substring():
    p = compile_predicate({"any_libraries": [".so"]})
    assert p(_ctx("", libraries=("libffmpeg.so",))) is True
    assert p(_ctx("", libraries=())) is False


def test_repo_in():
    p = compile_predicate({"repo_in": ["android-gpuimage-plus"]})
    assert p(SkillCtx(Signals(), "android-gpuimage-plus", "")) is True
    assert p(SkillCtx(Signals(), "organicmaps", "")) is False


def test_clauses_are_or_across_keys():
    p = compile_predicate({"any_text": ["nomatch"], "any_text_regex": [r"lib\w+\.so"]})
    assert p(_ctx("libffmpeg.so")) is True     # second clause fires though first does not


def test_deterministic():
    p = compile_predicate({"any_text": ["crash"]})
    c = _ctx("crash")
    assert p(c) is True and p(c) is True
