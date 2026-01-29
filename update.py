#!/usr/bin/env python3
"""
Парсер графіків відключень з static.yasno.ua
Підтримує DTEK та ЦЕК для Дніпра
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, List, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


YASNO_URL = "https://static.yasno.ua/dnipro/outages"
TIMEZONE = "Europe/Kyiv"
ALL_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]

# Файли для збереження
DTEK_FILE = os.getenv("DTEK_FILE", "schedule.json")
CEK_FILE = os.getenv("CEK_FILE", "schedule_cek.json")


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
    """Конвертує список хвилин у інтервали"""
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
    """Парсить таблицю графіку"""
    groups = {}
    rows = driver.find_elements(By.CSS_SELECTOR, "[class*='_row_']")
    
    for row in rows:
        try:
            row_text = row.text.strip()
            
            # Шукаємо групу
            group_id = None
            for g in ALL_GROUPS:
                if row_text.startswith(g) or f"\n{g}\n" in f"\n{row_text}\n":
                    group_id = g
                    break
            
            if not group_id:
                continue
            
            # Парсимо комірки (перша — номер групи, пропускаємо)
            cells = row.find_elements(By.CSS_SELECTOR, "[class*='_cell_']")
            outage_minutes = []
            
            # Пропускаємо першу комірку (номер групи), беремо наступні 24
            time_cells = cells[1:25] if len(cells) > 24 else cells[1:]
            
            for hour, cell in enumerate(time_cells):
                cell_html = cell.get_attribute("innerHTML") or ""
                
                if "_definite_" not in cell_html:
                    continue
                
                # Парсимо кожен блок _definite_ окремо
                definite_parts = cell_html.split("_definite_")
                for part in definite_parts[1:]:
                    block = part[:part.find("</div>")] if "</div>" in part else part[:200]
                    
                    has_50_width = "width: 50%" in block or "width:50%" in block
                    
                    if has_50_width:
                        if "left: 0%" in block or "left:0%" in block:
                            outage_minutes.append(hour * 60)
                        elif "left: 50%" in block or "left:50%" in block:
                            outage_minutes.append(hour * 60 + 30)
                    else:
                        outage_minutes.append(hour * 60)
                        outage_minutes.append(hour * 60 + 30)
            
            if outage_minutes:
                groups[group_id] = minutes_to_intervals(outage_minutes)
                
        except Exception as e:
            print(f"  Row error: {e}")
    
    return groups


def select_osr(driver, osr_name: str) -> bool:
    """Вибирає ОСР (DTEK або ЦЕК) у випадаючому списку"""
    try:
        print(f"  Selecting OSR: {osr_name}")
        time.sleep(1)
        
        # Шукаємо dropdown button з класом osrSelect або y-select-field
        try:
            osr_dropdown = driver.find_element(By.CSS_SELECTOR, "button[class*='osrSelect'], button[class*='y-select-field']")
        except:
            # Fallback - шукаємо button що містить ДТЕК/ЦЕК
            buttons = driver.find_elements(By.CSS_SELECTOR, "button")
            osr_dropdown = None
            for btn in buttons:
                txt = btn.text.upper()
                if "ДТЕК" in txt or "ЦЕК" in txt or "DTEK" in txt:
                    osr_dropdown = btn
                    break
        
        if not osr_dropdown:
            print(f"  ⚠️ OSR dropdown not found")
            return False
        
        # Клікаємо щоб відкрити
        osr_dropdown.click()
        time.sleep(1)
        
        # Шукаємо опцію - li з класом _item_
        options = driver.find_elements(By.CSS_SELECTOR, "li[class*='_item_']")
        for opt in options:
            opt_text = opt.text.strip().upper()
            if osr_name.upper() in opt_text:
                opt.click()
                print(f"  ✅ Selected: {opt.text.strip()}")
                time.sleep(2)
                return True
        
        print(f"  ⚠️ Option '{osr_name}' not found in {len(options)} items")
        return False
        
    except Exception as e:
        print(f"  OSR selection error: {e}")
        return False


def click_tab(driver, tab_text: str) -> bool:
    """Натискає вкладку 'Сьогодні' або 'Завтра'"""
    try:
        time.sleep(1)
        
        # Шукаємо по id який містить "tomorrow" або "today"
        tab_id = "tomorrow" if "завтра" in tab_text.lower() else "today"
        
        try:
            tab = driver.find_element(By.CSS_SELECTOR, f"button[id*='{tab_id}'], [id*='{tab_id}']")
            if tab.is_displayed():
                tab.click()
                print(f"  ✅ Clicked tab by id: {tab_id}")
                time.sleep(2)
                return True
        except:
            pass
        
        # Fallback - шукаємо button з класом y-segmented__option
        try:
            tabs = driver.find_elements(By.CSS_SELECTOR, "button[class*='segmented__option'], button[class*='_option_']")
            for tab in tabs:
                if tab_text.lower() in tab.text.lower():
                    tab.click()
                    print(f"  ✅ Clicked tab: {tab.text}")
                    time.sleep(2)
                    return True
        except:
            pass
        
        # Шукаємо будь-який button з текстом
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if tab_text.lower() in btn.text.lower():
                btn.click()
                print(f"  ✅ Clicked button: {btn.text}")
                time.sleep(2)
                return True
        
        print(f"  ⚠️ Tab '{tab_text}' not found")
        return False
        
    except Exception as e:
        print(f"  Tab click error: {e}")
        return False


def get_date_from_tab(driver, is_today: bool) -> str:
    """Отримує дату з активної вкладки"""
    try:
        if is_today:
            return datetime.now().strftime("%d.%m.%Y")
        else:
            from datetime import timedelta
            return (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    except:
        return ""


def parse_osr(driver, osr_name: str) -> Dict[str, Any]:
    """Парсить графіки для одного ОСР"""
    result = {"timezone": TIMEZONE, "today": {"date": "", "groups": {}}, "tomorrow": {"date": "", "groups": {}}}
    
    print(f"\n📊 Parsing {osr_name}...")
    
    # Вибираємо ОСР
    if osr_name != "DTEK":
        if not select_osr(driver, osr_name):
            print(f"  ⚠️ Could not select {osr_name}, using default")
    
    time.sleep(2)
    
    # Парсимо сьогодні
    print("  📅 Parsing today...")
    result["today"]["date"] = get_date_from_tab(driver, True)
    result["today"]["groups"] = parse_table(driver)
    print(f"  ✅ Today: {len(result['today']['groups'])} groups")
    
    # Парсимо завтра
    print("  📅 Parsing tomorrow...")
    if click_tab(driver, "Завтра"):
        time.sleep(2)
        result["tomorrow"]["date"] = get_date_from_tab(driver, False)
        result["tomorrow"]["groups"] = parse_table(driver)
        print(f"  ✅ Tomorrow: {len(result['tomorrow']['groups'])} groups")
        
        # Повертаємось на сьогодні
        click_tab(driver, "Сьогодні")
    else:
        print("  ⚠️ Tomorrow tab not found")
    
    return result


def save_schedule(data: Dict[str, Any], filepath: str):
    """Зберігає графік у JSON"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved: {filepath}")


