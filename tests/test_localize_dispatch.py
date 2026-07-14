from groundloop.core.types import Signals
from groundloop.domains.android_ivi.functional_signals import (
    PROSE_MARK, is_functional_localize)


def test_is_functional_localize_prose_marked_is_true():
    # DispatchExtractor stuffs prose into symbols[0] behind PROSE_MARK
    sig = Signals(symbols=(PROSE_MARK + "carplay icon does nothing when tapped",))
    assert is_functional_localize(sig) is True


def test_is_functional_localize_no_anchor_is_true():
    # A prose-only ticket under a non-dispatch extractor: no code tells extracted
    assert is_functional_localize(Signals()) is True
    assert is_functional_localize(Signals(errors=("ANR",))) is True  # generic error != code anchor


def test_is_functional_localize_with_code_anchor_is_false():
    sig = Signals(classes=("com.x.CarPlaySession",), methods=("onConnect",),
                  libraries=("libcarplay.so",))
    assert is_functional_localize(sig) is False


def test_is_functional_localize_native_symbol_anchor_is_false():
    # A real native symbol (NOT prose-marked) is a crash anchor -> FTS5 path
    assert is_functional_localize(Signals(symbols=("IAP2Session",))) is False
