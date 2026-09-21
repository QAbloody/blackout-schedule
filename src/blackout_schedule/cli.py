from __future__ import annotations

import requests

from .config import get_settings
from .models import build_schedule_payload


def create_telegram_message(group_name: str, today_date: str, today_intervals: list[str], tomorrow_date: str, tomorrow_intervals: list[str]) -> str:
    from .models import format_day_status

    today_block = format_day_status(today_date, today_intervals)
    tomorrow_block = format_day_status(tomorrow_date, tomorrow_intervals)
    return (
        f"<b>📍 Група {group_name} ДТЕК Дніпро</b>\n\n"
        f"{today_block}\n\n"
        f"{tomorrow_block}\n"
        "_____________________\n\n"
        "👉 <b>Графіки ДТЕК Дніпро</b> 👈"
    )


def send_telegram(text: str, bot_token: str | None = None, chat_id: str | None = None) -> bool:
    settings = get_settings()
    token = bot_token or settings["bot_token"]
    chat = chat_id or settings["chat_id"]
    if not token or not chat:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def build_default_notification(group_name: str = "1.2") -> str:
    payload = build_schedule_payload()
    return create_telegram_message(
        group_name,
        payload["today"]["date"],
        payload["today"]["groups"].get(group_name, []),
        payload["tomorrow"]["date"],
        payload["tomorrow"]["groups"].get(group_name, []),
    )
