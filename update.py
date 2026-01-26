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
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import re


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

# API endpoint
DAILY_SCHEDULE_API = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"

# Налаштування
CITY = os.getenv("YASNO_CITY", "dnipro")
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

# Всі групи відключень
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
    """Конвертує години (може бути 12.5 = 12:30) в HH:MM"""
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
    """
    Парсить слоти групи в інтервали HH:MM-HH:MM
    
    Слоти приходять як:
    {"start": 0, "end": 4, "type": "DEFINITE_OUTAGE"}
    
    start/end - години (можуть бути десятковими: 12.5 = 12:30)
    """
    # Фільтруємо тільки реальні відключення
    outage_slots = [s for s in slots if s.get("type") == "DEFINITE_OUTAGE"]
    
    if not outage_slots:
        return []
    
    # Об'єднуємо послідовні
    merged = merge_intervals(outage_slots)
    
    # Конвертуємо в HH:MM формат
    intervals = []
    for slot in merged:
        start_str = hours_to_time(slot["start"])
        end_str = hours_to_time(slot["end"])
        intervals.append(f"{start_str}-{end_str}")
    
    return intervals


def parse_api_response(data: Dict[str, Any], city: str = "dnipro", day: str = "today") -> Dict[str, Any]:
    """
    Парсить відповідь API
    
    Структура:
    {
        "components": [
            {
                "template_name": "electricity-outages-daily-schedule",
                "dailySchedule": {
                    "dnipro": {
                        "today": {
                            "title": "Понеділок, 27.01.2026",
                            "groups": {
                                "1.1": [{"start": 0, "end": 4, "type": "DEFINITE_OUTAGE"}, ...]
                            }
                        }
                    }
                }
            }
        ]
    }
    """
    groups = {}
    schedule_date = None
    
    # Шукаємо компонент з графіком
    components = data.get("components", [])
    
    print(f"🔍 DEBUG: Found {len(components)} components")
    
    daily_schedule = None
    for comp in components:
        template = comp.get("template_name", "")
        print(f"   Component: {template}")
        
        if template == "electricity-outages-daily-schedule":
            # DEBUG: показуємо всі ключі компонента
            print(f"   🔍 Component keys: {list(comp.keys())}")
            
            daily_schedule = comp.get("dailySchedule", {})
            
            # Може бути під іншим ключем
            if not daily_schedule:
                print(f"   🔍 Looking for schedule data...")
                for key in comp.keys():
                    val = comp[key]
                    if isinstance(val, dict) and ("dnipro" in val or "kiev" in val or "kyiv" in val):
                        print(f"   🔍 Found city data in key: {key}")
                        daily_schedule = val
                        break
                    if isinstance(val, dict) and "today" in val:
                        print(f"   🔍 Found 'today' in key: {key}")
                        print(f"   🔍 Value: {list(val.keys())}")
            break
    
    if not daily_schedule:
        print("❌ No dailySchedule component found!")
        return {"date": date.today().strftime("%d.%m.%Y"), "timezone": TIMEZONE_NAME, "groups": {}}
    
    print(f"🔍 DEBUG: dailySchedule cities: {list(daily_schedule.keys())}")
    
    # Отримуємо дані для міста
    city_data = daily_schedule.get(city, {})
    if not city_data:
        print(f"❌ No data for city: {city}")
        return {"date": date.today().strftime("%d.%m.%Y"), "timezone": TIMEZONE_NAME, "groups": {}}
    
    print(f"🔍 DEBUG: city_data keys: {list(city_data.keys())}")
    
    # Отримуємо дані для дня
    day_data = city_data.get(day, {})
    if not day_data:
        print(f"❌ No data for day: {day}")
        return {"date": date.today().strftime("%d.%m.%Y"), "timezone": TIMEZONE_NAME, "groups": {}}
    
    # Витягуємо дату з title
    title = day_data.get("title", "")
    print(f"🔍 DEBUG: title = {title}")
    
    # Парсимо дату з "Понеділок, 27.01.2026"
    date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', title)
    if date_match:
        d, m, y = date_match.groups()
        schedule_date = f"{int(d):02d}.{int(m):02d}.{y}"
    else:
        schedule_date = date.today().strftime("%d.%m.%Y")
    
    # Парсимо групи
    groups_data = day_data.get("groups", {})
    print(f"🔍 DEBUG: Found {len(groups_data)} groups")
    
    for group_id, slots in groups_data.items():
        print(f"   Group {group_id}: {len(slots)} slots")
        if slots:
            # Показуємо типи слотів
            types = set(s.get("type") for s in slots)
            print(f"      Types: {types}")
        
        intervals = parse_group_slots(slots)
        if intervals:
            groups[group_id] = intervals
    
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
    parser.add_argument("--city", default=CITY, choices=["dnipro", "kiev"],
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
        raw_data = fetch_schedule_api()
        
        # 2. Парсимо
        schedule = parse_api_response(raw_data, args.city, args.day)
        
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
            print(f"\n📝 Changes detected!")
        
        # 5. Зберігаємо
        save_schedule(schedule, args.output)
        print("\n✅ Update completed!")
        
        return 0
        
    except requests.RequestException as e:
        print(f"\n❌ API error: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
