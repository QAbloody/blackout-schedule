#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсить графік відключень через офіційний API
Оновлює schedule.json для Telegram бота

API: https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages
"""

import os
import sys
import json
import requests
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

# API endpoint для планованих відключень
PLANNED_OUTAGES_API = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"

# Регіони та DSO (Distribution System Operator)
REGIONS = {
    "dnipro": {"region_id": 25, "dso_id": 902},
    "kyiv": {"region_id": 7, "dso_id": 401},
}

# Налаштування
CITY = os.getenv("YASNO_CITY", "dnipro")
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

# Всі групи відключень
ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


# ═══════════════════════════════════════════════════════════════════════════════
# API КЛІЄНТ
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_planned_outages(city: str = "dnipro") -> Dict[str, Any]:
    """
    Отримує заплановані відключення через API
    
    Returns:
        Сирі дані API
    """
    region_config = REGIONS.get(city)
    if not region_config:
        raise ValueError(f"Unknown city: {city}. Available: {list(REGIONS.keys())}")
    
    url = PLANNED_OUTAGES_API.format(
        region_id=region_config["region_id"],
        dso_id=region_config["dso_id"]
    )
    
    print(f"📡 Fetching: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    
    # DEBUG: показуємо структуру відповіді
    print(f"\n🔍 DEBUG: API Response structure")
    print(f"   Keys: {list(data.keys())[:5]}...")
    
    # Показуємо приклад для групи 1.1
    if "1.1" in data:
        group_data = data["1.1"]
        print(f"   Group 1.1 keys: {list(group_data.keys())}")
        if "today" in group_data:
            today_data = group_data["today"]
            print(f"   Today keys: {list(today_data.keys())}")
            slots = today_data.get("slots", [])
            print(f"   Slots count: {len(slots)}")
            if slots:
                print(f"   First slot: {slots[0]}")
                # Показуємо всі типи слотів
                types = set(s.get("type") for s in slots)
                print(f"   Slot types: {types}")
    
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСЕР
# ═══════════════════════════════════════════════════════════════════════════════

def minutes_to_time(minutes: int) -> str:
    """Конвертує хвилини від початку доби в HH:MM"""
    hours = minutes // 60
    mins = minutes % 60
    
    if hours >= 24:
        return "24:00"
    
    return f"{hours:02d}:{mins:02d}"


def merge_slots(slots: List[Dict]) -> List[Dict]:
    """Об'єднує послідовні слоти"""
    if not slots:
        return []
    
    sorted_slots = sorted(slots, key=lambda x: x["start"])
    merged = [{"start": sorted_slots[0]["start"], "end": sorted_slots[0]["end"]}]
    
    for current in sorted_slots[1:]:
        previous = merged[-1]
        
        if current["start"] <= previous["end"]:
            previous["end"] = max(previous["end"], current["end"])
        else:
            merged.append({"start": current["start"], "end": current["end"]})
    
    return merged


def parse_slots_to_intervals(slots: List[Dict]) -> List[str]:
    """
    Конвертує слоти API в інтервали HH:MM-HH:MM
    
    API повертає:
    {"start": 840, "end": 1080, "type": "Definite"}
    
    start/end - хвилини від початку доби (840 = 14:00)
    """
    # Фільтруємо тільки "Definite" (реальні відключення)
    outage_slots = [s for s in slots if s.get("type") == "Definite"]
    
    if not outage_slots:
        return []
    
    # Об'єднуємо послідовні інтервали
    merged = merge_slots(outage_slots)
    
    # Конвертуємо в HH:MM формат
    intervals = []
    for slot in merged:
        start_str = minutes_to_time(slot["start"])
        end_str = minutes_to_time(slot["end"])
        intervals.append(f"{start_str}-{end_str}")
    
    return intervals


