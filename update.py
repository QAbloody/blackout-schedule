#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсить графік з static.yasno.ua через Selenium
"""

import os
import sys
import json
import re
from datetime import datetime, date
from typing import Dict, List, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
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
    """Налаштовує headless Chrome"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=options)
    return driver


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСЕР
# ═══════════════════════════════════════════════════════════════════════════════

def hours_to_interval(hours: List[int]) -> List[str]:
    """Конвертує список годин в інтервали"""
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
    
    # Останній інтервал
    end = prev + 1
    intervals.append(f"{start:02d}:00-{end:02d}:00" if end < 24 else f"{start:02d}:00-24:00")
    
    return intervals


def parse_schedule(driver) -> Dict[str, Any]:
    """Парсить графік зі сторінки"""
    print(f"📡 Loading: {YASNO_URL}")
    driver.get(YASNO_URL)
    
    # Чекаємо завантаження
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    
    import time
    time.sleep(3)  # Даємо JS відпрацювати
    
    groups = {}
    schedule_date = date.today().strftime("%d.%m.%Y")
    
    # Шукаємо дату на сторінці
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        # Шукаємо "Сьогодні, 26 січня" або подібне
        months_ua = {
            'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4,
            'травня': 5, 'червня': 6, 'липня': 7, 'серпня': 8,
            'вересня': 9, 'жовтня': 10, 'листопада': 11, 'грудня': 12,
        }
        
        for month_name, month_num in months_ua.items():
            match = re.search(rf'(\d{{1,2}})\s+{month_name}', page_text.lower())
            if match:
                day = int(match.group(1))
                year = datetime.now().year
                schedule_date = f"{day:02d}.{month_num:02d}.{year}"
                print(f"📅 Found date: {schedule_date}")
                break
    except Exception as e:
        print(f"⚠️  Could not extract date: {e}")
    
    # Парсимо таблицю
    # Шукаємо всі рядки з групами (1.1, 1.2, тощо)
    try:
        # Знаходимо всі елементи на сторінці
        all_elements = driver.find_elements(By.XPATH, "//*")
        
        print(f"🔍 Scanning page for schedule data...")
        
        # Шукаємо елементи що містять номери груп
        for group_id in ALL_GROUPS:
            try:
                # Шукаємо елемент з текстом групи
                group_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{group_id}')]")
                
                for group_el in group_elements:
                    # Знаходимо батьківський рядок
                    try:
                        parent = group_el.find_element(By.XPATH, "./..")
                        row_text = parent.text
                        
                        # Якщо рядок містить тільки номер групи - шукаємо вище
                        if len(row_text.strip()) < 10:
                            parent = parent.find_element(By.XPATH, "./..")
                            row_text = parent.text
                        
                        # Шукаємо всі дочірні елементи (клітинки)
                        cells = parent.find_elements(By.XPATH, ".//*")
                        
                        outage_hours = []
                        
                        for i, cell in enumerate(cells):
                            # Перевіряємо чи є іконка відключення (svg або специфічний клас)
                            try:
                                cell_html = cell.get_attribute("outerHTML")
                                cell_class = cell.get_attribute("class") or ""
                                
                                # Шукаємо ознаки відключення
                                has_outage = (
                                    "svg" in cell_html.lower() or
                                    "outage" in cell_class.lower() or
                                    "off" in cell_class.lower() or
                                    "×" in cell.text or
                                    "✕" in cell.text
                                )
                                
                                if has_outage and i < 24:
                                    outage_hours.append(i)
                            except:
                                pass
                        
                        if outage_hours:
                            intervals = hours_to_interval(outage_hours)
                            if intervals:
                                groups[group_id] = intervals
                                print(f"   {group_id}: {intervals}")
                                break
                    except:
                        pass
            except:
                pass
        
        # Альтернативний метод - парсимо через JavaScript
        if not groups:
            print("🔍 Trying JavaScript extraction...")
            
            js_result = driver.execute_script("""
                const result = {};
                const groups = ['1.1', '1.2', '2.1', '2.2', '3.1', '3.2', '4.1', '4.2', '5.1', '5.2', '6.1', '6.2'];
                
                // Шукаємо таблицю або grid
                const tables = document.querySelectorAll('table, [class*="grid"], [class*="schedule"]');
                
                for (const table of tables) {
                    const rows = table.querySelectorAll('tr, [class*="row"]');
                    
                    for (const row of rows) {
                        const text = row.textContent;
                        
                        for (const group of groups) {
                            if (text.includes(group) && !result[group]) {
                                const cells = row.querySelectorAll('td, [class*="cell"]');
                                const hours = [];
                                
                                cells.forEach((cell, i) => {
                                    // Перевіряємо наявність SVG або певних класів
                                    if (cell.querySelector('svg') || 
                                        cell.classList.toString().includes('outage') ||
                                        cell.classList.toString().includes('off')) {
                                        if (i > 0 && i <= 24) hours.push(i - 1);
                                    }
                                });
                                
                                if (hours.length > 0) {
                                    result[group] = hours;
                                }
                            }
                        }
                    }
                }
                
                return result;
            """)
            
            if js_result:
                for group_id, hours in js_result.items():
                    intervals = hours_to_interval(hours)
                    if intervals:
                        groups[group_id] = intervals
                        print(f"   {group_id}: {intervals}")
        
    except Exception as e:
        print(f"❌ Parse error: {e}")
        
        # Зберігаємо HTML для дебагу
        try:
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("📄 Saved debug_page.html")
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
    
    print("🚀 YASNO Schedule Parser (Selenium)")
    print()
    
    driver = None
    try:
        driver = setup_driver()
        schedule = parse_schedule(driver)
        
        print(f"\n📊 Schedule for {schedule['date']}")
        print(f"   Groups: {len(schedule['groups'])}")
        
        if not schedule['groups']:
            print("\n⚠️  No schedule data parsed!")
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
