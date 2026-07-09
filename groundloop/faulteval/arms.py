"""Arm construction for the fault-localization eval: 3 arms over the same faultlog dataset.
flood = the legacy full-token extractor; faultslice/routing = the fault-scoped extractor."""
from __future__ import annotations

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.arms import Arm

_TAU = (1.0, 1.0)   # membership scale (matches eval/arms._TAU["membership"])


def build_fault_arms(index_db: str, names=("flood", "faultslice", "routing")) -> list[Arm]:
    tm, ts = _TAU
    atlas = AtlasIndex(index_db)
    made: list[Arm] = []
    for name in names:
        if name == "flood":
            made.append(Arm("flood", atlas, AndroidSignalExtractor(), tm, ts))
        elif name == "faultslice":
            made.append(Arm("faultslice", atlas, FaultSignalExtractor(), tm, ts))
        elif name == "routing":
            from groundloop.adapters.index.fault_routing import FaultRoutingIndex   # Phase 2
            made.append(Arm("routing", FaultRoutingIndex(index_db), FaultSignalExtractor(), tm, ts))
    return made
