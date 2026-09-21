from __future__ import annotations

import argparse

import requests

from .config import get_settings
from .models import format_day_status
from .schedule import build_schedule_payload


def create_telegram_message(
    group_name: str,
    today_date: str,
    today_intervals: list[str],
    tomorrow_date: str,
    tomorrow_intervals: list[str],
) -> str:
    today_block = format_day_status(today_date, today_intervals)
    tomorrow_block = format_day_status(tomorrow_date, tomorrow_intervals)
    return (
        f"<b>📍 Група {group_name} ДТЕК Дніпро</b>\n\n"
        f"{today_block}\n\n"
        f"{tomorrow_block}\n"
        "_____________________\n\n"
        "👉 <b>Графіки ДТЕК Дніпро</b> 👈"
    )


def send_telegram(
    text: str, bot_token: str | None = None, chat_id: str | None = None
) -> bool:
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


def cmd_update(_: argparse.Namespace) -> int:
    from .history import update_schedule

    settings = get_settings()
    payload = update_schedule()
    print(
        __import__("json").dumps(
            {"status": "updated", "schedule_path": str(settings["schedule_path"])},
            ensure_ascii=False,
        )
    )
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    payload = build_schedule_payload()
    errors = __import__("blackout_schedule.schedule", fromlist=["validate_schedule"]).validate_schedule(payload)
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Schedule validation passed")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    payload = build_schedule_payload()
    text = create_telegram_message(
        args.group,
        payload["today"]["date"],
        payload["today"]["groups"].get(args.group, []),
        payload["tomorrow"]["date"],
        payload["tomorrow"]["groups"].get(args.group, []),
    )
    success = send_telegram(text)
    if success:
        print("Telegram notification sent")
    else:
        print("Telegram notification skipped: missing BOT_TOKEN or CHAT_ID")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="blackout-schedule CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("update", help="Generate and write a new schedule file")
    subparsers.add_parser("validate", help="Validate schedule format")

    notify = subparsers.add_parser("notify", help="Send default Telegram notification")
    notify.add_argument("--group", default="1.2")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "update"
    command_map = {
        "update": cmd_update,
        "validate": cmd_validate,
        "notify": cmd_notify,
    }
    raise SystemExit(command_map[command](args))
