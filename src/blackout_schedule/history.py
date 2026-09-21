from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import get_settings
from .models import build_schedule_payload, validate_schedule


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def update_schedule() -> dict:
    settings = get_settings()
    payload = build_schedule_payload()
    errors = validate_schedule(payload)
    if errors:
        raise ValueError("Schedule validation failed: " + "; ".join(errors))

    schedule_path = Path(settings["schedule_path"])
    _write_json(schedule_path, payload)

    legacy_schedule = Path(settings["schedule_path"]).resolve().parent / "schedule.json"
    if legacy_schedule != schedule_path:
        _write_json(legacy_schedule, payload)

    history_path = Path(settings["history_path"])
    history_data = {"days": {}}
    if history_path.exists():
        with history_path.open("r", encoding="utf-8") as handle:
            history_data = json.load(handle) or {"days": {}}

    for day_key in (payload["today"]["date"], payload["tomorrow"]["date"]):
        if payload["today"]["date"] == day_key:
            groups = payload["today"]["groups"]
        else:
            groups = payload["tomorrow"]["groups"]
        history_data.setdefault("days", {})[day_key] = {"groups": groups, "updated": payload["updated"]}

    _write_json(history_path, history_data)
    legacy_history = history_path.resolve().parent.parent / "history.json"
    if legacy_history != history_path:
        _write_json(legacy_history, history_data)

    return payload


def validate_configuration() -> list[str]:
    settings = get_settings()
    issues: list[str] = []
    if not settings["timezone"]:
        issues.append("TIMEZONE is not configured")
    if settings["bot_token"] and not settings["chat_id"]:
        issues.append("TG_BOT_TOKEN provided without TG_CHAT_ID")
    return issues
