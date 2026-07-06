"""LOFO attribution: keep only line-fragments whose removal drops the measured lift."""
from groundloop.kb.distill.lofo import lofo_fragments


def test_lofo_isolates_the_single_load_bearing_fragment():
    guidance = "\n".join(
        [
            "Signature: NPE in HvacController.onPropertyChanged",
            "Localize: search bind_hvac_service near the CarPropertyManager callback",
            "Fix: null-guard the property value before dispatch",
        ]
    )
    key = "Localize: search bind_hvac_service near the CarPropertyManager callback"

    def run_fn(candidate: str) -> float:
        # Exactly one fragment carries the lift; every other line is inert filler.
        return 1.0 if key in candidate else 0.0

    load_bearing = lofo_fragments(guidance, run_fn)
    assert load_bearing == [key]


def test_lofo_returns_empty_when_no_fragment_moves_the_score():
    guidance = "Signature: A\nLocalize: B\nFix: C"

    def run_fn(_candidate: str) -> float:
        return 0.42  # constant lift -> removing anything never drops it

    assert lofo_fragments(guidance, run_fn) == []


def test_lofo_skips_blank_lines_and_preserves_order():
    guidance = "line-1\n\n  \nline-2\nline-3"
    survivors = {"line-1", "line-3"}

    def run_fn(candidate: str) -> float:
        # Two load-bearing fragments; each removal must drop the score.
        return float(sum(1 for s in survivors if s in candidate))

    assert lofo_fragments(guidance, run_fn) == ["line-1", "line-3"]
