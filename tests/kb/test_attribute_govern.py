"""Per-item promote/retire bridge + attribute_and_govern (Phase C4). Hermetic: a scripted run_card_fn
(set[str] -> arm-scorecard dict) stands in for the grounded fix-eval; the KnowledgeRecord bridge drives the
REUSED kb/lifecycle ladder; a demoting fail at the bottom rung retires the item (terminal)."""
from groundloop.kb.attribute import attribute_and_govern, promote_or_retire
from groundloop.kb.knowledge import Knowledge


def _knowledge(kid="c1", tier="candidate", ev=None):
    return Knowledge(id=kid, applies_when={"any_text": ["x"]}, signature=f"advice {kid}",
                     fix=(f"advice {kid}",), grounding_refs=("GetLongField",), provenance="p", tier=tier,
                     evidence=ev or {})


# --- the KnowledgeRecord bridge onto the reused apply_verdict ladder ---
def test_promote_advances_one_rung_and_resets_fail():
    k = promote_or_retire(_knowledge(tier="candidate", ev={"fail_count": 1}), True)
    assert k.tier == "applied" and k.evidence["fail_count"] == 0


def test_two_promotions_reach_validated():
    k = promote_or_retire(_knowledge(tier="candidate"), True)   # -> applied
    k = promote_or_retire(k, True)                              # -> validated (the PRODUCTION floor)
    assert k.tier == "validated"


def test_single_fail_holds_tier_but_counts():
    k = promote_or_retire(_knowledge(tier="validated"), False)
    assert k.tier == "validated" and k.evidence["fail_count"] == 1


def test_persistent_fail_demotes_non_bottom_tier():
    k = _knowledge(tier="validated")
    k = promote_or_retire(k, False)     # streak 1 -> hold
    k = promote_or_retire(k, False)     # streak 2 -> demote validated->applied
    assert k.tier == "applied" and k.evidence["demotions"] == ["validated->applied"]


def test_persistent_fail_at_candidate_retires():
    k = _knowledge(tier="candidate")
    k = promote_or_retire(k, False)     # streak 1 -> hold
    k = promote_or_retire(k, False)     # streak 2 at the bottom rung -> retired
    assert k.tier == "retired" and k.evidence["demotions"][-1] == "candidate->retired"


def test_retired_is_terminal():
    assert promote_or_retire(_knowledge(tier="retired"), True).tier == "retired"   # a pass must NOT resurrect


# --- attribute_and_govern: screen shortlist -> confirm -> per-item verdict ---
def _card(ptr, *, fab=0.0, gnd=0.9, rss=0.5):
    return {"plan_target_recall@1": {"value": ptr, "n": 5}, "resolved_rate_strict": {"value": rss, "n": 5},
            "fabrication_rate": {"value": fab, "n": 3}, "plan_groundedness": {"value": gnd, "n": 5},
            "cost_per_solved": {"value": 1.0, "n": 5}, "resolved_by_case": {}}


def test_govern_promotes_a_load_bearing_item():
    knowledge = {"c1": _knowledge("c1"), "c2": _knowledge("c2")}

    def run_card_fn(ids):                       # c1 lifts resolved_rate_strict; its placebo does not
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.5, rss=0.8 if good else 0.4)      # ptr flat; rss is the load-bearing metric now

    updated = attribute_and_govern(knowledge, ["c1"], run_card_fn)
    assert updated["c1"].tier == "applied"                       # promoted one rung
    assert updated["c1"].evidence["measured_lift"]["lofo_delta"] > 0
    assert updated["c2"].tier == "candidate"                     # untouched (not shortlisted)


def test_govern_rejects_an_item_that_raises_fabrication():
    knowledge = {"c1": _knowledge("c1")}

    def run_card_fn(ids):                       # c1 lifts recall BUT raises fabrication -> honesty side fails
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.8 if good else 0.4, fab=0.3 if good else 0.0)

    assert attribute_and_govern(knowledge, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held, not promoted


def test_govern_retires_placebo_equivalent_item_on_second_fail():
    knowledge = {"c1": _knowledge("c1", ev={"fail_count": 1})}   # already one fail on the ladder

    def run_card_fn(ids):                       # flat: c1 no better than its placebo -> no lift
        return _card(0.5)

    assert attribute_and_govern(knowledge, ["c1"], run_card_fn)["c1"].tier == "retired"


# --- both gates are INDEPENDENT: promotion needs accept_grounded AND a positive LOFO Δ ---
def test_govern_requires_lofo_even_when_accept_passes():
    """accept_grounded PASSES (item beats its placebo) but the LOFO ablation Δ == 0 (removing the item
    does not drop the primary — a sibling/baseline compensates). Deleting the `and deltas[cid] > 0` gate
    would wrongly promote this item, so this locks the LOFO gate independently."""
    knowledge = {"c1": _knowledge("c1")}

    def run_card_fn(ids):                       # ptr depends only on the placebo's ABSENCE; rss stays flat
        return _card(0.8 if "placebo-c1" not in set(ids) else 0.4)

    # LOFO on rss (the primary): rss({c1}) == rss({}) == 0.5 (flat) -> Δ = 0 ; accept passes via ptr:
    # head ptr 0.8 vs base ptr 0.4 -> accept_grounded pos_ok. Held on the LOFO gate alone (Δ not > 0).
    assert attribute_and_govern(knowledge, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held (Δ not > 0)


def test_govern_requires_accept_even_when_lofo_passes():
    """The LOFO ablation Δ > 0 (the item IS load-bearing) but the placebo-swap accept_grounded FAILS
    (no positive grounded lift over its placebo). Deleting the `bool(verdict["accepted"])` gate would
    wrongly promote this item, so this locks the accept gate independently."""
    knowledge = {"c1": _knowledge("c1")}

    def run_card_fn(ids):                       # rss (the primary) depends only on ANY id present (c1 OR placebo)
        return _card(0.5, rss=0.8 if set(ids) else 0.4)

    # LOFO on rss: rss({c1})=0.8 vs rss({})=0.4 -> Δ=0.4>0 (load-bearing) ; placebo-swap: head rss 0.8 ==
    # base rss 0.8 (both have an id present) -> accept_grounded rejects the tie. Held on the accept gate alone.
    assert attribute_and_govern(knowledge, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held (not accepted)