def main():
    print("=" * 50)
    print("🚀 YASNO Schedule Parser (DTEK + ЦЕК)")
    print("=" * 50)
    
    driver = None
    try:
        driver = setup_driver()
        print(f"\n🌐 Loading {YASNO_URL}")
        driver.get(YASNO_URL)
        
        # Чекаємо завантаження таблиці
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='_row_']"))
        )
        print("✅ Page loaded")
        time.sleep(3)
        
        # Парсимо DTEK (за замовчуванням)
        dtek_data = parse_osr(driver, "DTEK")
        save_schedule(dtek_data, DTEK_FILE)
        
        # Перезавантажуємо сторінку для ЦЕК
        print("\n🔄 Reloading for CEK...")
        driver.get(YASNO_URL)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='_row_']"))
        )
        time.sleep(3)
        
        # Парсимо ЦЕК
        cek_data = parse_osr(driver, "ЦЕК")
        save_schedule(cek_data, CEK_FILE)
        
        # Підсумок
        print("\n" + "=" * 50)
        print("📊 Summary:")
        print(f"  DTEK: {sum(len(g) for g in dtek_data['today']['groups'].values())} intervals today")
        print(f"  ЦЕК:  {sum(len(g) for g in cek_data['today']['groups'].values())} intervals today")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Зберігаємо HTML для дебагу
        if driver:
            try:
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("📄 Debug HTML saved to debug_page.html")
            except:
                pass
        
        sys.exit(1)
        
    finally:
        if driver:
            driver.quit()
            print("\n👋 Browser closed")


if __name__ == "__main__":
    main()
