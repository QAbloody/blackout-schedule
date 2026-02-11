#!/usr/bin/env python3
"""
DTEK Schedule Parser
Парсить графіки відключень через API dtek-dnem.com.ua
"""

import os
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

API_URL = "https://www.dtek-dnem.com.ua/ua/ajax"
CITY = "м. Дніпро"
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

# Еталонні адреси для кожної групи
# Формат: "група": ("вулиця", "будинок")
GROUP_ADDRESSES = {
    "1.1": ("пров. Парковий", "1"),
    "1.2": ("вул. Мохова", "1"),
    "3.1": ("вул. Центральна", "1"),
    "3.2": ("вул. Холодильна", "1"),
    "5.1": ("пров. Морський", "1"),
    "5.2": ("вул. Автодорожна", "1"),
    # Додай після знаходження:
    # "2.1": ("вул. ???", "1"),
    # "2.2": ("вул. ???", "1"),
    # "4.1": ("вул. ???", "1"),
    # "4.2": ("вул. ???", "1"),
    # "6.1": ("вул. ???", "1"),
    # "6.2": ("вул. ???", "1"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# API ФУНКЦІЇ
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_street_data(street: str) -> Optional[Dict]:
    """Запитує дані по вулиці"""
    try:
        data = {
            "method": "getHomeNum",
            "data[0][name]": "city",
            "data[0][value]": CITY,
            "data[1][name]": "street",
            "data[1][value]": street,
            "data[2][name]": "updateFact",
            "data[2][value]": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
        
        r = requests.post(API_URL, data=data, timeout=15)
        r.raise_for_status()
        result = r.json()
        
        if result.get("result") and result.get("data"):
            return result
        return None
        
    except Exception as e:
        print(f"  ❌ API Error: {e}")
        return None


def parse_outages(api_data: Dict, target_group: str) -> List[Dict]:
    """
    Парсить відключення для конкретної групи
    Повертає список: [{"start": "HH:MM DD.MM.YYYY", "end": "...", "type": "..."}]
    """
    outages = []
    
    if not api_data or not api_data.get("data"):
        return outages
    
    target_gpv = f"GPV{target_group}"
    
    for house, info in api_data["data"].items():
        reasons = info.get("sub_type_reason", [])
        
        if target_gpv in reasons:
            start = info.get("start_date", "")
            end = info.get("end_date", "")
            sub_type = info.get("sub_type", "")
            
            if start and end:
                outages.append({
                    "start": start,
                    "end": end,
                    "type": sub_type,
                    "house": house
                })
    
    return outages


def outages_to_intervals(outages: List[Dict], target_date: str) -> List[str]:
    """
    Конвертує відключення в інтервали для конкретної дати
    target_date: "DD.MM.YYYY"
    Повертає: ["08:00-12:00", "16:00-20:00"]
    """
    intervals = []
    
    for outage in outages:
        try:
            # Парсимо дати: "HH:MM DD.MM.YYYY"
            start_str = outage["start"]
            end_str = outage["end"]
            
            start_time, start_date = start_str.split(" ")
            end_time, end_date = end_str.split(" ")
            
            # Перевіряємо чи відключення стосується цільової дати
            if start_date == target_date or end_date == target_date:
                # Якщо початок раніше цільової дати — починаємо з 00:00
                if start_date < target_date:
                    start_time = "00:00"
                # Якщо кінець пізніше цільової дати — закінчуємо о 24:00
                if end_date > target_date:
                    end_time = "24:00"
                
                intervals.append(f"{start_time}-{end_time}")
                
        except Exception as e:
            print(f"  ⚠️ Parse error: {e}")
    
    return merge_intervals(intervals)


def merge_intervals(intervals: List[str]) -> List[str]:
    """Об'єднує перекриваючі інтервали"""
    if not intervals:
        return []
    
    # Конвертуємо в хвилини
    mins = []
    for iv in intervals:
        try:
            start, end = iv.split("-")
            sh, sm = map(int, start.split(":"))
            eh, em = map(int, end.split(":"))
            mins.append((sh * 60 + sm, eh * 60 + em))
        except:
            continue
    
    if not mins:
        return []
    
    # Сортуємо і об'єднуємо
    mins.sort()
    merged = [mins[0]]
    
    for start, end in mins[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    
    # Конвертуємо назад
    result = []
    for start, end in merged:
        sh, sm = divmod(start, 60)
        eh, em = divmod(end, 60)
        result.append(f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}")
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🚀 DTEK Schedule Parser")
    print("=" * 60)
    
    now = datetime.now()
    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")
    
    print(f"\n📅 Сьогодні: {today}")
    print(f"📅 Завтра: {tomorrow}")
    print(f"📋 Груп: {len(GROUP_ADDRESSES)}\n")
    
    result = {
        "timezone": "Europe/Kyiv",
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "dtek-dnem.com.ua",
        "emergency": None,
        "today": {"date": today, "groups": {}},
        "tomorrow": {"date": tomorrow, "groups": {}}
    }
    
    # Збираємо дані по кожній групі
    for group, (street, house) in GROUP_ADDRESSES.items():
        print(f"📍 Група {group}: {street}...")
        
        api_data = fetch_street_data(street)
        
        if not api_data:
            print(f"  ⚠️ Немає даних")
            continue
        
        # Перевіряємо екстрені відключення
        update_ts = api_data.get("updateTimestamp", "")
        
        # Парсимо відключення
        outages = parse_outages(api_data, group)
        
        if outages:
            print(f"  ✅ Знайдено {len(outages)} відключень")
            
            # Конвертуємо в інтервали
            today_intervals = outages_to_intervals(outages, today)
            tomorrow_intervals = outages_to_intervals(outages, tomorrow)
            
            if today_intervals:
                result["today"]["groups"][group] = today_intervals
                print(f"     Сьогодні: {today_intervals}")
            
            if tomorrow_intervals:
                result["tomorrow"]["groups"][group] = tomorrow_intervals
                print(f"     Завтра: {tomorrow_intervals}")
        else:
            print(f"  ✅ Відключень немає")
    
    # Зберігаємо
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Збережено: {SCHEDULE_FILE}")
    
    # Підсумок
    print("\n" + "=" * 60)
    print("📊 ПІДСУМОК:")
    today_count = len(result["today"]["groups"])
    tomorrow_count = len(result["tomorrow"]["groups"])
    print(f"  Сьогодні: {today_count} груп з відключеннями")
    print(f"  Завтра: {tomorrow_count} груп з відключеннями")
    print("=" * 60)


if __name__ == "__main__":
    main()
