from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

GROUPS = [
    "1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
    "4.1", "4.2", "5.1", "5.2", "6.1", "6.2",
]


@dataclass(frozen=True)
class Interval:
    start: time
    end: time

    @classmethod
    def from_string(cls, raw: str) -> Interval:
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
