"""Arm construction for the fault-localization eval: 3 arms over the same faultlog dataset.
flood = the legacy full-token extractor; faultslice/routing = the fault-scoped extractor."""
from __future__ import annotations

from groundloop.adapters.index.atlas import AtlasIndex
from groundloop.domains.android_ivi.fault_signals import FaultSignalExtractor
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.eval.arms import Arm

_TAU_FTS = (1.0, 1.0)      # raw FTS distinct-token-count scale (flood, faultslice via AtlasIndex)
_TAU_RRF = (0.005, 0.01)   # RRF fused-fraction scale (routing via FaultRoutingIndex; fused ~0.017-0.05)


def build_fault_arms(index_db: str, names=("flood", "faultslice", "routing")) -> list[Arm]:
    atlas = AtlasIndex(index_db)
    made: list[Arm] = []
    for name in names:
        if name == "flood":
            made.append(Arm("flood", atlas, AndroidSignalExtractor(), *_TAU_FTS))
        elif name == "faultslice":
            made.append(Arm("faultslice", atlas, FaultSignalExtractor(), *_TAU_FTS))
        elif name == "routing":
            from groundloop.adapters.index.labs.fault_routing import FaultRoutingIndex   # Phase 2
            made.append(Arm("routing", FaultRoutingIndex(index_db), FaultSignalExtractor(), *_TAU_RRF))
    return made
