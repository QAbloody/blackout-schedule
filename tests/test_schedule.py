from __future__ import annotations

from datetime import datetime

from blackout_schedule.parser import extract_intervals, parse_date_reference


def test_parse_date_reference_today() -> None:
    day = parse_date_reference("сьогодні", today=datetime(2026, 9, 21))
    assert day == "21.09.2026"


def test_parse_date_reference_full_date() -> None:
    day = parse_date_reference("24.01.2026")
    assert day == "24.01.2026"


def test_extract_intervals() -> None:
    text = "1.2: 00:00-04:00, 07:30-11:00; 18:00-21:30"
    intervals = extract_intervals(text)
    assert intervals == ["00:00-04:00", "07:30-11:00", "18:00-21:30"]
