#!/usr/bin/env python3
"""
YASNO Schedule Parser
Парсить графіки відключень з static.yasno.ua для Дніпра
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

YASNO_URL = "https://static.yasno.ua/dnipro/outages"
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")
TIMEZONE = "Europe/Kyiv"

ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", 
              "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]


# ═══════════════════════════════════════════════════════════════════════════════
# ДОПОМІЖНІ ФУНКЦІЇ
# ═══════════════════════════════════════════════════════════════════════════════

def setup_driver() -> webdriver.Chrome:
    """Налаштовує Chrome WebDriver"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    return webdriver.Chrome(options=options)


def minutes_to_intervals(minutes: List[int]) -> List[str]:
    """
    Конвертує список хвилин у інтервали
    [0, 30, 60, 120, 150] → ['00:00-01:30', '02:00-03:00']
    """
    if not minutes:
        return []
    
    minutes = sorted(set(minutes))
    intervals = []
    start = minutes[0]
    prev = minutes[0]
    
    for m in minutes[1:]:
        # Якщо розрив більше 30 хв — новий інтервал
        if m - prev > 30:
            end = prev + 30
            intervals.append(f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
            start = m
        prev = m
    
    # Додаємо останній інтервал
    end = min(prev + 30, 24 * 60)
    intervals.append(f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}")
    
    return intervals


def parse_emergency(driver) -> Optional[str]:
    """Перевіряє чи є екстрене повідомлення на сайті"""
    try:
        # Шукаємо великий текст про екстрені відключення
        elements = driver.find_elements(By.CSS_SELECTOR, "[class*='alert'], [class*='warning'], [class*='emergency'], [class*='banner'], h1, h2, h3, div[class*='message']")
        for el in elements:
            text = el.text.strip().upper()
            if "ЕКСТРЕН" in text or "ГРАФІКИ НЕ ДІЮТЬ" in text or "НЕ ДІЮТЬ" in text:
                return el.text.strip()
        
        # Також перевіряємо весь текст сторінки
        body = driver.find_element(By.TAG_NAME, "body").text.upper()
        if "ЕКСТРЕНІ ВІДКЛЮЧЕННЯ" in body and "ГРАФІКИ НЕ ДІЮТЬ" in body:
            return "Екстрені відключення, графіки не діють"
        
        return None
    except:
        return None


def parse_table(driver) -> Dict[str, List[str]]:
    """Парсить таблицю графіку відключень"""
    groups = {}
    
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "[class*='_row_']")
        print(f"    Знайдено {len(rows)} рядків")
        
        for row in rows:
            try:
                row_text = row.text.strip()
                
                # Визначаємо групу
                group_id = None
                for g in ALL_GROUPS:
                    if row_text.startswith(g) or f"\n{g}\n" in f"\n{row_text}\n":
                        group_id = g
                        break
                
                if not group_id:
                    continue
                
                # Парсимо комірки (перша — номер групи, пропускаємо)
                cells = row.find_elements(By.CSS_SELECTOR, "[class*='_cell_']")
                time_cells = cells[1:25] if len(cells) > 24 else cells[1:]
                
                outage_minutes = []
                
                for hour, cell in enumerate(time_cells):
                    cell_html = cell.get_attribute("innerHTML") or ""
                    
                    # Шукаємо блоки з відключеннями
                    if "_definite_" not in cell_html:
                        continue
                    
                    # Парсимо кожен блок окремо
                    parts = cell_html.split("_definite_")
                    for part in parts[1:]:
                        block = part[:part.find("</div>")] if "</div>" in part else part[:200]
                        
                        # Перевіряємо ширину блоку (50% = півгодини)
                        is_half = "width: 50%" in block or "width:50%" in block
                        
                        if is_half:
                            # Визначаємо яка половина
                            if "left: 0%" in block or "left:0%" in block:
                                outage_minutes.append(hour * 60)  # перші 30 хв
                            elif "left: 50%" in block or "left:50%" in block:
                                outage_minutes.append(hour * 60 + 30)  # другі 30 хв
                        else:
                            # Повна година
                            outage_minutes.append(hour * 60)
                            outage_minutes.append(hour * 60 + 30)
                
                if outage_minutes:
                    groups[group_id] = minutes_to_intervals(outage_minutes)
                    
            except Exception as e:
                print(f"    ⚠️ Помилка рядка: {e}")
        
    except Exception as e:
        print(f"    ❌ Помилка парсингу таблиці: {e}")
    
    return groups


