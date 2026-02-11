#!/usr/bin/env python3
"""
DTEK Schedule Parser - Using Selenium ActionChains
"""

import os
import json
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DTEK_URL = "https://www.dtek-dnem.com.ua/ua/shutdowns"
CITY = "м. Дніпро"
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

GROUP_ADDRESSES = {
    "1.1": "пров. Парковий",
    "1.2": "вул. Мохова",
    "3.1": "вул. Центральна",
    "3.2": "вул. Холодильна",
    "5.1": "пров. Морський",
    "5.2": "вул. Автодорожна",
}


def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def slots_to_intervals(slots):
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
            sh, sm = divmod(start * 30, 60)
            eh, em = divmod(end * 30, 60)
            intervals.append(f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}")
        else:
            i += 1
    return intervals


def close_popup(driver):
    """Закриває popup"""
    try:
        driver.execute_script("""
            var closeBtn = document.querySelector('.modal__close, .m-attention__close');
            if (closeBtn) closeBtn.click();
        """)
        time.sleep(1)
    except:
        pass


def fill_form(driver, street):
    """Заповнює форму через ActionChains"""
    actions = ActionChains(driver)
    
    try:
        # Чекаємо форму
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".discon-schedule-form #city"))
        )
        
        # Закриваємо popup
        close_popup(driver)
        time.sleep(2)
        
        # === МІСТО ===
        city_input = driver.find_element(By.CSS_SELECTOR, ".discon-schedule-form #city")
        
        # Скролимо до елемента
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", city_input)
        time.sleep(0.5)
        
        # Клікаємо через JavaScript
        driver.execute_script("arguments[0].click(); arguments[0].focus();", city_input)
        time.sleep(0.5)
        
        # Вводимо текст через ActionChains
        actions.move_to_element(city_input).click().send_keys(CITY).perform()
        time.sleep(2)
        
        city_value = city_input.get_attribute("value")
        print(f"    🔍 City value: {city_value}")
        
        # Клікаємо на перший елемент автодоповнення
        try:
            autocomplete = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#cityautocomplete-list div, [class*='autocomplete'] div"))
            )
            autocomplete.click()
            print(f"    🔍 City autocomplete clicked")
        except:
            # Якщо немає автодоповнення - натискаємо Enter
            city_input.send_keys(Keys.RETURN)
            print(f"    🔍 City: pressed Enter")
        time.sleep(2)
        
        # === ВУЛИЦЯ ===
        street_input = driver.find_element(By.CSS_SELECTOR, ".discon-schedule-form #street")
        
        # Перевіряємо чи активна
        if street_input.get_attribute("disabled"):
            driver.execute_script("arguments[0].disabled = false;", street_input)
        
        driver.execute_script("arguments[0].click(); arguments[0].focus();", street_input)
        time.sleep(0.5)
        
        actions = ActionChains(driver)
        actions.move_to_element(street_input).click().send_keys(street).perform()
        time.sleep(2)
        
        street_value = street_input.get_attribute("value")
        print(f"    🔍 Street value: {street_value}")
        
        # Клікаємо на автодоповнення
        try:
            autocomplete = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#streetautocomplete-list div, [class*='autocomplete'] div"))
            )
            autocomplete.click()
            print(f"    🔍 Street autocomplete clicked")
        except:
            street_input.send_keys(Keys.RETURN)
            print(f"    🔍 Street: pressed Enter")
        time.sleep(2)
        
        # === БУДИНОК ===
        try:
            house_input = driver.find_element(By.CSS_SELECTOR, ".discon-schedule-form #house_num")
            
            if house_input.get_attribute("disabled"):
                driver.execute_script("arguments[0].disabled = false;", house_input)
            
            driver.execute_script("arguments[0].click(); arguments[0].focus();", house_input)
            time.sleep(0.5)
            
            actions = ActionChains(driver)
            actions.move_to_element(house_input).click().send_keys("1").perform()
            time.sleep(1.5)
            
            house_value = house_input.get_attribute("value")
            print(f"    🔍 House value: {house_value}")
            
            # Клікаємо на автодоповнення
            try:
                autocomplete = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#house_numautocomplete-list div, [class*='autocomplete'] div"))
                )
                autocomplete.click()
            except:
                house_input.send_keys(Keys.RETURN)
        except Exception as e:
            print(f"    🔍 House error: {e}")
        
        time.sleep(3)
        return True
        
    except Exception as e:
        print(f"    ❌ Form error: {e}")
        return False


def parse_schedule(driver):
    """Парсить таблицю з графіком"""
    slots = [False] * 48
    
    try:
        tables = driver.find_elements(By.TAG_NAME, "table")
        print(f"    🔍 Found {len(tables)} tables")
        
        for t in tables:
            html = t.get_attribute("outerHTML")
            # Шукаємо таблицю БЕЗ head-time (це графік на сьогодні)
            if "head-time" not in html and "Понеділок" not in html:
                cells = t.find_elements(By.CSS_SELECTOR, "tbody td[class*='cell-']")
                print(f"    🔍 Schedule table found, cells: {len(cells)}")
                
                for i, cell in enumerate(cells[:24]):
                    cls = cell.get_attribute("class")
                    first = "cell-scheduled" in cls and "maybe" not in cls
                    second = first
                    if "cell-first-half" in cls:
                        first, second = True, False
                    if "cell-second-half" in cls:
                        first, second = False, True
                    slots[i * 2] = first
                    slots[i * 2 + 1] = second
                break
    except Exception as e:
        print(f"    ❌ Parse error: {e}")
    
    return slots


def main():
    print("=" * 60)
    print("🚀 DTEK Schedule Parser")
    print("=" * 60)
    
    now = datetime.now()
    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")
    
    print(f"\n📅 Сьогодні: {today}")
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
            
            driver.get(DTEK_URL)
            time.sleep(3)
            
            if fill_form(driver, street):
                slots = parse_schedule(driver)
                
                if any(slots):
                    intervals = slots_to_intervals(slots)
                    result["today"]["groups"][group] = intervals
                    total = sum(slots) * 30
                    print(f"    ✅ {intervals} ({total // 60}год {total % 60:02d}хв)")
                else:
                    print(f"    ✅ Відключень немає")
            else:
                print(f"    ⚠️ Form failed")
            
            # Debug screenshot (only first)
            if group == "1.1":
                try:
                    driver.save_screenshot("debug_page.png")
                    with open("debug_page.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                except:
                    pass
        
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 Збережено: {SCHEDULE_FILE}")
        print(f"📊 Груп з графіком: {len(result['today']['groups'])}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            driver.quit()
            print("👋 Done")


if __name__ == "__main__":
    main()
