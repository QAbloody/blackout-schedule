from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_SCHEDULE_PATH = DATA_DIR / "schedule.json"
LEGACY_SCHEDULE_PATH = ROOT / "schedule.json"
DEFAULT_HISTORY_PATH = DATA_DIR / "history.json"
LEGACY_HISTORY_PATH = ROOT / "history.json"


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def get_settings() -> dict[str, str | Path]:
    schedule_path = Path(get_env("SCHEDULE_PATH", str(DEFAULT_SCHEDULE_PATH)))
    history_path = Path(get_env("HISTORY_PATH", str(DEFAULT_HISTORY_PATH)))
    return {
        "timezone": get_env("TIMEZONE", "Europe/Kyiv"),
        "tg_channel": get_env("TG_CHANNEL", "dnepr_svet_voda"),
        "bot_token": get_env("TG_BOT_TOKEN", ""),
        "chat_id": get_env("TG_CHAT_ID", ""),
        "schedule_path": schedule_path,
        "history_path": history_path,
        "cache_ttl": int(get_env("CACHE_TTL", "300")),
        "check_interval": int(get_env("CHECK_INTERVAL", "300")),
    }
