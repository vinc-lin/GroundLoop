"""Arm construction for the functional-bug eval. Calibration seeds live here; freeze on a calib
split after the first proxy run (spec §6). Full builder is filled in Task 4.2."""
from __future__ import annotations

# functional score scale = cosine (0..1) + rank-decayed log bonus; margin gate must be reachable.
TAU_FUNC = (0.05, 0.0)
