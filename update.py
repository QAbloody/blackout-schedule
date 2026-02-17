#!/usr/bin/env python3
"""
DTEK + YASNO Schedule Parser
- DTEK для груп 1.1, 1.2, 3.1, 3.2, 5.1, 5.2
- YASNO API для груп 2.1, 2.2, 4.1, 4.2, 6.1, 6.2
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DTEK_URL = "https://www.dtek-dnem.com.ua/ua/shutdowns"
YASNO_API = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"
CITY = "м. Дніпро"
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

# DTEK групи (парсимо через Selenium)
DTEK_GROUPS = {
    "1.1": "пров. Парковий",
    "1.2": "вул. Мохова",
    "3.1": "вул. Центральна",
    "3.2": "вул. Холодильна",
    "5.1": "пров. Морський",
    "5.2": "вул. Автодорожна",
}

# YASNO групи (парсимо через API)
YASNO_GROUPS = ["2.1", "2.2", "4.1", "4.2", "6.1", "6.2"]


def fetch_yasno_schedule():
    """Отримує графіки з YASNO API для груп 2.x, 4.x, 6.x"""
    result = {"today": {}, "tomorrow": {}}
    
    try:
        print("\n📡 Завантаження YASNO API...")
        r = requests.get(YASNO_API, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        # Знаходимо компонент з графіками
        components = data.get("components", [])
        schedule_data = None
        
        for comp in components:
            if comp.get("template_name") == "electricity-outages-daily-schedule":
                schedule_data = comp.get("schedule", {}).get("dnipro", {})
                break
        
        if not schedule_data:
            print("   ⚠️ Графіки YASNO не знайдено")
            return result
        
        # Визначаємо день тижня (0=пн, 6=нд)
        today_weekday = datetime.now().weekday()
        tomorrow_weekday = (today_weekday + 1) % 7
        
        for group in YASNO_GROUPS:
            group_key = f"group_{group}"
            group_data = schedule_data.get(group_key, [])
            
            if not group_data or len(group_data) < 7:
                continue
            
            # Парсимо сьогодні
            today_slots = group_data[today_weekday]
            today_intervals = yasno_slots_to_intervals(today_slots)
            if today_intervals:
                result["today"][group] = today_intervals
            
            # Парсимо завтра
            tomorrow_slots = group_data[tomorrow_weekday]
            tomorrow_intervals = yasno_slots_to_intervals(tomorrow_slots)
            if tomorrow_intervals:
                result["tomorrow"][group] = tomorrow_intervals
            
            total_today = sum_intervals(today_intervals)
            total_tomorrow = sum_intervals(tomorrow_intervals)
            print(f"   📍 Група {group}: сьогодні {total_today//60}год {total_today%60:02d}хв, завтра {total_tomorrow//60}год {total_tomorrow%60:02d}хв")
        
        print(f"   ✅ YASNO: {len(result['today'])} груп")
        
    except Exception as e:
        print(f"   ❌ YASNO API error: {e}")
    
    return result


def yasno_slots_to_intervals(slots):
    """Конвертує слоти YASNO в інтервали"""
    if not slots:
        return []
    
    intervals = []
    for slot in slots:
        start = slot.get("start", 0)
        end = slot.get("end", 0)
        slot_type = slot.get("type", "")
        
        # Беремо тільки DEFINITE_OUTAGE або POSSIBLE_OUTAGE
        if "OUTAGE" in slot_type:
            # Конвертуємо години в формат HH:MM
            sh = int(start)
            sm = int((start - sh) * 60)
            eh = int(end)
            em = int((end - eh) * 60)
            
            if eh == 24:
                eh = 24
                em = 0
            
            intervals.append(f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}")
    
    # Об'єднуємо суміжні інтервали
    return merge_intervals(intervals)


def merge_intervals(intervals):
    """Об'єднує суміжні інтервали"""
    if not intervals:
        return []
    
    # Сортуємо по початку
    sorted_ivs = sorted(intervals)
    merged = [sorted_ivs[0]]
    
    for iv in sorted_ivs[1:]:
        last_end = merged[-1].split("-")[1]
        curr_start = iv.split("-")[0]
        
        if last_end == curr_start:
            # Об'єднуємо
            merged[-1] = merged[-1].split("-")[0] + "-" + iv.split("-")[1]
        else:
            merged.append(iv)
    
    return merged


def sum_intervals(intervals):
    """Сумує тривалість інтервалів в хвилинах"""
    total = 0
    for iv in intervals:
        parts = iv.split("-")
        if len(parts) == 2:
            sh, sm = map(int, parts[0].split(":"))
            eh, em = map(int, parts[1].split(":"))
            start = sh * 60 + sm
            end = eh * 60 + em if eh != 24 else 24 * 60
            total += end - start
    return total


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


