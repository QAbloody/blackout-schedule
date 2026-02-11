#!/usr/bin/env python3
"""
DTEK Schedule Parser (Selenium)
Парсить графіки відключень з dtek-dnem.com.ua через таблицю
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

DTEK_URL = "https://www.dtek-dnem.com.ua/ua/shutdowns"
CITY = "м. Дніпро"
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

# Еталонні адреси для кожної групи
GROUP_ADDRESSES = {
    "1.1": "пров. Парковий",
    "1.2": "вул. Мохова",
    "3.1": "вул. Центральна",
    "3.2": "вул. Холодильна",
    "5.1": "пров. Морський",
    "5.2": "вул. Автодорожна",
    # Додай після знаходження:
    # "2.1": "вул. ???",
    # "2.2": "вул. ???",
    # "4.1": "вул. ???",
    # "4.2": "вул. ???",
    # "6.1": "вул. ???",
    # "6.2": "вул. ???",
}


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


def slots_to_intervals(slots: List[bool]) -> List[str]:
    """
    Конвертує 48 слотів (по 30 хв) в інтервали
    [True, True, False, False, True, ...] → ["00:00-01:00", "02:00-02:30"]
    """
    if not any(slots):
        return []
    
    intervals = []
    i = 0
    while i < 48:
        if slots[i]:
            start = i
            while i < 48 and slots[i]:
                i += 1
            end = i
            
            start_h, start_m = divmod(start * 30, 60)
            end_h, end_m = divmod(end * 30, 60)
            intervals.append(f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}")
        else:
            i += 1
    
    return intervals


def parse_table(driver, day: str = "today") -> List[bool]:
    """
    Парсить таблицю графіку
    Повертає 48 слотів (по 30 хв): True = немає світла
    """
    slots = [False] * 48
    
    try:
        # Клікаємо на потрібну вкладку (сьогодні/завтра)
        if day == "tomorrow":
            try:
                driver.execute_script("""
                    var tabs = document.querySelectorAll('[class*="tab"], button');
                    for (var t of tabs) {
                        if (t.textContent.toLowerCase().includes('завтра')) {
                            t.click();
                            break;
                        }
                    }
                """)
                time.sleep(1)
            except:
                pass
        
        # Беремо ПЕРШУ таблицю (Table 0) - це графік на сьогодні/завтра
        tables = driver.find_elements(By.TAG_NAME, "table")
        
        if not tables:
            print("    ⚠️ No tables found")
            return slots
        
        table = tables[0]  # Перша таблиця
        
        # Шукаємо tbody tr з комірками
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            
            # Фільтруємо тільки комірки з класами cell-*
            hour_cells = [c for c in cells if c.get_attribute("class") and "cell-" in c.get_attribute("class")]
            
            if not hour_cells:
                continue
            
            for hour, cell in enumerate(hour_cells[:24]):
                cell_class = cell.get_attribute("class") or ""
                
                first_half = False
                second_half = False
                
                if "cell-scheduled" in cell_class and "cell-scheduled-maybe" not in cell_class:
                    first_half, second_half = True, True
                elif "cell-first-half" in cell_class:
                    first_half = True
                elif "cell-second-half" in cell_class:
                    second_half = True
                # cell-non-scheduled = False, False
                
                slots[hour * 2] = first_half
                slots[hour * 2 + 1] = second_half
        
    except Exception as e:
        print(f"    ❌ Parse error: {e}")
    
    return slots


def enter_address(driver, street: str) -> bool:
    """Вводить адресу на сторінці через JavaScript"""
    try:
        # Чекаємо завантаження сторінки
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "city"))
        )
        time.sleep(3)
        
        # Закриваємо popup якщо є
        try:
            driver.execute_script("""
                // Закриваємо модальне вікно DTEK
                var closeBtn = document.querySelector('.modal__close, .m-attention__close, [class*="modal__close"]');
                if (closeBtn) {
                    closeBtn.click();
                    console.log('Closed modal via .modal__close');
                }
                
                // Також закриваємо через overlay
                var overlay = document.querySelector('.modal__overlay');
                if (overlay) {
                    overlay.click();
                }
            """)
            print("    🔍 DEBUG: Tried to close popup")
        except Exception as e:
            print(f"    🔍 DEBUG: Popup close error: {e}")
        
        time.sleep(2)
        
        # Скролимо до форми вводу адреси
        driver.execute_script("""
            var form = document.querySelector('.discon-schedule-form, #city');
            if (form) {
                form.scrollIntoView({behavior: 'instant', block: 'center'});
            } else {
                window.scrollTo(0, 0);  // Скролимо на початок сторінки
            }
        """)
        time.sleep(1)
        time.sleep(1)
        
        # Вводимо місто - симулюємо реальне введення
        try:
            city_input = driver.find_element(By.CSS_SELECTOR, ".discon-schedule-form #city")
            city_input.click()
            time.sleep(0.5)
            city_input.clear()
            
            # Вводимо посимвольно
            for char in CITY:
                city_input.send_keys(char)
                time.sleep(0.05)
            
            time.sleep(1)
            city_value = city_input.get_attribute("value")
            print(f"    🔍 DEBUG: City input value = {city_value}")
        except Exception as e:
            print(f"    🔍 DEBUG: City input error: {e}")
            # Fallback to JavaScript
            driver.execute_script(f"""
                var cityInput = document.querySelector('.discon-schedule-form #city');
                if (cityInput) {{
                    cityInput.focus();
                    cityInput.value = '{CITY}';
                    cityInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            """)
        time.sleep(1)
        
        # Клікаємо на перший елемент автодоповнення міста
        try:
            autocomplete_count = driver.execute_script("""
                var items = document.querySelectorAll('#cityautocomplete-list div');
                return items.length;
            """)
            print(f"    🔍 DEBUG: City autocomplete items = {autocomplete_count}")
            driver.execute_script("""
                var items = document.querySelectorAll('#cityautocomplete-list div');
                if (items.length > 0) items[0].click();
            """)
        except:
            pass
        time.sleep(1)
        
        # Вводимо вулицю - симулюємо реальне введення
        try:
            street_input = driver.find_element(By.CSS_SELECTOR, ".discon-schedule-form #street")
            street_input.click()
            time.sleep(0.5)
            street_input.clear()
            
            # Вводимо посимвольно
            for char in street:
                street_input.send_keys(char)
                time.sleep(0.05)
            
            time.sleep(1)
            street_value = street_input.get_attribute("value")
            print(f"    🔍 DEBUG: Street input value = {street_value}")
        except Exception as e:
            print(f"    🔍 DEBUG: Street input error: {e}")
        time.sleep(1)
        
        # Клікаємо на перший елемент автодоповнення вулиці
        try:
            autocomplete_count = driver.execute_script("""
                var items = document.querySelectorAll('#streetautocomplete-list div');
                return items.length;
            """)
            print(f"    🔍 DEBUG: Street autocomplete items = {autocomplete_count}")
            driver.execute_script("""
                var items = document.querySelectorAll('#streetautocomplete-list div');
                if (items.length > 0) items[0].click();
            """)
        except:
            pass
        time.sleep(2)
        
        # Вводимо номер будинку
        try:
            house_input = driver.find_element(By.CSS_SELECTOR, ".discon-schedule-form #house")
            house_input.click()
            time.sleep(0.5)
            house_input.clear()
            house_input.send_keys("1")
            time.sleep(1)
            house_value = house_input.get_attribute("value")
            print(f"    🔍 DEBUG: House input value = {house_value}")
        except Exception as e:
            print(f"    🔍 DEBUG: House input error: {e}")
        time.sleep(1)
        
        # Вибираємо з автодоповнення будинку
        try:
            autocomplete_count = driver.execute_script("""
                var items = document.querySelectorAll('#houseautocomplete-list div');
                return items.length;
            """)
            print(f"    🔍 DEBUG: House autocomplete items = {autocomplete_count}")
            driver.execute_script("""
                var items = document.querySelectorAll('#houseautocomplete-list div');
                if (items.length > 0) items[0].click();
            """)
        except:
            pass
        time.sleep(2)
        
        # DEBUG: зберігаємо скріншот і HTML
        try:
            debug_path = os.path.join(os.getcwd(), "debug_page.png")
            driver.save_screenshot(debug_path)
            print(f"    🔍 DEBUG: Screenshot saved to {debug_path}")
            
            html_path = os.path.join(os.getcwd(), "debug_page.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"    🔍 DEBUG: HTML saved to {html_path}")
            
            tables = driver.find_elements(By.TAG_NAME, "table")
            print(f"    🔍 DEBUG: Found {len(tables)} tables")
            if tables:
                html = tables[0].get_attribute("outerHTML")
                has_scheduled = "cell-scheduled" in html and "cell-scheduled-maybe" not in html.split("cell-scheduled")[0]
                has_first = "cell-first-half" in html
                has_second = "cell-second-half" in html
                print(f"    🔍 DEBUG: Table 0 has scheduled={has_scheduled}, first-half={has_first}, second-half={has_second}")
                
                # Покажемо перші 500 символів таблиці
                print(f"    🔍 DEBUG: Table 0 HTML: {html[:500]}")
        except Exception as e:
            print(f"    🔍 DEBUG error: {e}")
        
        # Перевіряємо чи з'явилась таблиця з графіком
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody td.cell-scheduled, table tbody td.cell-first-half, table tbody td.cell-second-half, table tbody td.cell-non-scheduled"))
            )
            return True
        except:
            # Спробуємо натиснути кнопку якщо є
            try:
                driver.execute_script("""
                    var btns = document.querySelectorAll('button[type="submit"], .btn-search, input[type="submit"]');
                    if (btns.length > 0) btns[0].click();
                """)
                time.sleep(2)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody td.cell-scheduled, table tbody td.cell-first-half, table tbody td.cell-second-half, table tbody td.cell-non-scheduled"))
                )
                return True
            except:
                print("    ⚠️ Table not found after address input")
                return False
        
    except Exception as e:
        print(f"    ❌ Address error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🚀 DTEK Schedule Parser (Table)")
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
    
    driver = None
    
    try:
        driver = setup_driver()
        
        for group, street in GROUP_ADDRESSES.items():
            print(f"📍 Група {group}: {street}...")
            
            # Відкриваємо сторінку заново для кожної групи
            driver.get(DTEK_URL)
            time.sleep(2)
            
            # Вводимо адресу
            if not enter_address(driver, street):
                print(f"    ⚠️ Не вдалося ввести адресу")
                continue
            
            # Парсимо таблицю (сьогодні)
            slots_today = parse_table(driver, "today")
            intervals_today = slots_to_intervals(slots_today)
            
            if intervals_today:
                result["today"]["groups"][group] = intervals_today
                total_mins = sum(slots_today) * 30
                print(f"    ✅ Сьогодні: {intervals_today} ({total_mins // 60}год {total_mins % 60:02d}хв)")
            else:
                print(f"    ✅ Сьогодні: відключень немає")
            
            # Парсимо таблицю (завтра) - якщо є вкладка
            try:
                slots_tomorrow = parse_table(driver, "tomorrow")
                intervals_tomorrow = slots_to_intervals(slots_tomorrow)
                
                if intervals_tomorrow and intervals_tomorrow != intervals_today:
                    result["tomorrow"]["groups"][group] = intervals_tomorrow
                    print(f"    ✅ Завтра: {intervals_tomorrow}")
            except:
                pass
        
        # Зберігаємо
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 Збережено: {SCHEDULE_FILE}")
        
        # Підсумок
        print("\n" + "=" * 60)
        print("📊 ПІДСУМОК:")
        print(f"  Сьогодні: {len(result['today']['groups'])} груп")
        print(f"  Завтра: {len(result['tomorrow']['groups'])} груп")
        
        for group in sorted(result["today"]["groups"].keys()):
            ivs = result["today"]["groups"][group]
            total = sum(
                (int(iv.split("-")[1].split(":")[0]) * 60 + int(iv.split("-")[1].split(":")[1])) -
                (int(iv.split("-")[0].split(":")[0]) * 60 + int(iv.split("-")[0].split(":")[1]))
                for iv in ivs
            )
            print(f"    {group}: {total // 60}год {total % 60:02d}хв")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        if driver:
            driver.quit()
            print("\n👋 Браузер закрито")


if __name__ == "__main__":
    main()
