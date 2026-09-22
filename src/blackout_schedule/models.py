from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True)
class Interval:
    start: time
    end: time

    @classmethod
    def from_string(cls, raw: str) -> "Interval":
        start_text, end_text = raw.replace(" ", "").split("-")
        return cls(start=_to_time(start_text), end=_to_time(end_text))

    @property
    def duration_minutes(self) -> int:
        start_minutes = self.start.hour * 60 + self.start.minute
        end_minutes = self.end.hour * 60 + self.end.minute
        return max(0, end_minutes - start_minutes)

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
        if not interval:
            continue
        start_text, end_text = parse_interval(interval)
        cleaned.append(f"{start_text}-{end_text}")
    return sorted(set(cleaned))


def format_day_status(
    date_str: str,
    intervals: list[str],
    *,
    available: bool = True,
) -> str:
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    day_name = [
        "Понеділок",
        "Вівторок",
        "Середа",
        "Четвер",
        "П'ятниця",
        "Субота",
        "Неділя",
    ][dt.weekday()]

    header = f"📝 <b>{day_name}, {date_str}</b>"
    if not available:
        return f"{header}\nℹ️ Графіки ще недоступні"

    off_minutes = sum(Interval.from_string(interval).duration_minutes for interval in intervals)
    on_minutes = 24 * 60 - off_minutes
    off_hours = round(off_minutes / 60, 1)
    on_hours = round(on_minutes / 60, 1)

    if not intervals:
        header_icon = "📝"
        status_icon = "🟢"
        intervals_str = "00:00 - 00:00 (24 год.)"
    else:
        header_icon = "⚠️"
        status_icon = "🔴"
        intervals_str = f"{', '.join(intervals)} ({off_hours:g} год.)"

    return (
        f"{header_icon} <b>{day_name}, {date_str}</b>\n"
        f"{status_icon} {intervals_str}\n"
        f"📊 <i>Світло є: {on_hours:g} год. | Немає: {off_hours:g} год.</i>"
    )
