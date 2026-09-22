from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import build_schedule_payload, validate_schedule


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def append_day_history(
    path: str | Path,
    date_str: str,
    groups: dict[str, list[str]],
    updated: str | None = None,
) -> dict[str, Any]:
    data = read_history(path)
    data["days"][date_str] = {
        "groups": groups,
        "updated": updated or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    write_json(path, data)
    return data
