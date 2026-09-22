from __future__ import annotations

from datetime import datetime

from blackout_schedule.cli import create_telegram_message
from blackout_schedule.models import format_day_status
from blackout_schedule.schedule import build_schedule_payload, validate_schedule


def test_format_day_status_when_unavailable() -> None:
    text = format_day_status("21.09.2026", [], available=False)
    assert "Графіки ще недоступні" in text
    assert "24 год." not in text


def test_unavailable_notification_has_no_schedule_template() -> None:
    text = create_telegram_message(
        "1.2",
        "21.09.2026",
        ["00:00-17:00"],
        "22.09.2026",
        ["17:00-18:30"],
        available=False,
    )
    assert text == "ℹ️ Графіки ще недоступні"
    assert "Група" not in text
    assert "21.09.2026" not in text
    assert "00:00-17:00" not in text


def test_schedule_payload_does_not_use_sample_intervals() -> None:
    payload = build_schedule_payload(datetime(2026, 9, 21))
    assert payload["available"] is False
    assert payload["source"] == "UNAVAILABLE"
    assert all(not intervals for intervals in payload["today"]["groups"].values())
    assert validate_schedule(payload) == []
