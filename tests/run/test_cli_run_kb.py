"""_wire_kb — the composition-root helper that makes the KB path in `gloop run` strictly OPT-IN: with
no --kb-store, it must hand back the fixer UNCHANGED and mint=None (so an unconfigured run stays
byte-identical to before the KB existed); with --kb-store set it wraps the fixer in
KnowledgeInjectingFixEngine (tier_floor='validated') and returns a mint callback. Unit-tested directly
per the task's preferred approach — no need to drive the whole CLI/dataset to exercise this wiring."""
from __future__ import annotations

from pathlib import Path

from groundloop.adapters.fix.canned import CannedFixEngine
from groundloop.kb.inject import KnowledgeInjectingFixEngine
from groundloop.adapters.mock.model import CannedModel
from groundloop.adapters.extractor_recording import RecordingExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor


def _fixer():
    return CannedFixEngine(CannedModel({"default": "patch"}))


def test_wire_kb_falsy_kb_store_returns_fixer_unchanged_and_no_mint(tmp_path):
    from groundloop.cli import _wire_kb

    fixer = _fixer()
    extractor_rec = RecordingExtractor(AndroidSignalExtractor())
    out_fixer, mint = _wire_kb(fixer, extractor_rec, str(tmp_path / "atlas.db"), "", 2, None)
    assert out_fixer is fixer                 # unwrapped, identity-preserved
    assert mint is None


def test_wire_kb_empty_string_kb_store_is_falsy(tmp_path):
    """Belt-and-braces: an explicit empty string (the argparse default) must behave exactly like
    omitting the flag — falsy, not '--kb-store \"\"' engaging the KB path."""
    from groundloop.cli import _wire_kb

    fixer = _fixer()
    extractor_rec = RecordingExtractor(AndroidSignalExtractor())
    out_fixer, mint = _wire_kb(fixer, extractor_rec, str(tmp_path / "atlas.db"), "", 2, None)
    assert out_fixer is fixer and mint is None


def test_wire_kb_with_kb_store_wraps_fixer_and_returns_mint_callback(tmp_path):
    from groundloop.cli import _wire_kb

    fixer = _fixer()
    extractor_rec = RecordingExtractor(AndroidSignalExtractor())
    kb_store = str(tmp_path / "knowledge.json")
    index_db = str(tmp_path / "atlas.db")
    out_fixer, mint = _wire_kb(fixer, extractor_rec, index_db, kb_store, 2, None)
    assert isinstance(out_fixer, KnowledgeInjectingFixEngine)
    assert out_fixer.inner is fixer                       # the real fixer still does the work
    assert out_fixer.tier_floor == "validated"             # production floor, not candidate
    assert out_fixer.extractor_rec is extractor_rec
    assert callable(mint)


def test_wire_kb_mint_callback_writes_a_grounded_playbook_and_dedupes(tmp_path):
    """The mint callback closes over kb_store + an atlas resolver: a clean-applying fix whose refs
    resolve in the atlas gets minted into the store; re-minting the SAME crash class (same signals)
    dedupes onto the same id rather than growing the store."""
    from groundloop.cli import _wire_kb
    from groundloop.core.types import Signals
    from groundloop.engines.atlas.store import Store, Unit
    from groundloop.kb.knowledge import load_knowledge

    index_db = str(tmp_path / "atlas.db")
    # seed the atlas with a real symbol so mint's grounding check has something to resolve against
    store = Store(index_db)
    store.reindex_repo("alpha", [(Unit(repo="alpha", kind="symbol", name="onDestroyView",
                                       qualified_name="MyFragment.onDestroyView", file="MyFragment.kt",
                                       repo_head="h", text="onDestroyView"), None)], repo_head="h")

    kb_store = str(tmp_path / "knowledge.json")
    extractor_rec = RecordingExtractor(AndroidSignalExtractor())
    _, mint = _wire_kb(_fixer(), extractor_rec, index_db, kb_store, 2, None)

    signals = Signals(errors=("NullPointerException",), methods=("onDestroyView",), classes=("MyFragment",))
    diff = "+++ b/MyFragment.kt\n+    override fun onDestroyView() { _binding = null }\n"
    mint("T-1", signals, ["MyFragment.kt"], diff)
    saved = load_knowledge(kb_store)
    assert len(saved) == 1
    first_id = next(iter(saved))

    mint("T-2", signals, ["MyFragment.kt"], diff)          # same crash class -> same id -> dedupes
    saved_again = load_knowledge(kb_store)
    assert len(saved_again) == 1 and next(iter(saved_again)) == first_id


def test_wire_kb_mint_callback_drops_ungrounded_playbook_silently(tmp_path):
    """A fix whose refs don't resolve anywhere in the atlas must NOT be minted (mint_playbook returns
    None) — and the callback must not crash or write an empty/partial entry."""
    from groundloop.cli import _wire_kb
    from groundloop.core.types import Signals

    index_db = str(tmp_path / "atlas.db")     # empty atlas: nothing resolves
    kb_store = str(tmp_path / "knowledge.json")
    extractor_rec = RecordingExtractor(AndroidSignalExtractor())
    _, mint = _wire_kb(_fixer(), extractor_rec, index_db, kb_store, 2, None)

    signals = Signals(errors=("NullPointerException",), methods=("onDestroyView",), classes=("MyFragment",))
    diff = "+++ b/MyFragment.kt\n+    override fun onDestroyView() { _binding = null }\n"
    mint("T-1", signals, ["MyFragment.kt"], diff)
    assert not Path(kb_store).exists()          # nothing grounded -> nothing written