def save_history(result):
    """Зберігає історію графіків для прогнозування"""
    history_file = "history.json"
    
    try:
        # Завантажуємо існуючу історію
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = {"days": {}}
        
        # Додаємо сьогоднішні дані
        today_date = result["today"]["date"]
        today_groups = result["today"]["groups"]
        
        if today_date and today_groups:
            # Зберігаємо тільки якщо є дані
            history["days"][today_date] = {
                "groups": today_groups,
                "updated": result["updated"]
            }
        
        # Видаляємо старі записи (більше 30 днів)
        if len(history["days"]) > 30:
            sorted_dates = sorted(history["days"].keys())
            for old_date in sorted_dates[:-30]:
                del history["days"][old_date]
        
        # Зберігаємо
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        
        print(f"📚 Історія: {len(history['days'])} днів")
        
    except Exception as e:
        print(f"⚠️ History error: {e}")


def close_popup(driver):
    """Закриває popup і повертає текст повідомлення"""
    message = None
    is_emergency = False
    
    try:
        # Читаємо текст popup
        popup = driver.find_element(By.CSS_SELECTOR, ".modal__container, .m-attention__container, [class*='modal'][class*='container']")
        if popup:
            full_text = popup.text.strip()
            
            # Беремо тільки перший абзац або перші 2-3 речення
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]
            
            # Пропускаємо заголовок типу "Шановні клієнти!"
            start_idx = 0
            skip_phrases = ["шановні", "увага", "dear", "дорогі"]
            if lines and any(p in lines[0].lower() for p in skip_phrases):
                start_idx = 1
            
            # Беремо наступні 1-2 рядки (зазвичай це основна інформація)
            important_lines = lines[start_idx:start_idx + 2]
            message = " ".join(important_lines)
            
            # Обрізаємо якщо занадто довге (макс 200 символів)
            if len(message) > 200:
                # Знаходимо кінець речення
                for end in ['. ', '! ', '? ']:
                    idx = message[:200].rfind(end)
                    if idx > 50:
                        message = message[:idx + 1]
                        break
                else:
                    message = message[:197] + "..."
            
            # Перевіряємо на екстрені відключення
            emergency_keywords = [
                "екстрен",
                "аварій",
                "терміново",
                "негайно",
                "надзвичайн",
                "без графік",
                "цілодобов",
                "00:00 до 24:00",
                "весь день",
            ]
            
            message_lower = full_text.lower()
            for keyword in emergency_keywords:
                if keyword in message_lower:
                    is_emergency = True
                    break
        
        # Закриваємо popup
        close_btn = driver.find_element(By.CSS_SELECTOR, ".modal__close, .m-attention__close")
        if close_btn:
            close_btn.click()
        time.sleep(1)
        
    except:
        pass
    
    return message, is_emergency


def fill_form(driver, street):
    """Заповнює форму через ActionChains. Повертає (success, popup_message, is_emergency)"""
    actions = ActionChains(driver)
    popup_message = None
    is_emergency = False
    
    try:
        # Чекаємо форму
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".discon-schedule-form #city"))
        )
        
        # Закриваємо popup і читаємо повідомлення
        popup_message, is_emergency = close_popup(driver)
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
        
        # Клікаємо на перший елемент автодоповнення
        try:
            autocomplete = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#cityautocomplete-list div, [class*='autocomplete'] div"))
            )
            autocomplete.click()
        except:
            city_input.send_keys(Keys.RETURN)
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
        
        # Клікаємо на автодоповнення
        try:
            autocomplete = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#streetautocomplete-list div, [class*='autocomplete'] div"))
            )
            autocomplete.click()
        except:
            street_input.send_keys(Keys.RETURN)
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
            
            # Клікаємо на автодоповнення
            try:
                autocomplete = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#house_numautocomplete-list div, [class*='autocomplete'] div"))
                )
                autocomplete.click()
            except:
                house_input.send_keys(Keys.RETURN)
        except Exception as e:
            pass
        
        time.sleep(3)
        return True, popup_message, is_emergency
        
    except Exception as e:
        print(f"    ❌ Form error: {e}")
        return False, popup_message, is_emergency


