"""Arm construction for the functional-bug eval. Calibration seeds live here; freeze on a calib
split after the first proxy run (spec §6)."""
from __future__ import annotations

from groundloop.adapters.index.labs.fault_routing import FaultRoutingIndex
from groundloop.adapters.index.labs.functional_text import DispatchIndex, FunctionalTextIndex
from groundloop.domains.android_ivi.functional_signals import DispatchExtractor, FunctionalTextExtractor
from groundloop.eval.arms import Arm
from groundloop.faulteval.arms import _TAU_RRF, build_fault_arms

TAU_FUNC = (0.05, 0.0)
# align FaultRoutingIndex's RRF margin scale to the functional cosine tau, so the single TAU_FUNC gate
# on the dispatch arm reproduces the routing arm's _TAU_RRF decision (linked if either is recalibrated).
_FAULT_SCALE = TAU_FUNC[0] / _TAU_RRF[0]


def build_functional_arms(profile_db: str, index_db: str, *, embedder,
                          names=("functional", "dispatch", "flood", "faultslice", "routing")) -> list[Arm]:
    made: list[Arm] = []
    if "functional" in names or "dispatch" in names:
        ftext = FunctionalTextIndex(profile_db, embedder, atlas_db=index_db)
    if "functional" in names:
        made.append(Arm("functional", ftext, FunctionalTextExtractor(), *TAU_FUNC))
    if "dispatch" in names:
        disp = DispatchIndex(FaultRoutingIndex(index_db), ftext, fault_scale=_FAULT_SCALE)
        made.append(Arm("dispatch", disp, DispatchExtractor(), *TAU_FUNC))
    fault_names = tuple(n for n in names if n in ("flood", "faultslice", "routing"))
    if fault_names:
        made += build_fault_arms(index_db, names=fault_names)       # reuse v2 ablation arms (one open)
    return made
