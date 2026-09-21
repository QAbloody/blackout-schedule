from __future__ import annotations

import json
from pathlib import Path

from blackout_schedule.history import append_day_history


def test_append_day_history(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    data = append_day_history(path, "21.09.2026", {"1.2": ["00:00-02:00"]}, updated="2026-09-21 12:00:00")
    assert "21.09.2026" in data["days"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["days"]["21.09.2026"]["groups"]["1.2"] == ["00:00-02:00"]
