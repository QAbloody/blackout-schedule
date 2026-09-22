#!/usr/bin/env python3
"""Single-file CLI and implementation for blackout-schedule."""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - only needed for Telegram notifications
    requests = None


# Configuration
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DEFAULT_SCHEDULE_PATH = DATA_DIR / "schedule.json"
LEGACY_SCHEDULE_PATH = ROOT / "schedule.json"
DEFAULT_HISTORY_PATH = DATA_DIR / "history.json"
LEGACY_HISTORY_PATH = ROOT / "history.json"


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def get_settings() -> dict[str, str | Path | int]:
    return {
        "timezone": get_env("TIMEZONE", "Europe/Kyiv"),
        "tg_channel": get_env("TG_CHANNEL", "dnepr_svet_voda"),
        "bot_token": get_env("TG_BOT_TOKEN", ""),
        "chat_id": get_env("TG_CHAT_ID", ""),
        "schedule_path": Path(get_env("SCHEDULE_PATH", str(DEFAULT_SCHEDULE_PATH))),
        "history_path": Path(get_env("HISTORY_PATH", str(DEFAULT_HISTORY_PATH))),
        "cache_ttl": int(get_env("CACHE_TTL", "300")),
        "check_interval": int(get_env("CHECK_INTERVAL", "300")),
    }


GROUPS = [
    "1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
    "4.1", "4.2", "5.1", "5.2", "6.1", "6.2",
]


def generate_intervals() -> list[str]:
    """Generate sample intervals for development and tests only."""
    possible_starts = [f"{hour:02d}:00" for hour in range(24)] + ["00:30"]
    random.shuffle(possible_starts)
    intervals: list[str] = []
    used: list[tuple[int, int]] = []

    for start in possible_starts:
        if len(intervals) >= random.randint(0, 3):
            break
        hour, minute = map(int, start.split(":"))
        duration = random.choice([30, 60, 90, 120, 180])
        start_minutes = hour * 60 + minute
        end_minutes = start_minutes + duration
        if end_minutes > 1440 or any(
            start_minutes < old_end and end_minutes > old_start
            for old_start, old_end in used
        ):
            continue
        intervals.append(f"{start}-{end_minutes // 60:02d}:{end_minutes % 60:02d}")
        used.append((start_minutes, end_minutes))

    return sorted(intervals)


def generate_groups() -> dict[str, list[str]]:
    return {group: generate_intervals() for group in GROUPS}


def build_schedule_payload(
    now: datetime | None = None, source: str = "UNAVAILABLE"
) -> dict[str, Any]:
    now = now or datetime.now()
    empty_groups = {group: [] for group in GROUPS}
    return {
        "timezone": "Europe/Kyiv",
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "available": False,
        "emergency": None,
        "today": {
            "date": now.strftime("%d.%m.%Y"),
            "groups": empty_groups.copy(),
        },
        "tomorrow": {
            "date": (now + timedelta(days=1)).strftime("%d.%m.%Y"),
            "groups": empty_groups.copy(),
        },
    }