def parse_api_response(data: Dict[str, Any], day: str = "today") -> Dict[str, Any]:
    """
    Парсить відповідь API в формат schedule.json
    
    API структура:
    {
        "1.1": {
            "today": {
                "slots": [{"start": 0, "end": 840, "type": "NotPlanned"}, ...],
                "date": "2026-01-26T00:00:00+02:00",
                "status": "ScheduleApplies"
            },
            "tomorrow": {...},
            "updatedOn": "2026-01-26T10:00:00+00:00"
        },
        "1.2": {...},
        ...
    }
    """
    groups = {}
    schedule_date = None
    
    for group_id in ALL_GROUPS:
        group_data = data.get(group_id, {})
        day_data = group_data.get(day, {})
        
        if not day_data:
            continue
        
        # Витягуємо дату (беремо з першої групи)
        if not schedule_date and "date" in day_data:
            # Формат: "2026-01-26T00:00:00+02:00"
            date_str = day_data["date"]
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                schedule_date = dt.strftime("%d.%m.%Y")
            except (ValueError, AttributeError):
                pass
        
        # Парсимо слоти
        slots = day_data.get("slots", [])
        intervals = parse_slots_to_intervals(slots)
        
        if intervals:
            groups[group_id] = intervals
    
    # Якщо дату не знайшли - використовуємо поточну
    if not schedule_date:
        target_date = date.today()
        if day == "tomorrow":
            target_date += timedelta(days=1)
        schedule_date = target_date.strftime("%d.%m.%Y")
    
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
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️  Failed to load existing schedule: {e}")
        return {}


def save_schedule(schedule: Dict, path: str) -> None:
    """Зберігає графік в JSON"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Saved to {path}")


def schedules_differ(old: Dict, new: Dict) -> bool:
    """Перевіряє чи є зміни в графіку"""
    return (
        old.get("groups", {}) != new.get("groups", {}) or
        old.get("date") != new.get("date")
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ГОЛОВНА ФУНКЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Головна функція"""
    import argparse
    
    parser = argparse.ArgumentParser(description="YASNO Schedule Parser")
    parser.add_argument("--city", default=CITY, choices=list(REGIONS.keys()),
                       help="City (default: dnipro)")
    parser.add_argument("--day", default="today", choices=["today", "tomorrow"],
                       help="Day to fetch (default: today)")
    parser.add_argument("--output", "-o", default=SCHEDULE_PATH,
                       help="Output file (default: schedule.json)")
    parser.add_argument("--force", "-f", action="store_true",
                       help="Save even if no changes")
    parser.add_argument("--dry-run", "-n", action="store_true",
                       help="Don't save, just print")
    
    args = parser.parse_args()
    
    print(f"🚀 YASNO Schedule Parser")
    print(f"   City: {args.city}")
    print(f"   Day: {args.day}")
    print()
    
    try:
        # 1. Отримуємо дані з API
        raw_data = fetch_planned_outages(args.city)
        
        # 2. Парсимо у формат schedule.json
        schedule = parse_api_response(raw_data, args.day)
        
        # 3. Виводимо результат
        print(f"\n📊 Schedule for {schedule['date']}")
        print(f"   Groups with outages: {len(schedule['groups'])}")
        print()
        
        for group_id in sorted(schedule['groups'].keys()):
            intervals = schedule['groups'][group_id]
            print(f"  {group_id}: {intervals}")
        
        if args.dry_run:
            print("\n🔍 Dry run - not saving")
            return 0
        
        # 4. Перевіряємо зміни
        existing = load_existing(args.output)
        has_changes = schedules_differ(existing, schedule)
        
        if not has_changes and not args.force:
            print("\n✅ No changes detected")
            return 0
        
        if has_changes:
            old_date = existing.get("date", "N/A")
            new_date = schedule["date"]
            print(f"\n📝 Changes detected!")
            if old_date != new_date:
                print(f"   Date: {old_date} → {new_date}")
            
            # Показуємо зміни по групах
            old_groups = existing.get("groups", {})
            new_groups = schedule["groups"]
            
            for group_id in ALL_GROUPS:
                old_intervals = old_groups.get(group_id, [])
                new_intervals = new_groups.get(group_id, [])
                
                if old_intervals != new_intervals:
                    print(f"   {group_id}: {old_intervals} → {new_intervals}")
        
        # 5. Зберігаємо
        save_schedule(schedule, args.output)
        print("\n✅ Update completed!")
        
        return 0
        
    except requests.RequestException as e:
        print(f"\n❌ API error: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
