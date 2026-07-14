"""Lifecycle tier manager: promote on pass, demote on hysteresis-many consecutive fails."""
import dataclasses

from groundloop.kb.lifecycle import TIERS, apply_verdict, next_tier, prev_tier


@dataclasses.dataclass(frozen=True)
class _Rec:
    tier: str
    fail_count: int = 0
    demotions: tuple[str, ...] = ()


def _rec(tier="candidate", fail_count=0, demotions=()):
    return _Rec(tier=tier, fail_count=fail_count, demotions=tuple(demotions))


def test_tiers_order_and_neighbors():
    assert TIERS == ("candidate", "applied", "validated", "canonical")
    assert next_tier("candidate") == "applied"
    assert next_tier("canonical") == "canonical"  # clamps at top
    assert prev_tier("applied") == "candidate"
    assert prev_tier("candidate") == "candidate"  # clamps at bottom


def test_passing_verdict_promotes_and_resets_fail_count():
    rec = _rec(tier="candidate", fail_count=1)
    out = apply_verdict(rec, True)
    assert out.tier == "applied"
    assert out.fail_count == 0
    assert out.demotions == ()
    assert isinstance(out, _Rec)
    # frozen: input untouched
    assert rec.tier == "candidate" and rec.fail_count == 1


def test_single_fail_does_not_demote_hysteresis():
    rec = _rec(tier="applied", fail_count=0)
    out = apply_verdict(rec, False)
    assert out.tier == "applied"  # NOT demoted on one fail
    assert out.fail_count == 1
    assert out.demotions == ()


def test_two_consecutive_fails_demote_record_and_reset():
    rec = _rec(tier="applied", fail_count=0)
    once = apply_verdict(rec, False)
    twice = apply_verdict(once, False)
    assert twice.tier == "candidate"  # demoted one tier
    assert twice.fail_count == 0  # reset after demotion
    assert twice.demotions == ("applied->candidate",)


def test_pass_after_one_fail_resets_streak_no_demote():
    rec = _rec(tier="applied", fail_count=1)
    out = apply_verdict(rec, True)
    assert out.tier == "validated"
    assert out.fail_count == 0
    assert out.demotions == ()


def test_custom_hysteresis_threshold():
    rec = _rec(tier="validated", fail_count=0)
    r1 = apply_verdict(rec, False, hysteresis=3)
    r2 = apply_verdict(r1, False, hysteresis=3)
    assert r2.tier == "validated" and r2.fail_count == 2  # still no demote at 2
    r3 = apply_verdict(r2, False, hysteresis=3)
    assert r3.tier == "applied" and r3.fail_count == 0
    assert r3.demotions == ("validated->applied",)


def test_apply_verdict_returns_new_instance():
    rec = _rec()
    assert apply_verdict(rec, True) is not rec
    assert dataclasses.is_dataclass(apply_verdict(rec, True))
