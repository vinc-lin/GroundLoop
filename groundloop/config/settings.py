from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_dir: str
    domain: str = "android_ivi"
    model: str = "canned"          # 'canned' | (later) gateway ids
    atlas_db: str = ""
    registry: str = ""
    embed_model: str = "bge-m3"    # reuse contract: pinned
    embed_base_url: str = ""
    embed_api_key: str = ""
    symbol_ratio: float = 0.5

    @classmethod
    def load(cls, env: dict | None = None) -> "Settings":
        e = os.environ if env is None else env
        return cls(
            data_dir=e.get("KLOOP_DATA_DIR", os.path.join(os.getcwd(), "data")),
            domain=e.get("KLOOP_DOMAIN", "android_ivi"),
            model=e.get("KLOOP_MODEL", "canned"),
            atlas_db=e.get("KLOOP_ATLAS_DB", ""),
            registry=e.get("KLOOP_REGISTRY", ""),
            embed_model=e.get("KLOOP_EMBED_MODEL", "bge-m3"),
            embed_base_url=e.get("KLOOP_EMBED_BASE_URL", ""),
            embed_api_key=e.get("KLOOP_EMBED_API_KEY", ""),
        )
