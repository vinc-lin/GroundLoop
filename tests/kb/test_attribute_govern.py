"""Per-claim promote/retire bridge + attribute_and_govern (Phase C4). Hermetic: a scripted run_card_fn
(set[str] -> arm-scorecard dict) stands in for the grounded fix-eval; the ClaimRecord bridge drives the
REUSED kb/lifecycle ladder; a demoting fail at the bottom rung retires the claim (terminal)."""
from groundloop.kb.attribute import attribute_and_govern, promote_or_retire
from groundloop.kb.claim import Claim


def _claim(cid="c1", tier="candidate", ev=None):
    return Claim(id=cid, applies_when={"any_text": ["x"]}, type="fix_step", content=f"advice {cid}",
                 grounding_refs=("GetLongField",), provenance="p", tier=tier, evidence=ev or {})


# --- the ClaimRecord bridge onto the reused apply_verdict ladder ---
def test_promote_advances_one_rung_and_resets_fail():
    c = promote_or_retire(_claim(tier="candidate", ev={"fail_count": 1}), True)
    assert c.tier == "applied" and c.evidence["fail_count"] == 0


def test_two_promotions_reach_validated():
    c = promote_or_retire(_claim(tier="candidate"), True)   # -> applied
    c = promote_or_retire(c, True)                          # -> validated (the PRODUCTION floor)
    assert c.tier == "validated"


def test_single_fail_holds_tier_but_counts():
    c = promote_or_retire(_claim(tier="validated"), False)
    assert c.tier == "validated" and c.evidence["fail_count"] == 1


def test_persistent_fail_demotes_non_bottom_tier():
    c = _claim(tier="validated")
    c = promote_or_retire(c, False)     # streak 1 -> hold
    c = promote_or_retire(c, False)     # streak 2 -> demote validated->applied
    assert c.tier == "applied" and c.evidence["demotions"] == ["validated->applied"]


def test_persistent_fail_at_candidate_retires():
    c = _claim(tier="candidate")
    c = promote_or_retire(c, False)     # streak 1 -> hold
    c = promote_or_retire(c, False)     # streak 2 at the bottom rung -> retired
    assert c.tier == "retired" and c.evidence["demotions"][-1] == "candidate->retired"


def test_retired_is_terminal():
    assert promote_or_retire(_claim(tier="retired"), True).tier == "retired"   # a pass must NOT resurrect it


# --- attribute_and_govern: screen shortlist -> confirm -> per-claim verdict ---
def _card(ptr, *, fab=0.0, gnd=0.9, rss=0.5):
    return {"plan_target_recall@1": {"value": ptr, "n": 5}, "resolved_rate_strict": {"value": rss, "n": 5},
            "fabrication_rate": {"value": fab, "n": 3}, "plan_groundedness": {"value": gnd, "n": 5},
            "cost_per_solved": {"value": 1.0, "n": 5}, "resolved_by_case": {}}


def test_govern_promotes_a_load_bearing_claim():
    claims = {"c1": _claim("c1"), "c2": _claim("c2")}

    def run_card_fn(ids):                       # c1 lifts plan_target_recall; its placebo does not
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.8 if good else 0.4)

    updated = attribute_and_govern(claims, ["c1"], run_card_fn)
    assert updated["c1"].tier == "applied"                       # promoted one rung
    assert updated["c1"].evidence["measured_lift"]["lofo_delta"] > 0
    assert updated["c2"].tier == "candidate"                     # untouched (not shortlisted)


def test_govern_rejects_a_claim_that_raises_fabrication():
    claims = {"c1": _claim("c1")}

    def run_card_fn(ids):                       # c1 lifts recall BUT raises fabrication -> honesty side fails
        ids = set(ids)
        good = "c1" in ids and "placebo-c1" not in ids
        return _card(0.8 if good else 0.4, fab=0.3 if good else 0.0)

    assert attribute_and_govern(claims, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held, not promoted


def test_govern_retires_placebo_equivalent_claim_on_second_fail():
    claims = {"c1": _claim("c1", ev={"fail_count": 1})}          # already one fail on the ladder

    def run_card_fn(ids):                       # flat: c1 no better than its placebo -> no lift
        return _card(0.5)

    assert attribute_and_govern(claims, ["c1"], run_card_fn)["c1"].tier == "retired"


# --- both gates are INDEPENDENT: promotion needs accept_grounded AND a positive LOFO Δ ---
def test_govern_requires_lofo_even_when_accept_passes():
    """accept_grounded PASSES (claim beats its placebo) but the LOFO ablation Δ == 0 (removing the claim
    does not drop the primary — a sibling/baseline compensates). Deleting the `and deltas[cid] > 0` gate
    would wrongly promote this claim, so this locks the LOFO gate independently."""
    claims = {"c1": _claim("c1")}

    def run_card_fn(ids):                       # metric depends only on the placebo's ABSENCE, not on c1
        return _card(0.8 if "placebo-c1" not in set(ids) else 0.4)

    # LOFO: primary({c1}) == primary({}) == 0.8 -> Δ = 0 ; placebo-swap: head 0.8 vs base 0.4 -> accept ok.
    assert attribute_and_govern(claims, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held (Δ not > 0)


def test_govern_requires_accept_even_when_lofo_passes():
    """The LOFO ablation Δ > 0 (the claim IS load-bearing) but the placebo-swap accept_grounded FAILS
    (no positive grounded lift over its placebo). Deleting the `bool(verdict["accepted"])` gate would
    wrongly promote this claim, so this locks the accept gate independently."""
    claims = {"c1": _claim("c1")}

    def run_card_fn(ids):                       # metric depends only on ANY id present (c1 OR its placebo)
        return _card(0.8 if set(ids) else 0.4)

    # LOFO: primary({c1})=0.8 vs primary({})=0.4 -> Δ=0.4>0 ; placebo-swap: head 0.8 == base 0.8 -> reject.
    assert attribute_and_govern(claims, ["c1"], run_card_fn)["c1"].tier == "candidate"   # held (not accepted)
