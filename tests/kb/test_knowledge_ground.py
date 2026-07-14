"""Oracle-blind ground-check for candidate Knowledge items (Phase A2). Hermetic: a fake resolver stands in
for the atlas; the leak red-test runs against the REAL FLEET_OWNER_TOKENS denylist
(kb/validate.owner_denylist)."""
import sqlite3

import pytest

from groundloop.engines.atlas.store import Store, Unit
from groundloop.kb.knowledge import Knowledge
from groundloop.kb.knowledge_ground import atlas_resolver, check_knowledge_grounded


def _knowledge(**over) -> Knowledge:
    base = dict(id="c-guard", applies_when={"any_text": ["sigsegv"]}, type="fix_step",
                content="Reject a 0 handle at native method entry before dereferencing it.",
                grounding_refs=("GetLongField", "reinterpret_cast"),
                provenance="native-null-deref-segv", tier="candidate", evidence={})
    base.update(over)
    return Knowledge(**base)


def _resolver(known):
    s = set(known)
    return lambda ref: ref in s


def test_grounded_when_all_refs_resolve_and_no_leak():
    chk = check_knowledge_grounded(_knowledge(), _resolver(["GetLongField", "reinterpret_cast"]))
    assert chk.grounded is True
    assert chk.reasons == ()
    assert set(chk.resolved_refs) == {"GetLongField", "reinterpret_cast"}


def test_unresolved_ref_is_not_grounded():
    chk = check_knowledge_grounded(_knowledge(), _resolver(["GetLongField"]))     # reinterpret_cast missing
    assert chk.grounded is False
    assert chk.missing_refs == ("reinterpret_cast",)
    assert any(r.startswith("unresolved_refs:") for r in chk.reasons)


def test_owner_token_leak_is_rejected():
    # "exoplayer" is a media3 owner slug in FLEET_OWNER_TOKENS -> a leak even though the ref resolves.
    k = _knowledge(content="Guard the ExoPlayer native peer handle.", grounding_refs=("GetLongField",))
    chk = check_knowledge_grounded(k, _resolver(["GetLongField"]))
    assert chk.grounded is False
    assert "exoplayer" in chk.leak_tokens


def test_bad_type_and_empty_content_flagged():
    chk = check_knowledge_grounded(_knowledge(type="bogus", content="  "),
                                   _resolver(["GetLongField", "reinterpret_cast"]))
    assert chk.grounded is False
    assert any(r.startswith("bad_type:") for r in chk.reasons)
    assert "empty_content" in chk.reasons


def test_empty_grounding_refs_not_grounded():
    chk = check_knowledge_grounded(_knowledge(grounding_refs=()), _resolver([]))
    assert chk.grounded is False
    assert "no_grounding_refs" in chk.reasons


def _real_store(tmp_path) -> Store:
    """A tiny REAL atlas indexing one plain symbol + one qualified symbol — so grounding is exercised
    against the true FTS + post-filter path (a set-membership fake would MASK the OR-subtoken bug)."""
    s = Store(str(tmp_path / "atlas.db"))
    units = [
        Unit(repo="r1", kind="symbol", name="GetLongField", qualified_name="GetLongField",
             file="jni.cpp", repo_head="h", text="jint GetLongField(JNIEnv*, jobject, jfieldID)", meta={}),
        Unit(repo="r1", kind="symbol", name="lock", qualified_name="std::weak_ptr::lock",
             file="ptr.h", repo_head="h", text="template lock() returns a shared_ptr", meta={}),
    ]
    s.reindex_repo("r1", list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return s


def test_atlas_resolver_grounds_real_symbols_rejects_fabricated(tmp_path):
    resolve = atlas_resolver(_real_store(tmp_path))
    # real indexed identifiers ground (plain name + fully-qualified symbol)
    assert resolve("GetLongField") is True
    assert resolve("std::weak_ptr::lock") is True
    # fabricated qualified/snake refs must NOT ground even though their SUBTOKENS (std, lock, get, buffer)
    # exist fleet-wide — the exact-match post-filter is the whole point (masks the OR-subtoken bug).
    assert resolve("std::totally_made_up::lock") is False
    assert resolve("get_totally_fake_buffer") is False
    assert resolve("DoesNotExist") is False
    assert resolve("") is False


def test_atlas_resolver_swallows_fts_error(tmp_path):
    class BoomStore:                                   # a malformed FTS term -> 'not found', never crashes
        def keyword_search(self, query, k=20, repos=None, kinds=None):
            raise sqlite3.OperationalError("fts5: syntax error")
    assert atlas_resolver(BoomStore())("anything") is False


def test_atlas_resolver_does_not_mask_infra_errors(tmp_path):
    class BrokenStore:                                 # a non-sqlite (infra/programming) error must propagate
        def keyword_search(self, query, k=20, repos=None, kinds=None):
            raise RuntimeError("db connection lost")
    with pytest.raises(RuntimeError):
        atlas_resolver(BrokenStore())("GetLongField")
