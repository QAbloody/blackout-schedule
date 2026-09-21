from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


MONTHS_UA = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
    "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}
MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date_reference(value: str, today: datetime | None = None) -> str:
    today = today or datetime.now()
    text = value.strip().lower()
    if not text:
        raise ValueError("Empty date value")
    if text in {"сьогодні", "сегодня", "today"}:
        return today.strftime("%d.%m.%Y")
    if text in {"завтра", "завтра", "tomorrow"}:
        return (today + __import__('datetime').timedelta(days=1)).strftime("%d.%m.%Y")

    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{int(day):02d}.{int(month):02d}.{year}"

    match = re.search(r"(\d{1,2})\.(\d{1,2})", text)
    if match:
        day, month = match.groups()
        return f"{int(day):02d}.{int(month):02d}.{today.year}"

    for month_name, month_num in {**MONTHS_UA, **MONTHS_RU, **MONTHS_EN}.items():
        match = re.search(rf"(\d{{1,2}})\s+{month_name}(?:\s+(\d{{4}}))?", text)
        if match:
            day = int(match.group(1))
            year = int(match.group(2) or today.year)
            return f"{day:02d}.{month_num:02d}.{year}"

    raise ValueError(f"Unsupported date format: {value!r}")


def extract_intervals(text: str) -> list[str]:
    pattern = r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b"
    matches = re.findall(pattern, text)
    return [match.replace(" ", "") for match in matches]


def read_json(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)
