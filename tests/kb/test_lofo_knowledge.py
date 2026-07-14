"""Leave-one-ITEM-out ablation Δ (Phase C3), the knowledge-granular LOFO in attribute.py.
Hermetic: a scripted run_fn (set[str] -> float) stands in for the grounded fix-eval; asserts baseline =
run_fn(full), per-item Δ = baseline - run_fn(full - {item}), and id de-dup / order preservation."""
from groundloop.kb.attribute import lofo_knowledge


def test_lofo_knowledge_returns_per_item_delta():
    # scripted lift surface: c1 worth 1.0, c2 worth 0.5, c3 inert. baseline(full) = 1.5.
    def run_fn(s):
        s = set(s)
        return (1.0 if "c1" in s else 0.0) + (0.5 if "c2" in s else 0.0)

    deltas = lofo_knowledge(["c1", "c2", "c3"], run_fn)
    assert deltas["c1"] == 1.0          # remove c1 -> 0.5 ; Δ = 1.5 - 0.5
    assert deltas["c2"] == 0.5          # remove c2 -> 1.0 ; Δ = 1.5 - 1.0
    assert deltas["c3"] == 0.0          # inert: removing it changes nothing


def test_lofo_knowledge_dedups_and_preserves_order():
    deltas = lofo_knowledge(["c1", "c1", "c2"], lambda s: float(len(set(s))))
    assert list(deltas) == ["c1", "c2"]     # de-duplicated, first-seen order preserved
    assert deltas["c1"] == 1.0 and deltas["c2"] == 1.0   # baseline |{c1,c2}|=2, each removal -> 1


def test_lofo_knowledge_empty_is_empty():
    assert lofo_knowledge([], lambda s: 1.0) == {}
