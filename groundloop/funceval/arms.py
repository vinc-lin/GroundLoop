"""Arm construction for the functional-bug eval. Calibration seeds live here; freeze on a calib
split after the first proxy run (spec §6)."""
from __future__ import annotations

from groundloop.adapters.index.fault_routing import FaultRoutingIndex
from groundloop.adapters.index.functional_text import DispatchIndex, FunctionalTextIndex
from groundloop.domains.android_ivi.functional_signals import DispatchExtractor, FunctionalTextExtractor
from groundloop.eval.arms import Arm
from groundloop.faulteval.arms import build_fault_arms

TAU_FUNC = (0.05, 0.0)


def build_functional_arms(profile_db: str, index_db: str, *, embedder,
                          names=("functional", "dispatch", "flood", "faultslice", "routing")) -> list[Arm]:
    ftext = FunctionalTextIndex(profile_db, embedder, atlas_db=index_db)
    made: list[Arm] = []
    for name in names:
        if name == "functional":
            made.append(Arm("functional", ftext, FunctionalTextExtractor(), *TAU_FUNC))
        elif name == "dispatch":
            disp = DispatchIndex(FaultRoutingIndex(index_db), ftext)
            made.append(Arm("dispatch", disp, DispatchExtractor(), *TAU_FUNC))
        elif name in ("flood", "faultslice", "routing"):
            made += build_fault_arms(index_db, names=(name,))       # reuse v2 ablation arms
    return made
