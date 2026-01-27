#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсить графік з static.yasno.ua
Структура: CSS Grid з класами _row_, _cell_, _iconContainer_ (відключення)
"""

import os
import sys
import json
import re
import time
from datetime import datetime, date
from typing import Dict, List, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

YASNO_URL = "https://static.yasno.ua/dnipro/outages"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


# ═══════════════════════════════════════════════════════════════════════════════
# SELENIUM
# ═══════════════════════════════════════════════════════════════════════════════

def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    return webdriver.Chrome(options=options)


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСЕР
# ═══════════════════════════════════════════════════════════════════════════════

def minutes_to_intervals(minutes: List[int]) -> List[str]:
    """Конвертує список хвилин в інтервали HH:MM-HH:MM"""
    if not minutes:
        return []
    
    minutes = sorted(set(minutes))
    intervals = []
    
    start = minutes[0]
    prev = minutes[0]
    
    for m in minutes[1:]:
        # Якщо розрив більше 30 хвилин - новий інтервал
        if m - prev > 30:
            end = prev + 30
            intervals.append(f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
            start = m
        prev = m
    
    # Останній інтервал
    end = prev + 30
    if end > 24 * 60:
        end = 24 * 60
    intervals.append(f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
    
    return intervals


def hours_to_intervals(hours: List[int]) -> List[str]:
    """Конвертує список годин в інтервали HH:00-HH:00"""
    if not hours:
        return []
    
    hours = sorted(set(hours))
    intervals = []
    
    start = hours[0]
    prev = hours[0]
    
    for h in hours[1:]:
        if h - prev > 1:
            end = prev + 1
            intervals.append(f"{start:02d}:00-{end:02d}:00" if end < 24 else f"{start:02d}:00-24:00")
            start = h
        prev = h
    
    end = prev + 1
    intervals.append(f"{start:02d}:00-{end:02d}:00" if end < 24 else f"{start:02d}:00-24:00")
    
    return intervals


def parse_schedule(driver) -> Dict[str, Any]:
    """Парсить графік зі сторінки YASNO"""
    print(f"📡 Loading: {YASNO_URL}")
    driver.get(YASNO_URL)
    
    # Чекаємо завантаження React
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='_row_']")))
    time.sleep(2)
    
    groups = {}
    schedule_date = date.today().strftime("%d.%m.%Y")
    
    # Витягуємо дату з кнопки "Сьогодні, 27 січня"
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
        months = {
            'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4,
            'травня': 5, 'червня': 6, 'липня': 7, 'серпня': 8,
            'вересня': 9, 'жовтня': 10, 'листопада': 11, 'грудня': 12,
        }
        
        # Шукаємо "Сьогодні, XX місяця" або "сьогодні, XX місяця"
        for month_name, month_num in months.items():
            match = re.search(rf'[Сс]ьогодні[,\s]+(\d{{1,2}})\s+{month_name}', page_text)
            if match:
                day = int(match.group(1))
                year = datetime.now().year
                schedule_date = f"{day:02d}.{month_num:02d}.{year}"
                print(f"📅 Date: {schedule_date}")
                break
        else:
            # Якщо не знайшли "Сьогодні" - беремо поточну дату
            schedule_date = date.today().strftime("%d.%m.%Y")
            print(f"📅 Date (today): {schedule_date}")
    except Exception as e:
        print(f"⚠️  Date extraction failed: {e}")
        schedule_date = date.today().strftime("%d.%m.%Y")
    
    # Знаходимо всі рядки таблиці
    rows = driver.find_elements(By.CSS_SELECTOR, "[class*='_row_']")
    print(f"🔍 Found {len(rows)} rows")
    
    for row in rows:
        try:
            # Шукаємо номер групи в рядку
            row_text = row.text.strip()
            
            group_id = None
            for g in ALL_GROUPS:
                if row_text.startswith(g) or f"\n{g}\n" in f"\n{row_text}\n":
                    group_id = g
                    break
            
            if not group_id:
                continue
            
            # Знаходимо всі клітинки в рядку
            cells = row.find_elements(By.CSS_SELECTOR, "[class*='_cell_']")
            
            outage_minutes = []
            hour = 0
            
            for cell in cells:
                # Пропускаємо клітинку з номером групи (перша)
                cell_text = cell.text.strip()
                if cell_text in ALL_GROUPS:
                    continue
                
                # Перевіряємо чи є клас _definite_ (реальне відключення)
                cell_html = cell.get_attribute("innerHTML")
                
                if "_definite_" in cell_html:
                    # Перевіряємо width і left для визначення половинок
                    # width: 100% = повна година
                    # width: 50% + left: 0% = перші 30 хв
                    # width: 50% + left: 50% = другі 30 хв
                    
                    has_first_half = False
                    has_second_half = False
                    
                    # Шукаємо всі iconContainer з _definite_
                    if "width: 100%" in cell_html or "width:100%" in cell_html:
                        # Повна година
                        has_first_half = True
                        has_second_half = True
                    else:
                        # Перевіряємо половинки
                        # left: 0% = перша половина
                        # left: 50% = друга половина
                        if "left: 0%" in cell_html or "left:0%" in cell_html:
                            has_first_half = True
                        if "left: 50%" in cell_html or "left:50%" in cell_html:
                            has_second_half = True
                    
                    if has_first_half:
                        outage_minutes.append(hour * 60)  # XX:00
                    if has_second_half:
                        outage_minutes.append(hour * 60 + 30)  # XX:30
                
                hour += 1
                if hour >= 24:
                    break
            
            if outage_minutes:
                intervals = minutes_to_intervals(outage_minutes)
                groups[group_id] = intervals
                print(f"   {group_id}: {intervals}")
            else:
                print(f"   {group_id}: no outages")
                
        except Exception as e:
            print(f"⚠️  Row parse error: {e}")
    
    # Зберігаємо HTML для дебагу якщо нічого не знайшли
    if not groups:
        print("⚠️  No groups parsed, saving debug HTML...")
        try:
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        except:
            pass
    
    return {
        "date": schedule_date,
        "timezone": TIMEZONE_NAME,
        "groups": groups,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ФАЙЛИ
# ═══════════════════════════════════════════════════════════════════════════════

def load_existing(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_schedule(schedule: Dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved to {path}")


def schedules_differ(old: Dict, new: Dict) -> bool:
    return (
        old.get("groups", {}) != new.get("groups", {}) or
        old.get("date") != new.get("date")
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", default=SCHEDULE_PATH)
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args()
    
    print("🚀 YASNO Schedule Parser")
    print()
    
    driver = None
    try:
        driver = setup_driver()
        schedule = parse_schedule(driver)
        
        print(f"\n📊 Schedule for {schedule['date']}")
        print(f"   Groups with outages: {len(schedule['groups'])}")
        
        if not schedule['groups']:
            print("\n⚠️  No data parsed!")
            return 1
        
        if args.dry_run:
            print("\n🔍 Dry run")
            return 0
        
        existing = load_existing(args.output)
        if not schedules_differ(existing, schedule) and not args.force:
            print("\n✅ No changes")
            return 0
        
        save_schedule(schedule, args.output)
        print("\n✅ Done!")
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    sys.exit(main())
