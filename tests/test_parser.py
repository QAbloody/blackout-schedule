from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import get_settings, LEGACY_HISTORY_PATH, LEGACY_SCHEDULE_PATH
from .models import build_schedule_payload, validate_schedule, write_json
from .notifier import build_default_notification, send_telegram


def _write_compatibility_files(schedule: dict, history: dict | None = None) -> None:
    settings = get_settings()
    schedule_path = Path(settings["schedule_path"])
    legacy_schedule = LEGACY_SCHEDULE_PATH
    write_json(schedule_path, schedule)
    if schedule_path != legacy_schedule:
        write_json(legacy_schedule, schedule)

    if history is not None:
        history_path = Path(settings["history_path"])
        legacy_history = LEGACY_HISTORY_PATH
        write_json(history_path, history)
        if history_path != legacy_history:
            write_json(legacy_history, history)


def cmd_update(_: argparse.Namespace) -> int:
    settings = get_settings()
    payload = build_schedule_payload()
    errors = validate_schedule(payload)
    if errors:
        raise ValueError("Schedule validation failed: " + "; ".join(errors))

    history = {
        "days": {
            payload["today"]["date"]: {"groups": payload["today"]["groups"], "updated": payload["updated"]},
            payload["tomorrow"]["date"]: {"groups": payload["tomorrow"]["groups"], "updated": payload["updated"]},
        }
    }
    _write_compatibility_files(payload, history)
    print(json.dumps({"status": "updated", "schedule_path": str(settings["schedule_path"])}, ensure_ascii=False))
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    payload = build_schedule_payload()
    errors = validate_schedule(payload)
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Schedule validation passed")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    text = build_default_notification(args.group)
    success = send_telegram(text)
    if success:
        print("Telegram notification sent")
        return 0
    print("Telegram notification skipped: missing BOT_TOKEN or CHAT_ID")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="blackout-schedule CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("update", help="Generate and write a new schedule file")
    subparsers.add_parser("validate", help="Validate schedule format")

    notify = subparsers.add_parser("notify", help="Send default Telegram notification")
    notify.add_argument("--group", default="1.2")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command_map = {
        "update": cmd_update,
        "validate": cmd_validate,
        "notify": cmd_notify,
    }
    raise SystemExit(command_map[args.command](args))
