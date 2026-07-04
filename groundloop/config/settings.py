from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_dir: str
    domain: str = "android_ivi"
    model: str = "canned"          # 'canned' | (later) gateway ids

    @classmethod
    def load(cls, env: dict | None = None) -> "Settings":
        e = os.environ if env is None else env
        return cls(
            data_dir=e.get("KLOOP_DATA_DIR", os.path.join(os.getcwd(), "data")),
            domain=e.get("KLOOP_DOMAIN", "android_ivi"),
            model=e.get("KLOOP_MODEL", "canned"),
        )