def parse_schedule(driver, day="today"):
    """Парсить таблицю з графіком. day = 'today' або 'tomorrow'"""
    slots = [False] * 48
    
    try:
        # Якщо потрібен завтрашній день - клікаємо на другу таблицю
        if day == "tomorrow":
            try:
                # Знаходимо всі таби графіків
                tabs = driver.find_elements(By.CSS_SELECTOR, ".discon-fact-table")
                if len(tabs) >= 2:
                    # Спробуємо кілька методів кліку
                    tab = tabs[1]
                    
                    # Метод 1: Клік на thead (заголовок таблиці)
                    try:
                        thead = tab.find_element(By.TAG_NAME, "thead")
                        thead.click()
                        time.sleep(1)
                    except:
                        pass
                    
                    # Метод 2: Якщо не спрацювало - JavaScript з classList
                    if "active" not in tab.get_attribute("class"):
                        driver.execute_script("""
                            var tabs = document.querySelectorAll('.discon-fact-table');
                            tabs.forEach(t => t.classList.remove('active'));
                            arguments[0].classList.add('active');
                        """, tab)
                        time.sleep(0.5)
                    
            except Exception as e:
                pass
        
        # Знаходимо активну таблицю
        active_table = driver.find_element(By.CSS_SELECTOR, ".discon-fact-table.active table")
        cells = active_table.find_elements(By.CSS_SELECTOR, "tbody td[class*='cell-']")
        
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
                
    except Exception as e:
        pass
    
    return slots


def main():
    print("=" * 60)
    print("🚀 DTEK + YASNO Schedule Parser")
    print("=" * 60)
    
    now = datetime.now()
    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")
    
    print(f"\n📅 Сьогодні: {today}")
    print(f"📋 DTEK груп: {len(DTEK_GROUPS)}")
    print(f"📋 YASNO груп: {len(YASNO_GROUPS)}\n")
    
    result = {
        "timezone": "Europe/Kyiv",
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "dtek-dnem.com.ua + yasno.com.ua",
        "emergency": None,
        "today": {"date": today, "groups": {}},
        "tomorrow": {"date": tomorrow, "groups": {}}
    }
    
    # === DTEK (Selenium) ===
    print("=" * 40)
    print("📡 DTEK (групи 1.x, 3.x, 5.x)")
    print("=" * 40)
    
    driver = None
    
    try:
        driver = setup_driver()
        
        popup_message = None
        is_emergency = False
        
        for group, street in DTEK_GROUPS.items():
            print(f"📍 Група {group}: {street}...")
            
            driver.get(DTEK_URL)
            time.sleep(3)
            
            success, msg, emergency = fill_form(driver, street)
            
            # Зберігаємо popup повідомлення (тільки перший раз)
            if msg and not popup_message:
                popup_message = msg
                is_emergency = emergency
                print(f"    📢 {msg}")
                if is_emergency:
                    print(f"    ⚠️ ЕКСТРЕНЕ!")
            
            if success:
                # Парсимо сьогодні
                slots_today = parse_schedule(driver, "today")
                
                if any(slots_today):
                    intervals = slots_to_intervals(slots_today)
                    result["today"]["groups"][group] = intervals
                    total = sum(slots_today) * 30
                    print(f"    📊 Сьогодні: {intervals} ({total // 60}год {total % 60:02d}хв)")
                else:
                    print(f"    📊 Сьогодні: відключень немає")
                
                # Парсимо завтра
                slots_tomorrow = parse_schedule(driver, "tomorrow")
                
                if any(slots_tomorrow):
                    intervals = slots_to_intervals(slots_tomorrow)
                    result["tomorrow"]["groups"][group] = intervals
                    total = sum(slots_tomorrow) * 30
                    print(f"    📅 Завтра: {intervals} ({total // 60}год {total % 60:02d}хв)")
                else:
                    print(f"    📅 Завтра: відключень немає")
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
        
        # Зберігаємо popup повідомлення в результат
        if popup_message:
            result["announcement"] = popup_message
            if is_emergency:
                result["emergency"] = popup_message
        
    except Exception as e:
        print(f"\n❌ DTEK Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            driver.quit()
    
    # === YASNO API ===
    print("\n" + "=" * 40)
    print("📡 YASNO API (групи 2.x, 4.x, 6.x)")
    print("=" * 40)
    
    yasno_data = fetch_yasno_schedule()
    
    # Додаємо YASNO графіки до результату
    for group, intervals in yasno_data["today"].items():
        result["today"]["groups"][group] = intervals
    
    for group, intervals in yasno_data["tomorrow"].items():
        result["tomorrow"]["groups"][group] = intervals
    
    # === Зберігаємо результат ===
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # Зберігаємо історію для прогнозування
    save_history(result)
    
    print(f"\n💾 Збережено: {SCHEDULE_FILE}")
    print(f"📊 Сьогодні: {len(result['today']['groups'])} груп")
    print(f"📅 Завтра: {len(result['tomorrow']['groups'])} груп")
    print("👋 Done")


if __name__ == "__main__":
    main()
