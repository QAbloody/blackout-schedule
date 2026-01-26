#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсить графік відключень через офіційний API
Для Дніпра: https://static.yasno.ua/dnipro/outages

Два джерела даних:
1. Planned Outages API - для конкретних відключень (DEFINITE)
2. Daily Schedule API - для графіку по групах
"""

import os
import json
import requests
from datetime import datetime, date
from typing import Dict, List, Optional, Any


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

# API endpoints
PLANNED_OUTAGES_API = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"
DAILY_SCHEDULE_API = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"

# Регіони та DSO
REGIONS = {
    "dnipro": {"region_id": 25, "dso_id": 902},
    "kyiv": {"region_id": 7, "dso_id": 401},
}

# Налаштування
CITY = os.getenv("YASNO_CITY", "dnipro")
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

# Групи відключень
ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


# ═══════════════════════════════════════════════════════════════════════════════
# API КЛІЄНТ
# ═══════════════════════════════════════════════════════════════════════════════

class YasnoApiClient:
    """Клієнт для роботи з YASNO API"""
    
    def __init__(self, city: str = "dnipro"):
        self.city = city
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
    
    def get_planned_outages(self) -> Dict[str, Any]:
        """
        Отримує заплановані відключення через Planned Outages API
        
        Returns:
            Сирі дані API з графіком по групах
        """
        region_config = REGIONS.get(self.city)
        if not region_config:
            raise ValueError(f"Unknown city: {self.city}")
        
        url = PLANNED_OUTAGES_API.format(
            region_id=region_config["region_id"],
            dso_id=region_config["dso_id"]
        )
        
        print(f"📡 Fetching planned outages from: {url}")
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        return response.json()
    
    def get_daily_schedule(self) -> Dict[str, Any]:
        """
        Отримує денний графік через Daily Schedule API
        
        Returns:
            Сирі дані API з графіком
        """
        print(f"📡 Fetching daily schedule from: {DAILY_SCHEDULE_API}")
        
        response = self.session.get(DAILY_SCHEDULE_API, timeout=30)
        response.raise_for_status()
        
        return response.json()


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСЕР
# ═══════════════════════════════════════════════════════════════════════════════

class YasnoScheduleParser:
    """Парсер графіку відключень YASNO"""
    
    def __init__(self, city: str = "dnipro"):
        self.city = city
        self.client = YasnoApiClient(city)
    
    def parse_planned_outages(self, data: Dict[str, Any], day: str = "today") -> Dict[str, List[str]]:
        """
        Парсить Planned Outages API відповідь
        
        API повертає структуру:
        {
            "1.1": {
                "today": {
                    "slots": [
                        {"start": 0, "end": 840, "type": "NotPlanned"},
                        {"start": 840, "end": 1080, "type": "Definite"},
                        ...
                    ],
                    "date": "2025-11-05T00:00:00+02:00"
                },
                "tomorrow": {...}
            },
            "1.2": {...}
        }
        
        start/end - хвилини від початку доби (0 = 00:00, 60 = 01:00, 1440 = 24:00)
        """
        groups = {}
        schedule_date = None
        
        for group_id in ALL_GROUPS:
            group_data = data.get(group_id, {})
            day_data = group_data.get(day, {})
            
            if not day_data:
                continue
            
            # Витягуємо дату
            if not schedule_date and "date" in day_data:
                schedule_date = day_data["date"]
            
            slots = day_data.get("slots", [])
            intervals = self._parse_slots(slots)
            
            if intervals:
                groups[group_id] = intervals
        
        return groups, schedule_date
    
    def _parse_slots(self, slots: List[Dict]) -> List[str]:
        """
        Конвертує слоти API в інтервали HH:MM-HH:MM
        
        Враховуємо тільки type="Definite" (DEFINITE_OUTAGE)
        """
        outage_slots = [s for s in slots if s.get("type") in ("Definite", "DEFINITE_OUTAGE")]
        
        if not outage_slots:
            return []
        
        # Об'єднуємо послідовні інтервали
        merged = self._merge_slots(outage_slots)
        
        # Конвертуємо в HH:MM формат
        intervals = []
        for slot in merged:
            start_minutes = slot["start"]
            end_minutes = slot["end"]
            
            start_str = self._minutes_to_time(start_minutes)
            end_str = self._minutes_to_time(end_minutes)
            
            intervals.append(f"{start_str}-{end_str}")
        
        return intervals
    
    def _merge_slots(self, slots: List[Dict]) -> List[Dict]:
        """Об'єднує послідовні слоти з однаковим типом"""
        if not slots:
            return []
        
        # Сортуємо за початком
        sorted_slots = sorted(slots, key=lambda x: x["start"])
        
        merged = [{"start": sorted_slots[0]["start"], "end": sorted_slots[0]["end"]}]
        
        for current in sorted_slots[1:]:
            previous = merged[-1]
            
            # Якщо поточний слот починається там, де закінчився попередній
            if current["start"] <= previous["end"]:
                previous["end"] = max(previous["end"], current["end"])
            else:
                merged.append({"start": current["start"], "end": current["end"]})
        
        return merged
    
    def _minutes_to_time(self, minutes: int) -> str:
        """Конвертує хвилини від початку доби в HH:MM"""
        hours = minutes // 60
        mins = minutes % 60
        
        if hours >= 24:
            return "24:00"
        
        return f"{hours:02d}:{mins:02d}"
    
    def parse_daily_schedule(self, data: Dict[str, Any], day: str = "today") -> Dict[str, List[str]]:
        """
        Парсить Daily Schedule API відповідь
        
        API повертає структуру:
        {
            "components": [
                {
                    "template_name": "electricity-outages-daily-schedule",
                    "dailySchedule": {
                        "dnipro": {
                            "today": {
                                "title": "Понеділок, 27.01.2026 на 00:00",
                                "groups": {
                                    "1.1": [
                                        {"start": 0, "end": 4, "type": "DEFINITE_OUTAGE"},
                                        ...
                                    ]
                                }
                            }
                        }
                    }
                }
            ]
        }
        
        start/end тут в ГОДИНАХ (або десяткових, наприклад 12.5 = 12:30)
        """
        groups = {}
        schedule_date = None
        
        # Знаходимо компонент з графіком
        components = data.get("components", [])
        daily_schedule_component = None
        
        for comp in components:
            if comp.get("template_name") == "electricity-outages-daily-schedule":
                daily_schedule_component = comp
                break
        
        if not daily_schedule_component:
            print("⚠️  Daily schedule component not found")
            return groups, schedule_date
        
        daily_schedule = daily_schedule_component.get("dailySchedule", {})
        city_schedule = daily_schedule.get(self.city, {})
        day_data = city_schedule.get(day, {})
        
        if not day_data:
            print(f"⚠️  No {day} schedule for {self.city}")
            return groups, schedule_date
        
        # Витягуємо дату з title
        title = day_data.get("title", "")
        schedule_date = self._extract_date_from_title(title)
        
        # Парсимо групи
        groups_data = day_data.get("groups", {})
        
        for group_id, slots in groups_data.items():
            intervals = self._parse_hourly_slots(slots)
            if intervals:
                groups[group_id] = intervals
        
        return groups, schedule_date
    
    def _parse_hourly_slots(self, slots: List[Dict]) -> List[str]:
        """
        Конвертує годинні слоти в інтервали HH:MM-HH:MM
        
        start/end тут в годинах (можуть бути десятковими: 12.5 = 12:30)
        """
        outage_slots = [s for s in slots if s.get("type") in ("DEFINITE_OUTAGE", "Definite")]
        
        if not outage_slots:
            return []
        
        # Конвертуємо години в хвилини для уніфікації
        minute_slots = []
        for slot in outage_slots:
            start_hours = slot["start"]
            end_hours = slot["end"]
            
            start_minutes = int(start_hours * 60)
            end_minutes = int(end_hours * 60)
            
            minute_slots.append({"start": start_minutes, "end": end_minutes})
        
        # Об'єднуємо
        merged = self._merge_slots(minute_slots)
        
        # Конвертуємо в HH:MM
        intervals = []
        for slot in merged:
            start_str = self._minutes_to_time(slot["start"])
            end_str = self._minutes_to_time(slot["end"])
            intervals.append(f"{start_str}-{end_str}")
        
        return intervals
    
    def _extract_date_from_title(self, title: str) -> Optional[str]:
        """
        Витягує дату з заголовка типу "Понеділок, 27.01.2026 на 00:00"
        """
        import re
        
        # Шукаємо дату у форматі DD.MM.YYYY
        match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', title)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            return f"{day:02d}.{month:02d}.{year}"
        
        return None
    
    def fetch_schedule(self, day: str = "today", api: str = "planned") -> Dict[str, Any]:
        """
        Отримує та парсить графік
        
        Args:
            day: "today" або "tomorrow"
            api: "planned" (Planned Outages API) або "daily" (Daily Schedule API)
            
        Returns:
            {
                "date": "DD.MM.YYYY",
                "timezone": "Europe/Kyiv",
                "groups": {"1.1": ["HH:MM-HH:MM", ...], ...},
                "source_api": "planned" | "daily"
            }
        """
        try:
            if api == "planned":
                raw_data = self.client.get_planned_outages()
                groups, schedule_date = self.parse_planned_outages(raw_data, day)
            else:
                raw_data = self.client.get_daily_schedule()
                groups, schedule_date = self.parse_daily_schedule(raw_data, day)
            
            # Якщо дату не вдалося витягти - використовуємо сьогодні/завтра
            if not schedule_date:
                from datetime import timedelta
                today = date.today()
                if day == "tomorrow":
                    schedule_date = (today + timedelta(days=1)).strftime("%d.%m.%Y")
                else:
                    schedule_date = today.strftime("%d.%m.%Y")
            
            return {
                "date": schedule_date,
                "timezone": TIMEZONE_NAME,
                "groups": groups,
                "source_api": api,
            }
            
        except requests.RequestException as e:
            print(f"❌ API request failed: {e}")
            raise
        except (KeyError, TypeError) as e:
            print(f"❌ Failed to parse API response: {e}")
            raise