def click_tab(driver, tab_name: str) -> bool:
    """Клікає на вкладку (Сьогодні/Завтра)"""
    try:
        time.sleep(1)
        
        # Спочатку шукаємо по id
        tab_id = "tomorrow" if "завтра" in tab_name.lower() else "today"
        
        try:
            tab = driver.find_element(By.CSS_SELECTOR, f"button[id*='{tab_id}']")
            if tab.is_displayed():
                tab.click()
                print(f"    ✅ Натиснуто: {tab_name}")
                time.sleep(2)
                return True
        except:
            pass
        
        # Шукаємо по класу segmented
        try:
            tabs = driver.find_elements(By.CSS_SELECTOR, "button[class*='segmented'], button[class*='_option_']")
            for tab in tabs:
                if tab_name.lower() in tab.text.lower():
                    tab.click()
                    print(f"    ✅ Натиснуто: {tab.text}")
                    time.sleep(2)
                    return True
        except:
            pass
        
        # Шукаємо будь-яку кнопку з текстом
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if tab_name.lower() in btn.text.lower():
                btn.click()
                print(f"    ✅ Натиснуто: {btn.text}")
                time.sleep(2)
                return True
        
        print(f"    ⚠️ Вкладка '{tab_name}' не знайдена")
        return False
        
    except Exception as e:
        print(f"    ❌ Помилка кліку: {e}")
        return False


def get_date(is_today: bool) -> str:
    """Повертає дату у форматі DD.MM.YYYY"""
    date = datetime.now()
    if not is_today:
        date += timedelta(days=1)
    return date.strftime("%d.%m.%Y")


def save_schedule(data: Dict[str, Any], filepath: str):
    """Зберігає графік у JSON"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Збережено: {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🚀 YASNO Schedule Parser")
    print("=" * 60)
    
    # Завантажуємо попередній файл якщо є
    old_data = None
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            print(f"📂 Завантажено попередній файл")
        except:
            pass
    
    result = {
        "timezone": TIMEZONE,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "emergency": None,
        "today": {"date": "", "groups": {}},
        "tomorrow": {"date": "", "groups": {}}
    }
    
    driver = None
    
    try:
        driver = setup_driver()
        
        print(f"\n🌐 Завантаження {YASNO_URL}")
        driver.get(YASNO_URL)
        
        # Чекаємо завантаження
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='_row_'], [class*='alert'], body"))
        )
        print("✅ Сторінка завантажена")
        time.sleep(3)
        
        # Перевіряємо екстрене повідомлення
        emergency = parse_emergency(driver)
        if emergency:
            print(f"\n🚨 ЕКСТРЕНЕ ПОВІДОМЛЕННЯ: {emergency}")
            result["emergency"] = emergency
            
            # Зберігаємо старі графіки якщо є екстрене повідомлення
            if old_data:
                result["today"] = old_data.get("today", result["today"])
                result["tomorrow"] = old_data.get("tomorrow", result["tomorrow"])
                print("📋 Графіки збережено з попереднього файлу")
            
            save_schedule(result, SCHEDULE_FILE)
            print("\n" + "=" * 60)
            print("🚨 Екстрені відключення - графіки не оновлено")
            print("=" * 60)
            return
        
        # === Парсимо СЬОГОДНІ ===
        print("\n📅 Парсинг: Сьогодні")
        result["today"]["date"] = get_date(True)
        result["today"]["groups"] = parse_table(driver)
        print(f"    📊 Груп з відключеннями: {len(result['today']['groups'])}")
        
        # === Парсимо ЗАВТРА ===
        print("\n📅 Парсинг: Завтра")
        if click_tab(driver, "Завтра"):
            time.sleep(2)
            result["tomorrow"]["date"] = get_date(False)
            result["tomorrow"]["groups"] = parse_table(driver)
            print(f"    📊 Груп з відключеннями: {len(result['tomorrow']['groups'])}")
        else:
            print("    ⚠️ Графік на завтра недоступний")
        
        # Зберігаємо
        save_schedule(result, SCHEDULE_FILE)
        
        # Підсумок
        print("\n" + "=" * 60)
        print("📊 ПІДСУМОК:")
        print(f"   Сьогодні ({result['today']['date']}): {len(result['today']['groups'])} груп")
        print(f"   Завтра ({result['tomorrow']['date']}): {len(result['tomorrow']['groups'])} груп")
        
        # Детальний вивід
        if result["today"]["groups"]:
            print("\n   Сьогодні:")
            for grp, intervals in sorted(result["today"]["groups"].items()):
                total = sum(
                    (int(iv.split("-")[1].split(":")[0]) * 60 + int(iv.split("-")[1].split(":")[1])) -
                    (int(iv.split("-")[0].split(":")[0]) * 60 + int(iv.split("-")[0].split(":")[1]))
                    for iv in intervals
                )
                print(f"      {grp}: {len(intervals)} інт., {total // 60}год {total % 60:02d}хв")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ПОМИЛКА: {e}")
        import traceback
        traceback.print_exc()
        
        # Зберігаємо HTML для дебагу
        if driver:
            try:
                debug_file = "debug_page.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"📄 Debug HTML: {debug_file}")
            except:
                pass
        
        sys.exit(1)
        
    finally:
        if driver:
            driver.quit()
            print("\n👋 Браузер закрито")


if __name__ == "__main__":
    main()
