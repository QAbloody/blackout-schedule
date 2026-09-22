from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

GROUPS = [
    "1.1", "1.2",
    "2.1", "2.2",
    "3.1", "3.2",
    "4.1", "4.2",
    "5.1", "5.2",
    "6.1", "6.2",
]


def generate_intervals() -> list[str]:
    """Generate sample intervals for development and tests only.

    This intentionally remains available as a fixture for future development,
    but is never used by the production payload until a real data source is
    connected.
    """
    possible_starts = [
        "00:00", "00:30", "01:00", "02:00", "03:00", "04:00", "05:00",
        "06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00",
        "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00",
        "20:00", "21:00", "22:00", "23:00",
    ]
    random.shuffle(possible_starts)
    count = random.randint(0, 3)
    intervals: list[str] = []
    used: list[tuple[int, int]] = []

    for start in possible_starts:
        if len(intervals) >= count:
            break
        hour, minute = map(int, start.split(":"))
        duration = random.choice([30, 60, 90, 120, 180])
        start_minutes = hour * 60 + minute
        end_minutes = start_minutes + duration
        if end_minutes > 1440:
            continue

        if any(
            start_minutes < old_end and end_minutes > old_start
            for old_start, old_end in used
        ):
            continue

        end_hour = end_minutes // 60
        end_minute = end_minutes % 60
        intervals.append(f"{start}-{end_hour:02d}:{end_minute:02d}")
        used.append((start_minutes, end_minutes))

    intervals.sort()
    return intervals


def generate_groups() -> dict[str, list[str]]:
    """Return sample groups for development and tests only."""
    return {group: generate_intervals() for group in GROUPS}


def build_schedule_payload(
    now: datetime | None = None,
    source: str = "UNAVAILABLE",
) -> dict[str, Any]:
    """Build a payload without presenting generated data as a real schedule.

    The old random generator is kept above as a future fixture, but fake
    intervals must not be sent to users. A real parser/source can later return
    the same payload shape with ``available=True`` and populated groups.
    """
    now = now or datetime.now()
    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")
    empty_groups = {group: [] for group in GROUPS}
    return {
        "timezone": "Europe/Kyiv",
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "available": False,
        "emergency": None,
        "today": {"date": today, "groups": empty_groups.copy()},
        "tomorrow": {"date": tomorrow, "groups": empty_groups.copy()},
    }


def validate_schedule(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for period_name in ("today", "tomorrow"):
        period = payload.get(period_name, {})
        groups = period.get("groups", {})
        for group_name, intervals in groups.items():
            for interval in intervals:
                try:
                    start_text, end_text = interval.replace(" ", "").split("-")
                    start_minutes = int(start_text.split(":")[0]) * 60 + int(start_text.split(":")[1])
                    end_minutes = int(end_text.split(":")[0]) * 60 + int(end_text.split(":")[1])
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
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