def validate_schedule(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for period_name in ("today", "tomorrow"):
        groups = payload.get(period_name, {}).get("groups", {})
        for group_name, intervals in groups.items():
            for interval in intervals:
                try:
                    start_text, end_text = interval.replace(" ", "").split("-")
                    start_hour, start_minute = map(int, start_text.split(":"))
                    end_hour, end_minute = map(int, end_text.split(":"))
                    start_minutes = start_hour * 60 + start_minute
                    end_minutes = end_hour * 60 + end_minute
                except (ValueError, AttributeError):
                    errors.append(f"{period_name}/{group_name}: invalid interval {interval!r}")
                    continue
                if end_minutes <= start_minutes:
                    errors.append(f"{period_name}/{group_name}: end <= start for {interval!r}")
                if not 0 <= start_minutes < 1440 or not 0 <= end_minutes <= 1440:
                    errors.append(f"{period_name}/{group_name}: out-of-range interval {interval!r}")
    return errors


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_schedule() -> dict[str, Any]:
    settings = get_settings()
    payload = build_schedule_payload()
    errors = validate_schedule(payload)
    if errors:
        raise ValueError("Schedule validation failed: " + "; ".join(errors))

    schedule_path = Path(settings["schedule_path"])
    write_json(schedule_path, payload)
    if schedule_path.resolve() != LEGACY_SCHEDULE_PATH.resolve():
        write_json(LEGACY_SCHEDULE_PATH, payload)

    history_path = Path(settings["history_path"])
    history: dict[str, Any] = {"days": {}}
    if history_path.exists():
        try:
            loaded = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                history = loaded
        except json.JSONDecodeError:
            pass
    history.setdefault("days", {})
    for period in ("today", "tomorrow"):
        day = payload[period]
        history["days"][day["date"]] = {
            "groups": day["groups"], "updated": payload["updated"]
        }
    write_json(history_path, history)
    if history_path.resolve() != LEGACY_HISTORY_PATH.resolve():
        write_json(LEGACY_HISTORY_PATH, history)
    return payload


def validate_configuration() -> list[str]:
    settings = get_settings()
    issues: list[str] = []
    if not settings["timezone"]:
        issues.append("TIMEZONE is not configured")
    if settings["bot_token"] and not settings["chat_id"]:
        issues.append("TG_BOT_TOKEN provided without TG_CHAT_ID")
    return issues


@dataclass(frozen=True)
class Interval:
    start: time
    end: time

    @classmethod
    def from_string(cls, raw: str) -> "Interval":
        start_text, end_text = raw.replace(" ", "").split("-")
        return cls(_to_time(start_text), _to_time(end_text))

    @property
    def duration_minutes(self) -> int:
        start = self.start.hour * 60 + self.start.minute
        end = self.end.hour * 60 + self.end.minute
        return max(0, end - start)

    def __str__(self) -> str:
        return f"{_format_time(self.start)}-{_format_time(self.end)}"


def _to_time(value: str) -> time:
    hours, minutes = map(int, value.split(":"))
    return time(hour=hours, minute=minutes)


def _format_time(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_interval(raw: str) -> tuple[str, str]:
    interval = raw.strip().replace(" ", "")
    if "-" not in interval:
        raise ValueError(f"Invalid interval: {raw!r}")
    start_text, end_text = interval.split("-", 1)
    if len(start_text.split(":")) != 2 or len(end_text.split(":")) != 2:
        raise ValueError(f"Invalid interval: {raw!r}")
    return start_text, end_text


def normalize_intervals(intervals: list[str]) -> list[str]:
    cleaned = []
    for interval in intervals:
        if interval:
            start, end = parse_interval(interval)
            cleaned.append(f"{start}-{end}")
    return sorted(set(cleaned))


def format_day_status(date_str: str, intervals: list[str], *, available: bool = True) -> str:
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    day_name = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"][dt.weekday()]
    header = f"📝 <b>{day_name}, {date_str}</b>"
    if not available:
        return f"{header}\nℹ️ Графіки ще недоступні"
    off_minutes = sum(Interval.from_string(item).duration_minutes for item in intervals)
    off_hours = round(off_minutes / 60, 1)
    on_hours = round((1440 - off_minutes) / 60, 1)
    if intervals:
        header_icon, status_icon = "⚠️", "🔴"
        intervals_text = f"{', '.join(intervals)} ({off_hours:g} год.)"
    else:
        header_icon, status_icon = "📝", "🟢"
        intervals_text = "00:00 - 00:00 (24 год.)"
    return f"{header_icon} <b>{day_name}, {date_str}</b>\n{status_icon} {intervals_text}\n📊 <i>Світло є: {on_hours:g} год. | Немає: {off_hours:g} год.</i>"


MONTHS = {
    **dict(zip("січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня".split(), range(1, 13))),
    **dict(zip("января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split(), range(1, 13))),
    **dict(zip("january february march april may june july august september october november december".split(), range(1, 13))),
}


def parse_date_reference(value: str, today: datetime | None = None) -> str:
    today = today or datetime.now()
    text = value.strip().lower()
    if not text:
        raise ValueError("Empty date value")
    if text in {"сьогодні", "сегодня", "today"}:
        return today.strftime("%d.%m.%Y")
    if text in {"завтра", "tomorrow"}:
        return (today + timedelta(days=1)).strftime("%d.%m.%Y")
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{int(day):02d}.{int(month):02d}.{year}"
    match = re.search(r"(\d{1,2})\.(\d{1,2})", text)
    if match:
        day, month = match.groups()
        return f"{int(day):02d}.{int(month):02d}.{today.year}"
    for month_name, month_num in MONTHS.items():
        match = re.search(rf"(\d{{1,2}})\s+{month_name}(?:\s+(\d{{4}}))?", text)
        if match:
            return f"{int(match.group(1)):02d}.{month_num:02d}.{int(match.group(2) or today.year)}"
    raise ValueError(f"Unsupported date format: {value!r}")


def extract_intervals(text: str) -> list[str]:
    return [item.replace(" ", "") for item in re.findall(r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b", text)]


def read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def read_history(path: str | Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        return {"days": {}}
    data.setdefault("days", {})
    return data


def append_day_history(path: str | Path, date_str: str, groups: dict[str, list[str]], updated: str | None = None) -> dict[str, Any]:
    data = read_history(path)
    data["days"][date_str] = {"groups": groups, "updated": updated or datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    write_json(path, data)
    return data


# Telegram notifications and CLI

def format_update_notice(updated: str | None) -> str:
    """Return a short notice showing when the schedule was last refreshed."""
    if not updated:
        return "🕒 Станом на невідомий час графіки не оновлювались"
    try:
        updated_at = datetime.strptime(updated, "%Y-%m-%d %H:%M:%S")
        shown_time = updated_at.strftime("%H:%M")
    except ValueError:
        shown_time = updated
    return f"🕒 Станом на {shown_time} графіки не оновлювались"


def create_telegram_message(
    group_name: str,
    today_date: str,
    today_intervals: list[str],
    tomorrow_date: str,
    tomorrow_intervals: list[str],
    available: bool = False,
    updated: str | None = None,
) -> str:
    if not available:
        return "ℹ️ Графіки ще недоступні"
    return (
        f"<b>📍 Група {group_name} ДТЕК Дніпро</b>\n\n"
        f"{format_day_status(today_date, today_intervals)}\n\n"
        f"{format_day_status(tomorrow_date, tomorrow_intervals)}\n\n"
        f"{format_update_notice(updated)}\n"
        "_____________________\n\n"
        "👉 <b>Графіки ДТЕК Дніпро</b> 👈"
    )


def build_default_notification(group_name: str = "1.2") -> str:
    settings = get_settings()
    payload = build_schedule_payload()
    try:
        stored = read_json(settings["schedule_path"])
        if stored:
            payload = stored
    except (OSError, json.JSONDecodeError):
        pass
    return create_telegram_message(
        group_name,
        payload["today"]["date"],
        payload["today"]["groups"].get(group_name, []),
        payload["tomorrow"]["date"],
        payload["tomorrow"]["groups"].get(group_name, []),
        available=payload.get("available", False),
        updated=payload.get("updated"),
    )


def send_telegram(text: str, bot_token: str | None = None, chat_id: str | None = None) -> bool:
    settings = get_settings()
    token, chat = bot_token or settings["bot_token"], chat_id or settings["chat_id"]
    if not token or not chat or requests is None:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def cmd_update(_: argparse.Namespace) -> int:
    settings = get_settings()
    update_schedule()
    print(json.dumps({"status": "updated", "schedule_path": str(settings["schedule_path"])}, ensure_ascii=False))
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    errors = validate_schedule(build_schedule_payload())
    if errors:
        print("Validation failed:\n" + "\n".join(f"- {error}" for error in errors))
        return 1
    print("Schedule validation passed")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    if send_telegram(build_default_notification(args.group)):
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
    raise SystemExit({"update": cmd_update, "validate": cmd_validate, "notify": cmd_notify}[command](args))


if __name__ == "__main__":
    main()
