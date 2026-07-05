from pathlib import Path

from groundloop.eval.dataset import CaseRef, EvalOracle, load_eval_oracle
from groundloop.fixeval.runner import FixRecord
from groundloop.fixeval.scorecard import grade_fix_all

NEG = Path(__file__).parent.parent / "fixtures" / "android_ivi" / "negatives"


def _r(patch_emitted, applies, abstained):
    return FixRecord("c", "a", "r" if patch_emitted else None, [], "+x" if patch_emitted else "", [],
                     patch_emitted, applies, abstained, None if patch_emitted else "x", 0, 0.0)


def test_bucket1_fabrication_penalized():
    # out_of_fleet + a clean-applying patch = fabrication = -c
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_fix_all([_r(True, True, False)], oracle_by_case={"c": oo}, c_values=(1.0,))
    a = card["arms"]["a"]
    assert a["fabrication_rate"]["value"] == 1.0 and a["phi_c"]["1.0"] == -1.0


def test_bucket1_abstain_rewarded():
    oo = EvalOracle("__OUT_OF_FLEET__", is_answerable=False, negative_class="out_of_fleet")
    card = grade_fix_all([_r(False, False, True)], oracle_by_case={"c": oo}, c_values=(1.0,))
    a = card["arms"]["a"]
    assert a["fabrication_rate"]["value"] == 0.0 and a["phi_c"]["1.0"] == 1.0


def test_bucket1_unappliable_patch_is_not_fabrication():
    # an emitted-but-unappliable patch is NOT counted as fabrication (apply-check gates it)
    oo = EvalOracle("__NOT_A_DEFECT__", is_answerable=False, negative_class="not_a_defect")
    card = grade_fix_all([_r(True, False, False)], oracle_by_case={"c": oo}, c_values=(1.0,))
    assert card["arms"]["a"]["fabrication_rate"]["value"] == 0.0


def test_notdefect_fixture_is_bucket1():
    ev = load_eval_oracle(CaseRef(case_id="notdefect-1", case_dir=str(NEG / "notdefect-1")))
    assert ev.is_answerable is False and ev.negative_class == "not_a_defect"
