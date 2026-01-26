#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсить графік відключень через офіційний API
Оновлює schedule.json для Telegram бота

API: https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity
"""

import os
import sys
import json
import requests
from datetime import datetime, date
from typing import Dict, List, Any
import re


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

DAILY_SCHEDULE_API = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"

CITY = os.getenv("YASNO_CITY", "dnipro")
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


# ═══════════════════════════════════════════════════════════════════════════════
# API КЛІЄНТ
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_schedule_api() -> Dict[str, Any]:
    """Отримує дані з API"""
    print(f"📡 Fetching: {DAILY_SCHEDULE_API}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    
    response = requests.get(DAILY_SCHEDULE_API, headers=headers, timeout=30)
    response.raise_for_status()
    
    return response.json()


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСЕР
# ═══════════════════════════════════════════════════════════════════════════════

def hours_to_time(hours: float) -> str:
    """Конвертує години в HH:MM"""
    h = int(hours)
    m = int((hours - h) * 60)
    if h >= 24:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def merge_intervals(intervals: List[Dict]) -> List[Dict]:
    """Об'єднує послідовні інтервали"""
    if not intervals:
        return []
    
    sorted_intervals = sorted(intervals, key=lambda x: x["start"])
    merged = [{"start": sorted_intervals[0]["start"], "end": sorted_intervals[0]["end"]}]
    
    for current in sorted_intervals[1:]:
        previous = merged[-1]
        if current["start"] <= previous["end"]:
            previous["end"] = max(previous["end"], current["end"])
        else:
            merged.append({"start": current["start"], "end": current["end"]})
    
    return merged


def parse_group_slots(slots: List[Dict]) -> List[str]:
    """Парсить слоти групи в інтервали HH:MM-HH:MM"""
    # Фільтруємо тільки реальні відключення
    outage_slots = [s for s in slots if s.get("type") == "DEFINITE_OUTAGE"]
    
    if not outage_slots:
        return []
    
    merged = merge_intervals(outage_slots)
    
    intervals = []
    for slot in merged:
        start_str = hours_to_time(slot["start"])
        end_str = hours_to_time(slot["end"])
        intervals.append(f"{start_str}-{end_str}")
    
    return intervals


def parse_api_response(data: Dict[str, Any], city: str = "dnipro") -> Dict[str, Any]:
    """
    Парсить відповідь API
    
    Структура:
    {
        "components": [
            {
                "template_name": "electricity-outages-daily-schedule",
                "schedule": {
                    "dnipro": {
                        "group_1.1": [{"start": 0, "end": 4, "type": "DEFINITE_OUTAGE"}, ...],
                        "group_1.2": [...],
                        ...
                    }
                }
            }
        ]
    }
    """
    groups = {}
    
    # Шукаємо компонент з графіком
    components = data.get("components", [])
    
    schedule_data = None
    for comp in components:
        if comp.get("template_name") == "electricity-outages-daily-schedule":
            # Дані в ключі "schedule"
            schedule_data = comp.get("schedule", {})
            break
    
    if not schedule_data:
        print("❌ No schedule component found!")
        return {"date": date.today().strftime("%d.%m.%Y"), "timezone": TIMEZONE_NAME, "groups": {}}
    
    # Отримуємо дані для міста
    city_data = schedule_data.get(city, {})
    if not city_data:
        print(f"❌ No data for city: {city}")
        return {"date": date.today().strftime("%d.%m.%Y"), "timezone": TIMEZONE_NAME, "groups": {}}
    
    print(f"🔍 Found {len(city_data)} groups for {city}")
    
    # Парсимо групи (ключі типу "group_1.1" -> "1.1")
    for key, slots in city_data.items():
        # Витягуємо номер групи з "group_1.1" -> "1.1"
        if key.startswith("group_"):
            group_id = key.replace("group_", "")
        else:
            group_id = key
        
        if group_id not in ALL_GROUPS:
            continue
        
        # Flatten якщо slots це список списків
        flat_slots = []
        for item in slots:
            if isinstance(item, list):
                flat_slots.extend(item)
            elif isinstance(item, dict):
                flat_slots.append(item)
        
        print(f"   {group_id}: {len(flat_slots)} slots", end="")
        
        if flat_slots:
            types = set(s.get("type") for s in flat_slots if isinstance(s, dict))
            print(f" | types: {types}")
        else:
            print()
        
        intervals = parse_group_slots(flat_slots)
        if intervals:
            groups[group_id] = intervals
    
    # Дата - сьогодні
    schedule_date = date.today().strftime("%d.%m.%Y")
    
    return {
        "date": schedule_date,
        "timezone": TIMEZONE_NAME,
        "groups": groups,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# РОБОТА З ФАЙЛАМИ
# ═══════════════════════════════════════════════════════════════════════════════

def load_existing(path: str) -> Dict:
    """Завантажує існуючий графік"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_schedule(schedule: Dict, path: str) -> None:
    """Зберігає графік в JSON"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved to {path}")


def schedules_differ(old: Dict, new: Dict) -> bool:
    """Перевіряє чи є зміни"""
    return (
        old.get("groups", {}) != new.get("groups", {}) or
        old.get("date") != new.get("date")
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="YASNO Schedule Parser")
    parser.add_argument("--city", default=CITY, choices=["dnipro", "kiev"])
    parser.add_argument("--output", "-o", default=SCHEDULE_PATH)
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--dry-run", "-n", action="store_true")
    
    args = parser.parse_args()
    
    print(f"🚀 YASNO Schedule Parser")
    print(f"   City: {args.city}")
    print()
    
    try:
        raw_data = fetch_schedule_api()
        schedule = parse_api_response(raw_data, args.city)
        
        print(f"\n📊 Schedule for {schedule['date']}")
        print(f"   Groups with outages: {len(schedule['groups'])}")
        print()
        
        for group_id in sorted(schedule['groups'].keys()):
            intervals = schedule['groups'][group_id]
            print(f"  {group_id}: {intervals}")
        
        if args.dry_run:
            print("\n🔍 Dry run - not saving")
            return 0
        
        existing = load_existing(args.output)
        has_changes = schedules_differ(existing, schedule)
        
        if not has_changes and not args.force:
            print("\n✅ No changes detected")
            return 0
        
        save_schedule(schedule, args.output)
        print("\n✅ Update completed!")
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
