#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсить графік з static.yasno.ua
Підтримує today і tomorrow
"""

import os
import sys
import json
import re
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


YASNO_URL = "https://static.yasno.ua/dnipro/outages"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    return webdriver.Chrome(options=options)


def minutes_to_intervals(minutes: List[int]) -> List[str]:
    if not minutes:
        return []
    
    minutes = sorted(set(minutes))
    intervals = []
    start = minutes[0]
    prev = minutes[0]
    
    for m in minutes[1:]:
        if m - prev > 30:
            end = prev + 30
            intervals.append(f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
            start = m
        prev = m
    
    end = prev + 30
    if end > 24 * 60:
        end = 24 * 60
    intervals.append(f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
    return intervals


def parse_table(driver) -> Dict[str, List[str]]:
    """Парсить поточну таблицю на сторінці"""
    groups = {}
    rows = driver.find_elements(By.CSS_SELECTOR, "[class*='_row_']")
    
    for row in rows:
        try:
            row_text = row.text.strip()
            
            group_id = None
            for g in ALL_GROUPS:
                if row_text.startswith(g) or f"\n{g}\n" in f"\n{row_text}\n":
                    group_id = g
                    break
            
            if not group_id:
                continue
            
            cells = row.find_elements(By.CSS_SELECTOR, "[class*='_cell_']")
            outage_minutes = []
            hour = 0
            
            for cell in cells:
                cell_text = cell.text.strip()
                if cell_text in ALL_GROUPS:
                    continue
                
                cell_html = cell.get_attribute("innerHTML")
                
                if "_definite_" in cell_html:
                    has_first_half = False
                    has_second_half = False
                    
                    # Debug для групи 1.1
                    if group_id == "1.1" and hour < 6:
                        has_50 = "50%" in cell_html
                        has_left0 = "left: 0%" in cell_html or "left:0%" in cell_html
                        has_left50 = "left: 50%" in cell_html or "left:50%" in cell_html
                        print(f"      DEBUG {hour}:00 - 50%={has_50}, left0={has_left0}, left50={has_left50}")
                    
                    has_half_width = "50%" in cell_html
                    
                    if has_half_width:
                        if "left: 0%" in cell_html or "left:0%" in cell_html:
                            has_first_half = True
                        if "left: 50%" in cell_html or "left:50%" in cell_html:
                            has_second_half = True
                    else:
                        has_first_half = True
                        has_second_half = True
                    
                    if has_first_half:
                        outage_minutes.append(hour * 60)
                    if has_second_half:
                        outage_minutes.append(hour * 60 + 30)
                
                hour += 1
                if hour >= 24:
                    break
            
            if outage_minutes:
                groups[group_id] = minutes_to_intervals(outage_minutes)
        except:
            pass
    
    return groups


def parse_schedule(driver) -> Dict[str, Any]:
    """Парсить графік на сьогодні і завтра"""
    print(f"📡 Loading: {YASNO_URL}")
    driver.get(YASNO_URL)
    
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='_row_']")))
    time.sleep(2)
    
    # Парсимо сьогодні
    print("📅 Parsing today...")
    today_groups = parse_table(driver)
    today_date = date.today().strftime("%d.%m.%Y")
    print(f"   Date: {today_date}, Groups: {len(today_groups)}")
    for g in sorted(today_groups.keys()):
        print(f"   {g}: {today_groups[g]}")
    
    # Клікаємо на "Завтра"
    print("\n📅 Parsing tomorrow...")
    tomorrow_groups = {}
    tomorrow_date = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
    
    try:
        # Шукаємо кнопку по id або по тексту
        try:
            tomorrow_btn = driver.find_element(By.CSS_SELECTOR, "[id*='tomorrow']")
        except:
            tomorrow_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Завтра')]")
        
        tomorrow_btn.click()
        time.sleep(2)
        tomorrow_groups = parse_table(driver)
        print(f"   Date: {tomorrow_date}, Groups: {len(tomorrow_groups)}")
        for g in sorted(tomorrow_groups.keys()):
            print(f"   {g}: {tomorrow_groups[g]}")
    except Exception as e:
        print(f"   ⚠️ Tomorrow not available")
    
    return {
        "timezone": TIMEZONE_NAME,
        "today": {
            "date": today_date,
            "groups": today_groups,
        },
        "tomorrow": {
            "date": tomorrow_date,
            "groups": tomorrow_groups,
        },
    }


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
    print(f"\n💾 Saved to {path}")


def schedules_differ(old: Dict, new: Dict) -> bool:
    return (
        old.get("today") != new.get("today") or
        old.get("tomorrow") != new.get("tomorrow")
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", default=SCHEDULE_PATH)
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args()
    
    print("🚀 YASNO Schedule Parser\n")
    
    driver = None
    try:
        driver = setup_driver()
        schedule = parse_schedule(driver)
        
        if not schedule['today']['groups']:
            print("\n⚠️ No today data!")
            return 1
        
        if args.dry_run:
            print("\n🔍 Dry run")
            return 0
        
        existing = load_existing(args.output)
        if not schedules_differ(existing, schedule) and not args.force:
            print("\n✅ No changes")
            return 0
        
        save_schedule(schedule, args.output)
        print("✅ Done!")
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
