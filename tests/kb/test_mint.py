from groundloop.kb.mint import mint_playbook, crash_class_id
from groundloop.core.types import Signals


def _signals():
    return Signals(errors=("NullPointerException",), methods=("onDestroyView",), classes=("MyFragment",))


def _true(ref):
    return True


def _false(ref):
    return False


def test_mint_from_clean_apply_writes_a_grounded_candidate():
    pb = mint_playbook(ticket_id="T-1", signals=_signals(), locations=["MyFragment.kt"],
                       patch_diff="+++ b/MyFragment.kt\n+    override fun onDestroyView() { _binding = null }\n",
                       resolver=_true)
    assert pb is not None and pb.tier == "candidate" and pb.provenance == "minted:T-1"
    assert pb.localize == ("MyFragment.kt",)
    assert "onDestroyView" in pb.grounding_refs


def test_mint_fires_on_realistic_diff_and_excludes_noise():
    diff = ("+++ b/MyFragment.kt\n"
            "+    // Fix: NPE when view destroyed before binding cleared\n"
            "+    override fun onDestroyView() {\n"
            "+        super.onDestroyView()\n"
            "+    }\n")
    def resolver(ref): return ref == "onDestroyView"     # only the real crash-named method resolves
    pb = mint_playbook(ticket_id="T-3", signals=_signals(), locations=["MyFragment.kt"],
                       patch_diff=diff, resolver=resolver)
    assert pb is not None and "onDestroyView" in pb.grounding_refs
    for noise in ("Fix:", "before", "cleared", "override", "fun", "super.onDestroyView"):
        assert noise not in pb.grounding_refs           # comment/keyword/qualified-prefix noise excluded


def test_same_crash_class_gets_the_same_id():
    assert crash_class_id(_signals()) == crash_class_id(_signals())   # stable dedupe key


def test_ungrounded_mint_is_dropped():
    pb = mint_playbook(ticket_id="T-2", signals=_signals(), locations=["X.kt"],
                       patch_diff="+++ b/X.kt\n+foo()\n", resolver=_false)   # nothing resolves
    assert pb is None
