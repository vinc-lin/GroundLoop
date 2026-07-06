"""C3 gate: the distilled form (B) must re-earn the form-A lift before it can be canonical."""
from groundloop.kb.distill.revalidate import revalidate

# Form A is the full (helped-trace) guidance; the two form-B variants are distillations of it.
_FORM_A = "Signature: NPE in binder. Localize: the HAL service. Fix: null-guard the callback."
_FORM_B_GOOD = "Signature: NPE in binder. Fix: null-guard the callback."   # reproduces the lift
_FORM_B_THIN = "Fix: null-guard."                                          # over-shrunk, weaker

# A tiny lift oracle standing in for a fix-eval A/B run (run_fn: Callable[[str], float]).
_LIFT = {_FORM_A: 0.31, _FORM_B_GOOD: 0.31, _FORM_B_THIN: 0.08}


def _run_fn(guidance: str) -> float:
    return _LIFT[guidance]


def test_distilled_form_that_reproduces_lift_is_accepted():
    assert revalidate(_FORM_B_GOOD, _LIFT[_FORM_A], _run_fn) is True


def test_distilled_form_that_underperforms_is_rejected():
    # B < A beyond the (zero) margin -> rejected before it can be promoted to canonical.
    assert revalidate(_FORM_B_THIN, _LIFT[_FORM_A], _run_fn) is False


def test_margin_tolerates_a_small_regression_but_zero_margin_does_not():
    # Distilled scores 0.29 vs a 0.31 baseline — a 0.02 dip.
    assert revalidate(_FORM_B_GOOD, 0.31, lambda g: 0.29, margin=0.05) is True
    assert revalidate(_FORM_B_GOOD, 0.31, lambda g: 0.29, margin=0.0) is False


def test_exact_baseline_passes_at_zero_margin():
    # Boundary: run_fn == baseline is a PASS (>=, not >).
    assert revalidate(_FORM_B_GOOD, 0.5, lambda g: 0.5) is True
