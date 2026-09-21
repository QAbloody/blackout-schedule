from __future__ import annotations

from datetime import datetime

from blackout_schedule.models import format_day_status
from blackout_schedule.schedule import (
    build_schedule_payload,
    generate_groups,
    validate_schedule,
)


def test_generate_groups_has_expected_keys() -> None:
    groups = generate_groups()
    assert len(groups) == 12
    assert "1.1" in groups
    assert "6.2" in groups


def test_format_day_status_when_empty() -> None:
    text = format_day_status("21.09.2026", [])
    assert "21.09.2026" in text
    assert "🟢" in text
    assert "24 год." in text


def test_schedule_payload_is_valid() -> None:
    payload = build_schedule_payload(datetime(2026, 9, 21), source="TEST")
    assert payload["today"]["date"] == "21.09.2026"
    assert payload["tomorrow"]["date"] == "22.09.2026"
    assert validate_schedule(payload) == []
