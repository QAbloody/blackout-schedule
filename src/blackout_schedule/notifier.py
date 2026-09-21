from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def read_history(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"days": {}}
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data.setdefault("days", {})
        return data
    return {"days": {}}


def append_day_history(path: str | Path, date_str: str, groups: dict[str, list[str]], updated: str | None = None) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = read_history(target)
    data["days"][date_str] = {
        "groups": groups,
        "updated": updated or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with target.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return data