# ═══════════════════════════════════════════════════════════════════════════════
# ДОПОМІЖНІ ФУНКЦІЇ
# ═══════════════════════════════════════════════════════════════════════════════

def load_existing_schedule(path: str) -> Dict:
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
    # Видаляємо service поля перед збереженням
    output = {
        "date": schedule["date"],
        "timezone": schedule["timezone"],
        "groups": schedule["groups"],
    }
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Schedule saved to {path}")


def compare_schedules(old: Dict, new: Dict) -> bool:
    """Порівнює графіки, повертає True якщо є зміни"""
    old_groups = old.get("groups", {})
    new_groups = new.get("groups", {})
    old_date = old.get("date")
    new_date = new.get("date")
    
    return old_groups != new_groups or old_date != new_date


def print_schedule(schedule: Dict) -> None:
    """Виводить графік у консоль"""
    print(f"\n📊 Schedule for {schedule['date']}")
    print(f"   Timezone: {schedule['timezone']}")
    print(f"   Groups: {len(schedule['groups'])}")
    print()
    
    for group_id in sorted(schedule['groups'].keys()):
        intervals = schedule['groups'][group_id]
        print(f"  {group_id}: {intervals}")


# ═══════════════════════════════════════════════════════════════════════════════
# ГОЛОВНА ФУНКЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Головна функція"""
    import argparse
    
    parser = argparse.ArgumentParser(description="YASNO Schedule Parser")
    parser.add_argument("--city", default=CITY, choices=["dnipro", "kyiv"],
                       help="City to fetch schedule for")
    parser.add_argument("--day", default="today", choices=["today", "tomorrow"],
                       help="Day to fetch")
    parser.add_argument("--api", default="planned", choices=["planned", "daily"],
                       help="API to use (planned = Planned Outages API, daily = Daily Schedule API)")
    parser.add_argument("--output", default=SCHEDULE_PATH,
                       help="Output JSON file path")
    parser.add_argument("--force", action="store_true",
                       help="Force save even if no changes")
    parser.add_argument("--dry-run", action="store_true",
                       help="Don't save, just print")
    
    args = parser.parse_args()
    
    print(f"🚀 YASNO Schedule Parser")
    print(f"   City: {args.city}")
    print(f"   Day: {args.day}")
    print(f"   API: {args.api}")
    print()
    
    try:
        # Створюємо парсер і отримуємо графік
        schedule_parser = YasnoScheduleParser(args.city)
        schedule = schedule_parser.fetch_schedule(day=args.day, api=args.api)
        
        # Виводимо результат
        print_schedule(schedule)
        
        if args.dry_run:
            print("\n🔍 Dry run mode - not saving")
            return
        
        # Перевіряємо зміни
        existing = load_existing_schedule(args.output)
        has_changes = compare_schedules(existing, schedule)
        
        if not has_changes and not args.force:
            print("\n✅ No changes detected")
            return
        
        if has_changes:
            old_date = existing.get("date", "N/A")
            new_date = schedule["date"]
            print(f"\n📝 Changes detected!")
            if old_date != new_date:
                print(f"   Date: {old_date} → {new_date}")
        
        # Зберігаємо
        save_schedule(schedule, args.output)
        print("\n✅ Update completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()
