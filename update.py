#!/usr/bin/env python3
"""
YASNO Schedule Parser - парсит графік відключень з static.yasno.ua
"""

import os
import re
import json
import time
from datetime import datetime, date
from typing import Dict, List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

YASNO_URL = "https://static.yasno.ua/dnipro/outages"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = "Europe/Kyiv"

# Маппинг черг на групи (черга → група.підгрупа)
QUEUE_TO_GROUP = {
    "11": "1.1",
    "12": "1.2",
    "21": "2.1",
    "22": "2.2",
    "31": "3.1",
    "32": "3.2",
    "41": "4.1",
    "42": "4.2",
    "51": "5.1",
    "52": "5.2",
    "61": "6.1",
    "62": "6.2",
}


# ═══════════════════════════════════════════════════════════════════════════════
# SELENIUM SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def setup_driver():
    """Налаштовує headless Chrome драйвер"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСИНГ ГРАФІКА
# ═══════════════════════════════════════════════════════════════════════════════

def parse_yasno_schedule(driver) -> Dict[str, List[str]]:
    """
    Парсить графік з YASNO сторінки
    
    Returns:
        Словарь {group_id: [intervals]}
    """
    print(f"🌐 Loading {YASNO_URL}...")
    driver.get(YASNO_URL)
    
    # Чекаємо завантаження таблиці
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table, .schedule, [class*='grid']")))
    
    time.sleep(3)  # Додатковий час для JavaScript
    
    print("📊 Parsing schedule grid...")
    
    # Шукаємо таблицю або сітку
    try:
        # Спробуємо знайти всі рядки з чергами
        rows = driver.find_elements(By.CSS_SELECTOR, "tr, [class*='row']")
        
        groups = {}
        
        for row in rows:
            try:
                # Шукаємо номер черги (11, 12, 21, ...)
                queue_element = row.find_element(By.CSS_SELECTOR, "[class*='queue'], td:first-child, div:first-child")
                queue_text = queue_element.text.strip()
                
                # Перевіряємо чи це черга
                if not re.match(r'^\d{2}$', queue_text):
                    continue
                
                queue_id = queue_text
                group_id = QUEUE_TO_GROUP.get(queue_id)
                
                if not group_id:
                    print(f"⚠️  Unknown queue: {queue_id}")
                    continue
                
                print(f"  Processing queue {queue_id} → group {group_id}")
                
                # Шукаємо всі клітинки з часом
                cells = row.find_elements(By.CSS_SELECTOR, "td, div[class*='cell']")
                
                # Збираємо години з відключеннями (позначені X або іконкою)
                outage_hours = []
                
                for i, cell in enumerate(cells[1:], start=0):  # Пропускаємо першу колонку (номер черги)
                    cell_text = cell.text.strip()
                    cell_class = cell.get_attribute("class") or ""
                    
                    # Перевіряємо наявність X або спеціальних класів
                    has_outage = (
                        'X' in cell_text or
                        '×' in cell_text or
                        'outage' in cell_class.lower() or
                        'off' in cell_class.lower() or
                        'disabled' in cell_class.lower() or
                        cell.find_elements(By.CSS_SELECTOR, "svg, img")
                    )
                    
                    if has_outage:
                        outage_hours.append(i)
                
                # Конвертуємо години в інтервали
                intervals = hours_to_intervals(outage_hours)
                
                if intervals:
                    groups[group_id] = intervals
                    print(f"    ✅ {group_id}: {intervals}")
                
            except Exception as e:
                continue
        
        if not groups:
            raise RuntimeError("No schedule data parsed from page")
        
        return groups
        
    except Exception as e:
        print(f"❌ Failed to parse schedule: {e}")
        
        # Виводимо HTML для дебагу
        print("\n📄 Page source (first 2000 chars):")
        print(driver.page_source[:2000])
        
        raise


def hours_to_intervals(hours: List[int]) -> List[str]:
    """
    Конвертує список годин у інтервали HH:MM-HH:MM
    
    Args:
        hours: Список годин відключення (0-23)
        
    Returns:
        Список інтервалів ["HH:MM-HH:MM", ...]
    """
    if not hours:
        return []
    
    hours = sorted(set(hours))
    intervals = []
    
    start = hours[0]
    prev = hours[0]
    
    for hour in hours[1:]:
        # Якщо розрив більше 1 години - новий інтервал
        if hour - prev > 1:
            # Завершуємо попередній інтервал
            end = prev + 1
            if end == 24:
                intervals.append(f"{start:02d}:00-24:00")
            else:
                intervals.append(f"{start:02d}:00-{end:02d}:00")
            
            start = hour
        
        prev = hour
    
    # Додаємо останній інтервал
    end = prev + 1
    if end == 24:
        intervals.append(f"{start:02d}:00-24:00")
    else:
        intervals.append(f"{start:02d}:00-{end:02d}:00")
    
    return intervals


# ═══════════════════════════════════════════════════════════════════════════════
# ВИЗНАЧЕННЯ ДАТИ
# ═══════════════════════════════════════════════════════════════════════════════

def extract_date_from_page(driver) -> str:
    """
    Витягує дату з сторінки YASNO
    
    Returns:
        Дата в форматі DD.MM.YYYY
    """
    try:
        # Шукаємо дату на сторінці
        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        # Формат: "Сьогодні, 25 січня" або "Завтра, 26 січня"
        date_patterns = [
            r'(\d{1,2})\s+(січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня)',
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
            r'(\d{1,2})\.(\d{1,2})',
        ]
        
        months_ua = {
            'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4,
            'травня': 5, 'червня': 6, 'липня': 7, 'серпня': 8,
            'вересня': 9, 'жовтня': 10, 'листопада': 11, 'грудня': 12,
        }
        
        for pattern in date_patterns:
            match = re.search(pattern, page_text.lower())
            if match:
                if len(match.groups()) == 2 and match.group(2) in months_ua:
                    # Формат: "25 січня"
                    day = int(match.group(1))
                    month = months_ua[match.group(2)]
                    year = datetime.now().year
                    return f"{day:02d}.{month:02d}.{year}"
                
                elif len(match.groups()) == 3:
                    # Формат: "25.01.2026"
                    day = int(match.group(1))
                    month = int(match.group(2))
                    year = int(match.group(3))
                    return f"{day:02d}.{month:02d}.{year}"
                
                elif len(match.groups()) == 2:
                    # Формат: "25.01"
                    day = int(match.group(1))
                    month = int(match.group(2))
                    year = datetime.now().year
                    return f"{day:02d}.{month:02d}.{year}"
        
        # Якщо не знайшли - беремо сьогодні
        today = date.today()
        return today.strftime("%d.%m.%Y")
        
    except Exception as e:
        print(f"⚠️  Failed to extract date: {e}")
        today = date.today()
        return today.strftime("%d.%m.%Y")


# ═══════════════════════════════════════════════════════════════════════════════
# ЗБЕРЕЖЕННЯ
# ═══════════════════════════════════════════════════════════════════════════════

def save_schedule(groups: Dict[str, List[str]], date_str: str) -> None:
    """Зберігає графік в JSON"""
    data = {
        "date": date_str,
        "timezone": TIMEZONE_NAME,
        "groups": groups
    }
    
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Schedule saved to {SCHEDULE_PATH}")
    print(f"   Date: {date_str}")
    print(f"   Groups: {len(groups)}")


def load_existing() -> Dict:
    """Завантажує існуючий графік"""
    if not os.path.exists(SCHEDULE_PATH):
        return {}
    
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════════
# ГОЛОВНА ФУНКЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Головна функція парсингу"""
    driver = None
    
    try:
        print("🚀 Starting YASNO schedule parser...")
        
        # Налаштовуємо драйвер
        driver = setup_driver()
        
        # Парсимо графік
        groups = parse_yasno_schedule(driver)
        
        # Витягуємо дату
        date_str = extract_date_from_page(driver)
        
        print(f"\n📊 Parsed schedule for {date_str}")
        print(f"   Groups: {len(groups)}")
        
        # Показуємо деталі
        print("\n📋 Schedule details:")
        for group_id in sorted(groups.keys()):
            intervals = groups[group_id]
            print(f"  {group_id}: {intervals}")
        
        # Порівнюємо з існуючим
        existing = load_existing()
        old_groups = existing.get("groups", {})
        old_date = existing.get("date")
        
        groups_changed = old_groups != groups
        date_changed = old_date != date_str
        
        if not groups_changed and not date_changed:
            print("\n✅ No changes detected")
            return
        
        if groups_changed:
            print(f"\n📝 Groups changed!")
        
        if date_changed:
            print(f"📅 Date changed: {old_date} → {date_str}")
        
        # Зберігаємо
        save_schedule(groups, date_str)
        
        print("\n✅ Update completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
