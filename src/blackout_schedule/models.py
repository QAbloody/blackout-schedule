from datetime import datetime, timedelta
from typing import Any

GROUPS = [
    "1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
    "4.1", "4.2", "5.1", "5.2", "6.1", "6.2",
]

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
