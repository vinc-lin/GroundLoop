"""Compatibility shim for getenv_compat (mirrors knowledgeloop.envcompat exactly)."""
from __future__ import annotations

import os
import warnings
from typing import Mapping, Optional


def getenv_compat(
    new: str,
    legacy: str,
    *,
    default: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return env[new] if set, else env[legacy] (with deprecation warning), else default.

    Behaviour is byte-identical to knowledgeloop.envcompat.getenv_compat.
    """
    env: Mapping[str, str] = environ if environ is not None else os.environ
    if new in env:
        return env[new]
    if legacy in env:
        warnings.warn(
            f"Environment variable {legacy!r} is deprecated; use {new!r} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return env[legacy]
    return default
