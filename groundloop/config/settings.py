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
    produce_base_url: str = ""
    produce_api_key: str = ""
    produce_main_model: str = "deepseek-chat"
    cbm_index_timeout: float = 1800.0   # per-CBM-call ceiling; must cover a cold graph build
    embed_batch: int = 128              # inputs per embed request (server BGE_MAX_BATCH=256)
    embed_max_chars: int = 2000         # truncate each input (server BGE_MAX_CHARS=100000 → 413)
    index_camelcase: bool = False       # opt-in: append identifier sub-words to symbol text at index time

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
            produce_base_url=e.get("KLOOP_PRODUCE_BASE_URL", ""),
            produce_api_key=e.get("KLOOP_PRODUCE_API_KEY", e.get("OPENAI_API_KEY", "")),
            produce_main_model=e.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"),
            cbm_index_timeout=_pos_float(e.get("KLOOP_CBM_INDEX_TIMEOUT"), 1800.0),
            embed_batch=int(_pos_float(e.get("KLOOP_EMBED_BATCH"), 128.0)),
            embed_max_chars=int(_pos_float(e.get("KLOOP_EMBED_MAX_CHARS"), 2000.0)),
            index_camelcase=_bool_env(e.get("KLOOP_INDEX_CAMELCASE")),
        )


def _bool_env(raw: str | None) -> bool:
    """True unless `raw` is missing or an explicit negative ('', '0', 'false', 'no', 'off',
    case-insensitive) — mirrors cli._env_flag so `KLOOP_X=0` disables rather than enabling."""
    return (raw or "").strip().lower() not in ("", "0", "false", "no", "off")


def _pos_float(raw: str | None, default: float) -> float:
    """Parse a positive float from env; fall back to `default` on missing/invalid/non-positive."""
    if raw is None:
        return default
    try:
        v = float(raw)
    except (ValueError, TypeError):
        return default
    return v if v > 0 else default
